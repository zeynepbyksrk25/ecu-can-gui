"""Gerçek zamanlı grafik sekmesi (SRS Faz 4, genişletilmiş): işaretlenen
Measurement'ların CCP ile periyodik okunup zaman grafiğinde çizilmesi.

Genişletmeler:
  - Birden fazla BAĞIMSIZ grafik paneli (tile) eklenip kaldırılabilir;
    her panelin kendi sinyal seçici listesi ve kendi çizim alanı vardır.
  - Her panelde "sensör takibi": fare ile grafik üzerinde gezinince,
    dikey/yatay çizgilerle birlikte o andaki en yakın örneğin değeri
    canlı olarak bir etiket üzerinde gösterilir (pyqtgraph crosshair).

Diğer sekmeler gibi gerçek CCP okuma işlemini burada YAPMAZ — periyodik
tetiklemeyi (read_requested) dışarı bildirir, MainWindow her tur için
CCPClient'ı çağırıp append_sample() ile sonucu geri besler. Aynı sinyal
birden fazla panelde işaretlenmişse, gelen örnek TÜM ilgili panellere
dağıtılır.
"""

import time

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

POLL_INTERVAL_MS = 250
MAX_POINTS = 800  # ~200 saniyelik pencere (250ms * 800)

_PALETTE = ["#00c2b8", "#e5484d", "#3ecf8e", "#9467bd", "#f0a020", "#17becf"]


class _GraphTile(QWidget):
    """Tek bir bağımsız grafik paneli: kendi sinyal seçici listesi +
    kendi çizim alanı + kendi crosshair'i (sensör takibi)."""

    selection_changed = Signal()
    remove_requested = Signal(object)  # self

    def __init__(self, tile_number: int):
        super().__init__()
        self.tile_number = tile_number
        self._series: dict[str, dict] = {}   # name -> {"x": [...], "y": [...], "curve": PlotDataItem}
        self._color_index = 0
        self._checked_names: set[str] = set()

        box = QGroupBox(f"Panel {tile_number}")
        outer = QVBoxLayout(box)

        top_row = QHBoxLayout()
        left = QVBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("İsme göre ara...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        left.addWidget(self.search_edit)
        self.list_widget = QListWidget()
        self.list_widget.setMaximumHeight(110)
        self.list_widget.itemChanged.connect(self._on_item_checked)
        left.addWidget(self.list_widget)
        top_row.addLayout(left, stretch=1)

        side = QVBoxLayout()
        self.remove_button = QPushButton("Bu Paneli Kaldır")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        side.addWidget(self.remove_button)
        self.crosshair_label = QLabel("Sensör takibi: fareyi grafik üzerine getirin")
        self.crosshair_label.setWordWrap(True)
        side.addWidget(self.crosshair_label)
        side.addStretch()
        top_row.addLayout(side)
        outer.addLayout(top_row)

        pg.setConfigOptions(antialias=True)
        self.plot_widget = pg.PlotWidget(background="#1a222c")
        self.plot_widget.addLegend()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("bottom", "Zaman (s)")
        outer.addWidget(self.plot_widget, stretch=1)

        # ---- Crosshair / sensör takibi ----
        self._v_line = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#8ea0b0", width=1))
        self._h_line = pg.InfiniteLine(angle=0, movable=False, pen=pg.mkPen("#8ea0b0", width=1))
        self.plot_widget.addItem(self._v_line, ignoreBounds=True)
        self.plot_widget.addItem(self._h_line, ignoreBounds=True)
        self._v_line.setVisible(False)
        self._h_line.setVisible(False)
        self._proxy = pg.SignalProxy(
            self.plot_widget.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse_moved
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)

    def populate_measurements(self, names: list):
        checked_before = set(self._checked_names)
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        for name in names:
            item = QListWidgetItem(name)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if name in checked_before else Qt.Unchecked)
            self.list_widget.addItem(item)
        self.list_widget.blockSignals(False)
        self._apply_filter(self.search_edit.text())

    def _apply_filter(self, text: str):
        """Listeyi isme göre süzer; gizli öğelerin işareti korunur."""
        text = text.strip().lower()
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setHidden(bool(text) and text not in item.text().lower())

    def _on_item_checked(self, item: QListWidgetItem):
        name = item.text()
        if item.checkState() == Qt.Checked:
            self._checked_names.add(name)
            self._ensure_series(name)
        else:
            self._checked_names.discard(name)
        self.selection_changed.emit()

    def checked_names(self) -> set:
        return set(self._checked_names)

    def _ensure_series(self, name: str):
        if name in self._series:
            return
        color = _PALETTE[self._color_index % len(_PALETTE)]
        self._color_index += 1
        curve = self.plot_widget.plot([], [], pen=pg.mkPen(color, width=2), name=name)
        self._series[name] = {"x": [], "y": [], "curve": curve}

    def append_sample(self, name: str, value: float, t: float):
        if name not in self._checked_names:
            return
        self._ensure_series(name)
        series = self._series[name]
        series["x"].append(t)
        series["y"].append(value)
        if len(series["x"]) > MAX_POINTS:
            series["x"] = series["x"][-MAX_POINTS:]
            series["y"] = series["y"][-MAX_POINTS:]
        series["curve"].setData(series["x"], series["y"])

    def clear(self):
        for series in self._series.values():
            series["x"].clear()
            series["y"].clear()
            series["curve"].setData([], [])

    def _on_mouse_moved(self, event):
        pos = event[0]
        if not self.plot_widget.sceneBoundingRect().contains(pos):
            self._v_line.setVisible(False)
            self._h_line.setVisible(False)
            return
        mouse_point = self.plot_widget.getPlotItem().vb.mapSceneToView(pos)
        x = mouse_point.x()
        self._v_line.setPos(x)
        self._h_line.setPos(mouse_point.y())
        self._v_line.setVisible(True)
        self._h_line.setVisible(True)

        lines = []
        for name, series in self._series.items():
            if not series["x"]:
                continue
            # en yakın örneği bul (basit doğrusal arama; MAX_POINTS küçük olduğu için yeterli)
            closest_i = min(range(len(series["x"])), key=lambda i: abs(series["x"][i] - x))
            lines.append(f"{name}: {series['y'][closest_i]:.4g}  (t={series['x'][closest_i]:.1f}s)")
        self.crosshair_label.setText("\n".join(lines) if lines else "Sensör takibi: veri yok")


class GraphTab(QWidget):
    read_requested = Signal(list)  # o an TÜM panellerde işaretli Measurement adlarının birleşimi

    def __init__(self):
        super().__init__()
        self.a2l_db = None
        self._measurement_names: list = []
        self._tiles: list[_GraphTile] = []
        self._start_time: float | None = None
        self._tile_counter = 0

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_controls())

        self.tiles_container = QWidget()
        self.tiles_layout = QVBoxLayout(self.tiles_container)
        self.tiles_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.tiles_container)
        layout.addWidget(scroll, stretch=1)

        self.timer = QTimer(self)
        self.timer.setInterval(POLL_INTERVAL_MS)
        self.timer.timeout.connect(self._on_tick)

        self._add_tile()  # en az bir panelle başla

    def _build_controls(self) -> QGroupBox:
        box = QGroupBox("Canlı grafik — her panelde ayrı sinyaller işaretlenebilir (CCP bağlantısı gerekir)")
        self.add_tile_button = QPushButton("+ Grafik Paneli Ekle")
        self.add_tile_button.clicked.connect(self._add_tile)

        self.start_button = QPushButton("Başlat")
        self.start_button.clicked.connect(self._on_start)
        self.stop_button = QPushButton("Durdur")
        self.stop_button.clicked.connect(self._on_stop)
        self.stop_button.setEnabled(False)
        self.clear_button = QPushButton("Temizle")
        self.clear_button.clicked.connect(self._on_clear)

        self.status_label = QLabel("")

        button_row = QHBoxLayout()
        button_row.addWidget(self.add_tile_button)
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch()
        button_row.addWidget(self.status_label)

        box.setLayout(button_row)
        return box

    def refresh_objects(self):
        self._measurement_names = []
        if self.a2l_db is not None and self.a2l_db.summary is not None:
            self._measurement_names = [m.name for m in self.a2l_db.summary.readable()]
        for tile in self._tiles:
            tile.populate_measurements(self._measurement_names)

    # ---- Panel yönetimi ---------------------------------------------------
    def _add_tile(self):
        self._tile_counter += 1
        tile = _GraphTile(self._tile_counter)
        tile.populate_measurements(self._measurement_names)
        tile.remove_requested.connect(self._remove_tile)
        self._tiles.append(tile)
        self.tiles_layout.insertWidget(self.tiles_layout.count() - 1, tile)

    def _remove_tile(self, tile: _GraphTile):
        if len(self._tiles) <= 1:
            self.status_label.setText("En az bir panel kalmalı.")
            return
        self._tiles.remove(tile)
        self.tiles_layout.removeWidget(tile)
        tile.deleteLater()

    def _all_checked_names(self) -> list:
        names: set = set()
        for tile in self._tiles:
            names |= tile.checked_names()
        return list(names)

    # ---- Başlat / Durdur / Temizle -----------------------------------------
    def _on_start(self):
        if not self._all_checked_names():
            self.status_label.setText("Önce en az bir panelde bir ölçüm işaretleyin.")
            return
        if self._start_time is None:
            self._start_time = time.time()
        self.timer.start()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("Çiziliyor...")

    def _on_stop(self):
        self.timer.stop()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("Durduruldu.")

    def _on_clear(self):
        for tile in self._tiles:
            tile.clear()
        self._start_time = None
        self.status_label.setText("Temizlendi.")

    def _on_tick(self):
        names = self._all_checked_names()
        if not names:
            return
        self.read_requested.emit(names)

    # ---- MainWindow'un çağırdığı erişimci -----------------------------
    def append_sample(self, name: str, value: float):
        if self._start_time is None:
            return
        t = time.time() - self._start_time
        for tile in self._tiles:
            tile.append_sample(name, value, t)
