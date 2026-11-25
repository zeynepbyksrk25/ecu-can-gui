"""Harita Editörü (SRS Faz 3): A2L'deki CURVE (1D) / MAP (2D) / ARRAY
(VAL_BLK, eksensiz dizi) kalibrasyon nesnelerini tablo olarak düzenleme.
Her nesne ayrı bir "doküman" sekmesinde açılır (aynı anda istenen sayıda);
her dokümanın kendi tablosu, undo/redo geçmişi ve "ECU'dan son okunan"
(baz alınan) değerleri vardır. Çoklu hücre seçimi, toplu işlemler
(Ata/Ekle/Çarp/% Değiştir), Excel uyumlu kopyala/yapıştır, değişen hücre
vurgusu ve ısı haritası (heatmap) görünümü içerir.

Diğer sekmeler gibi bu widget de gerçek CCP okuma/yazma işlemini
YAPMAZ — sinyal olarak isteği dışarı bildirir, MainWindow CCPClient +
app/ccp/mapio.py üzerinden işlemi yapıp sonucu set_* metotlarıyla geri
bildirir.
"""

import copy
import math

import pyqtgraph as pg

from app import theme
from app.ui.dash_widgets import make_card
from app.ui.mesh3d import Mesh3DWidget, parula, parula_lut
from app.ccp.mapio import grid_shape as _grid_shape

from PySide6.QtCore import QItemSelectionModel, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QFrame, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSplitter, QTableWidget,
    QTableWidgetItem, QTabWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, QHeaderView,
)

from app.ui.a2l_tree import ROLE_OBJECT, filter_tree, new_tree, payload_item  # noqa: F401 (ROLE_OBJECT: eski içe aktarma yolu)

MODIFIED_BG = QColor("#FFE8A8")   # değişen hücre (ısı haritası kapalıyken)
MODIFIED_FG = QColor("#7A4F00")   # değişen hücrede kalın/turuncu yazı (ısı haritası açıkken)
HEAT_MODIFIED_FG = QColor("#B3001B")  # ısı haritası açıkken değişen hücre yazısı (mor/mavi zeminde okunur)
PLACEHOLDER = "-"                 # ECU'dan okunmamış hücre yer tutucusu


def _parse_number(text) -> float | None:
    """Metni sayıya çevirir (ondalık virgül de kabul); geçersizse None."""
    if text is None:
        return None
    s = str(text).strip().replace(",", ".")
    if not s:
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def _fmt(v: float | None) -> str:
    return PLACEHOLDER if v is None else f"{v:.10g}"


class MapDocument(QWidget):
    """Tek bir kalibrasyon nesnesinin (CURVE/MAP/ARRAY) editör sayfası."""

    read_requested = Signal()
    write_requested = Signal()
    changed = Signal()   # içerik/geçmiş değişti (sekme başlığı tazelemek için)

    def __init__(self, characteristic, parent=None):
        super().__init__(parent)
        self.characteristic = characteristic
        self._original_grid: list | None = None   # ECU'dan son okunan (baz alınan) değerler
        self._history: list = []                   # undo/redo yığını (None = geçersiz hücre)
        self._history_index = -1
        self._updating_table = False
        self._updating_details = False
        self._online = False

        self._build_ui()
        rows, cols = self._shape()
        self._build_empty_table(rows, cols)
        self._history = [self._values()]
        self._history_index = 0
        self._update_buttons()
        self._refresh_plot()

    # ---- Arayüz -----------------------------------------------------------
    def _shape(self) -> tuple:
        from app.ccp.mapio import grid_shape
        return grid_shape(self.characteristic)

    def _build_ui(self):
        c = self.characteristic
        rows, cols = self._shape()
        addr = f"0x{c.address:X}" if c.address else "-"
        self.info_label = QLabel(
            f"<b>{c.name}</b> &nbsp;|&nbsp; {c.kind} ({c.datatype}) &nbsp;|&nbsp; "
            f"Adres: {addr} &nbsp;|&nbsp; Boyut: {rows} satır × {cols} sütun"
        )
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.online_label = QLabel()
        self.online_label.setAlignment(Qt.AlignCenter)
        self.online_label.setMinimumWidth(84)
        self._style_online_label()

        self.caveat_label = QLabel(
            "⚠ DİKKAT: Bu nesnenin ekseni FIX_AXIS değil (STD_AXIS/COM_AXIS/vb.). "
            "Fonksiyon değerlerinin bellek adresi bu sürümde DOĞRULANMADI: ECU'dan okunan değerler YANLIŞ "
            "ADRESTEN gelebilir, bunlara güvenmeyin. Yazma kapalıdır. Kullanmadan önce PCAN-View trace'iyle kontrol edin."
        )
        self.caveat_label.setWordWrap(True)
        self.caveat_label.setStyleSheet(
            f"color: {theme.DANGER}; font-weight: 700; background: {theme.DANGER_BG}; "
            f"border: 1px solid {theme.DANGER}; border-radius: 6px; padding: 6px 10px;")
        self.caveat_label.setVisible(
            c.kind in ("CURVE", "MAP") and any(a.attribute != "FIX_AXIS" for a in c.axes)
        )

        self.read_button = QPushButton("ECU'dan Oku")
        self.read_button.clicked.connect(self.read_requested.emit)

        self.write_button = QPushButton("ECU'ya Yaz (RAM)")
        self.write_button.setProperty("primary", True)
        self.write_button.setToolTip("Tablodaki TÜM hücreler geçerli sayı olduğunda etkinleşir.")
        self.write_button.clicked.connect(self._on_write_clicked)

        self.undo_button = QPushButton("Geri Al")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("Yinele")
        self.redo_button.clicked.connect(self.redo)

        self.heatmap_checkbox = QCheckBox("Isı haritası")
        self.heatmap_checkbox.setChecked(True)          # MATLAB Lookup Table Editor gibi varsayılan açık
        self.heatmap_checkbox.toggled.connect(self._refresh_cell_colors)
        self.mesh_checkbox = QCheckBox("Mesh (3B)")
        self.mesh_checkbox.setChecked(True)
        self.contour_checkbox = QCheckBox("Contour")
        self.contour_checkbox.setChecked(True)

        self.hide_plot_button = QPushButton("GRAFİKLERİ GİZLE")
        self.hide_plot_button.setCheckable(True)
        self.hide_plot_button.setToolTip("Sağdaki Mesh / Contour grafiklerini gizle / göster")
        self.hide_plot_button.toggled.connect(self._on_hide_plot)

        toolbar = QHBoxLayout()
        for w in (self.read_button, self.write_button, self.undo_button,
                  self.redo_button, self.heatmap_checkbox, self.mesh_checkbox,
                  self.contour_checkbox, self.hide_plot_button):
            toolbar.addWidget(w)
        toolbar.addStretch()

        # Toplu işlem çubuğu: seçili TÜM hücrelere uygulanır
        self.value_edit = QLineEdit()
        self.value_edit.setPlaceholderText("Değer / yüzde")
        self.value_edit.setMinimumWidth(110)
        self.value_edit.setMaximumWidth(180)
        self.value_edit.returnPressed.connect(lambda: self.apply_to_selection("set"))
        self.assign_button = QPushButton("Ata (=)")
        self.add_button = QPushButton("Ekle (+)")
        self.mul_button = QPushButton("Çarp (×)")
        self.pct_button = QPushButton("% Değiştir")
        self.assign_button.clicked.connect(lambda: self.apply_to_selection("set"))
        self.add_button.clicked.connect(lambda: self.apply_to_selection("add"))
        self.mul_button.clicked.connect(lambda: self.apply_to_selection("mul"))
        self.pct_button.clicked.connect(lambda: self.apply_to_selection("pct"))
        self.pct_button.setToolTip("Seçili hücreleri yüzde olarak değiştirir (ör. 10 → %10 artır, -5 → %5 azalt).")

        bulk = QHBoxLayout()
        bulk.addWidget(QLabel("Seçili hücrelere:"))
        bulk.addWidget(self.value_edit)
        for b in (self.assign_button, self.add_button, self.mul_button, self.pct_button):
            bulk.addWidget(b)
        bulk.addStretch()

        # --- Sağ taraf: Plot - Mesh (3B) ve Plot - Contour (MATLAB Lookup Table Editor düzeni) ---
        self.mesh = Mesh3DWidget()
        self.mesh.set_theme(theme.paint("@@SURFACE@@"), theme.HEAD)
        self.mesh.cellPicked.connect(self._on_mesh_picked)
        self.mesh.cellDragged.connect(self._on_mesh_dragged)
        self.mesh.dragFinished.connect(self._push_history)
        self.mesh.setToolTip("Sürükle: döndür • Düğüm üstünden yukarı/aşağı sürükle: Z değerini değiştir\n"
                             "Tekerlek: yakınlaştır • Çift tık: görünümü sıfırla")

        self.plot = pg.PlotWidget(background=theme.paint("@@SURFACE_SUBTLE@@"))
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.setMinimumHeight(120)
        self.plot.scene().sigMouseClicked.connect(self._on_contour_clicked)

        self.mesh_panel = self._plot_panel("Plot - Mesh", self.mesh)
        self.contour_panel = self._plot_panel("Plot - Contour", self.plot)
        self.mesh_checkbox.toggled.connect(self.mesh_panel.setVisible)
        self.contour_checkbox.toggled.connect(self.contour_panel.setVisible)
        self.plot_splitter = QSplitter(Qt.Vertical)
        self.plot_splitter.addWidget(self.mesh_panel)
        self.plot_splitter.addWidget(self.contour_panel)
        self.plot_splitter.setChildrenCollapsible(False)
        self.plot_splitter.setStretchFactor(0, 3)
        self.plot_splitter.setStretchFactor(1, 2)

        # --- Sol taraf: Spreadsheet (X üstte, Y solda, Z hücrelerde) ---
        self.table = QTableWidget()
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Eksen değerleri (başlıklar) Lookup penceresindeki gibi gri zeminde, kalın
        hdr_css = theme.paint("QHeaderView::section { background:@@LINE_SOFT@@; color:@@HEAD@@; font-weight:bold; padding:3px 8px; border:1px solid @@BORDER@@; }")
        self.table.horizontalHeader().setStyleSheet(hdr_css)
        self.table.verticalHeader().setStyleSheet(hdr_css)
        self.table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self.table.itemChanged.connect(self._on_item_changed)
        self.table.itemSelectionChanged.connect(self._on_selection_changed)
        sc_copy = QShortcut(QKeySequence.Copy, self.table)
        sc_copy.setContext(Qt.WidgetShortcut)
        sc_copy.activated.connect(self.copy_selection)
        sc_paste = QShortcut(QKeySequence.Paste, self.table)
        sc_paste.setContext(Qt.WidgetShortcut)
        sc_paste.activated.connect(self.paste_from_clipboard)

        self.axis_label = QLabel(self._axis_summary())
        self.axis_label.setWordWrap(True)
        self.axis_label.setStyleSheet(f"color:{theme.INK_2}; font-size:11px;")
        sheet = self._plot_panel("Spreadsheet", self.table, extra=self.axis_label)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(sheet)
        self.main_splitter.addWidget(self.plot_splitter)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setStretchFactor(0, 3)
        self.main_splitter.setStretchFactor(1, 4)
        self.main_splitter.setSizes([480, 720])
        self.plot_splitter.setSizes([320, 220])

        # --- Veri kaynağı tablosu (MATLAB "Data Source") ---
        self.source_table = QTableWidget()
        self.source_table.setColumnCount(3)
        self.source_table.setHorizontalHeaderLabels(["Kaynak Türü", "Kaynak", "Ad"])
        self.source_table.horizontalHeader().setStretchLastSection(True)
        self.source_table.verticalHeader().setVisible(False)
        self.source_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.source_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.source_table.setMaximumHeight(118)
        self._fill_source_table()
        source_panel = self._plot_panel(f"Veri Kaynağı - {c.name}", self.source_table)

        # --- Ayrıntılar: hücre başına Adres / Hex / Değer / Ad / Tip / Birim ---
        self.details_button = QPushButton("Ayrıntıları göster >>")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._on_toggle_details)
        self.details_table = QTableWidget()
        self.details_table.setColumnCount(6)
        self.details_table.setHorizontalHeaderLabels(["Adres", "Hex", "Değer", "İsim", "Tip", "Birim"])
        self.details_table.horizontalHeader().setStretchLastSection(True)
        self.details_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.details_table.verticalHeader().setVisible(False)
        self.details_table.setMinimumHeight(140)
        self.details_table.setVisible(False)
        self.details_table.itemChanged.connect(self._on_details_item_changed)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        head = QHBoxLayout()
        head.addWidget(self.info_label, stretch=1)
        head.addWidget(self.online_label)

        layout = QVBoxLayout(self)
        layout.addLayout(head)
        layout.addWidget(self.caveat_label)
        layout.addLayout(toolbar)
        layout.addLayout(bulk)
        layout.addWidget(self.main_splitter, stretch=1)
        layout.addWidget(source_panel)
        details_row = QHBoxLayout()
        details_row.addWidget(self.details_button)
        details_row.addStretch()
        layout.addLayout(details_row)
        layout.addWidget(self.details_table, stretch=1)
        layout.addWidget(self.status_label)

    @staticmethod
    def _plot_panel(title: str, body: QWidget, extra: QWidget | None = None) -> QFrame:
        """MATLAB penceresindeki gibi başlık çubuklu çerçeve."""
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        lay = QVBoxLayout(frame)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QLabel(title)
        head.setStyleSheet(theme.paint(
            "background:@@LINE_SOFT@@; color:@@HEAD@@; font-weight:600; padding:3px 8px; "
            "border-bottom:1px solid @@BORDER@@;"))
        lay.addWidget(head)
        if extra is not None:
            lay.addWidget(extra)
        lay.addWidget(body, 1)
        return frame

    def _axis_summary(self) -> str:
        c = self.characteristic
        ax = list(getattr(c, "axes", None) or [])
        unit = lambda a: f" [{a.unit}]" if a is not None and a.unit else ""
        zu = f" [{c.unit}]" if c.unit else ""
        if c.kind == "MAP":
            return (f"X (sütun){unit(ax[0] if ax else None)} →   |   Y (satır){unit(ax[1] if len(ax) > 1 else None)} ↓   |   "
                    f"Z (değer){zu}")
        if c.kind == "CURVE":
            return f"X (nokta){unit(ax[0] if ax else None)} →   |   Z (değer){zu}"
        return f"X (indeks) →   |   Y (satır indeksi) ↓   |   Z (değer){zu}"

    def _axis_names(self) -> tuple:
        c = self.characteristic
        ax = list(getattr(c, "axes", None) or [])

        def nm(letter, a):
            return f"{letter} ({a.unit})" if a is not None and a.unit else letter
        zl = f"Z ({c.unit})" if c.unit else "Z"
        if c.kind == "MAP":
            return nm("X", ax[0] if ax else None), nm("Y", ax[1] if len(ax) > 1 else None), zl
        if c.kind == "CURVE":
            return nm("X", ax[0] if ax else None), "Y", zl
        return "X", "Y", zl

    def _fill_source_table(self):
        c = self.characteristic
        addr = f"0x{c.address:X}" if c.address else "-"
        rows = [("A2L", f"{c.kind} @ {addr}", f"{c.name}  (Z)")]
        for letter, a in zip("XY", getattr(c, "axes", None) or []):
            rows.append((f"A2L eksen {letter}", f"{a.attribute} • {a.count} nokta", a.unit or "-"))
        self.source_table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, text in enumerate(row):
                self.source_table.setItem(i, j, QTableWidgetItem(text))
        self.source_table.resizeColumnsToContents()
        self.source_table.horizontalHeader().setStretchLastSection(True)

    def _axis_labels(self, axis_info, count: int, fallback_prefix: str) -> list:
        if axis_info is not None and axis_info.values:
            return [f"{v:g}" for v in axis_info.values]
        return [f"{fallback_prefix}{i}" for i in range(count)]

    def _build_empty_table(self, rows: int, cols: int):
        self._updating_table = True
        self.table.clear()
        self.table.setRowCount(rows)
        self.table.setColumnCount(cols)

        c = self.characteristic
        if c.kind == "ARRAY":
            self.table.setHorizontalHeaderLabels([f"[{i}]" for i in range(cols)])
            self.table.setVerticalHeaderLabels(
                ["Değer"] if rows == 1 else [f"[{r}]" for r in range(rows)])
        elif c.kind == "CURVE":
            self.table.setHorizontalHeaderLabels(
                self._axis_labels(c.axes[0] if c.axes else None, cols, "P"))
            self.table.setVerticalHeaderLabels(["Değer"])
        elif c.kind == "MAP":
            self.table.setHorizontalHeaderLabels(
                self._axis_labels(c.axes[0] if len(c.axes) > 0 else None, cols, "X"))
            self.table.setVerticalHeaderLabels(
                self._axis_labels(c.axes[1] if len(c.axes) > 1 else None, rows, "Y"))

        for r in range(rows):
            for col in range(cols):
                item = QTableWidgetItem(PLACEHOLDER)
                item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(r, col, item)
        self._updating_table = False

    # ---- ONLINE/OFFLINE, grafik, ayrıntılar ----------------------------------
    def _style_online_label(self):
        if self._online:
            self.online_label.setText("ONLINE")
            self.online_label.setStyleSheet(
                f"background:{theme.OK}; color:white; font-weight:bold; border-radius:4px; padding:3px 8px;")
        else:
            self.online_label.setText("OFFLINE")
            self.online_label.setStyleSheet(
                f"background:#9AA8B5; color:{theme.HEAD}; font-weight:bold; border-radius:4px; padding:3px 8px;")

    def set_online(self, online: bool):
        self._online = bool(online)
        self._style_online_label()

    def _on_hide_plot(self, hidden: bool):
        self.plot_splitter.setVisible(not hidden)
        self.hide_plot_button.setText("GRAFİKLERİ GÖSTER" if hidden else "GRAFİKLERİ GİZLE")
        if not hidden:
            self._refresh_plot()

    def _axis_x_values(self, cols: int) -> list:
        c = self.characteristic
        ax = c.axes[0] if getattr(c, "axes", None) else None
        if c.kind != "ARRAY" and ax is not None and ax.values and len(ax.values) == cols:
            return [float(v) for v in ax.values]
        return [float(i) for i in range(cols)]

    def _axis_y_values(self, rows: int) -> list:
        c = self.characteristic
        ax = c.axes[1] if len(getattr(c, "axes", None) or []) > 1 else None
        if c.kind == "MAP" and ax is not None and ax.values and len(ax.values) == rows:
            return [float(v) for v in ax.values]
        return [float(i) for i in range(rows)]

    def _is_2d(self, vals) -> bool:
        return len(vals) >= 2 and len(vals[0]) >= 2

    def _refresh_plot(self, vals=None):
        if self.hide_plot_button.isChecked():
            return
        vals = vals if vals is not None else self._values()
        sel = self._selected_cells()
        if vals and vals[0]:
            xs, ys = self._axis_x_values(len(vals[0])), self._axis_y_values(len(vals))
        else:
            xs, ys = [0.0], [0.0]
        # --- Plot - Mesh (3B) ---
        self.mesh.set_data(xs, ys, vals if vals else [[None]], sel, self._axis_names(), self.is_cell_editable())
        # --- Plot - Contour ---
        self.plot.clear()
        if not vals or not vals[0]:
            return
        if self._is_2d(vals):
            self._plot_contour(vals, xs, ys, sel)
        else:
            self._plot_lines(vals, xs, sel)

    def _plot_lines(self, vals, xs, sel):
        """CURVE / 1xN dizi: değer - eksen çizgisi."""
        pi = self.plot.getPlotItem()
        pi.getAxis("bottom").setTicks(None)
        pi.getAxis("left").setTicks(None)
        names = self._axis_names()
        pi.setLabel("bottom", names[0])
        pi.setLabel("left", names[2])
        palette = [theme.ACCENT, theme.DANGER, theme.OK, theme.WARN_INK, theme.PURPLE, "#0E8C7C", theme.MUTED]
        for r, row in enumerate(vals):
            pts = [(x, v) for x, v in zip(xs, row) if v is not None]
            if not pts:
                continue
            color = palette[r % len(palette)]
            self.plot.plot([p[0] for p in pts], [p[1] for p in pts],
                           pen=pg.mkPen(color, width=2), symbol="o", symbolSize=7,
                           symbolBrush=None, symbolPen=pg.mkPen(color, width=1.5))
        pts = [(xs[cc], vals[rr][cc]) for rr, cc in sel
               if rr < len(vals) and cc < len(vals[rr]) and vals[rr][cc] is not None and cc < len(xs)]
        if pts:
            self.plot.plot([p[0] for p in pts], [p[1] for p in pts], pen=None, symbol="o",
                           symbolSize=11, symbolBrush=pg.mkBrush("#ff0000"), symbolPen=pg.mkPen("#ff0000"))

    def _plot_contour(self, vals, xs, ys, sel):
        """MAP / 2B dizi: eş-değer (izoçizgi) haritası; eksenler indeks uzayında, etiketler gerçek eksen değeri."""
        import numpy as np
        flat = [v for row in vals for v in row if v is not None]
        if not flat:
            return
        mean = sum(flat) / len(flat)
        arr = np.array([[mean if v is None else v for v in row] for row in vals], dtype=float).T   # [x, y]
        lo, hi = float(arr.min()), float(arr.max())
        rows, cols = len(vals), len(vals[0])
        pi = self.plot.getPlotItem()
        names = self._axis_names()
        pi.setLabel("bottom", names[0])
        pi.setLabel("left", names[1])

        def ticks(vs):
            step = max(1, math.ceil(len(vs) / 8))
            return [[(i, f"{vs[i]:g}") for i in range(0, len(vs), step)]]
        pi.getAxis("bottom").setTicks(ticks(xs))
        pi.getAxis("left").setTicks(ticks(ys))

        img = pg.ImageItem(axisOrder="col-major")
        img.setImage(arr, levels=(lo, hi if hi > lo else lo + 1.0))
        img.setLookupTable(np.array(parula_lut(), dtype=np.ubyte))
        img.setRect(pg.QtCore.QRectF(-0.5, -0.5, cols, rows))
        img.setOpacity(0.35)
        self.plot.addItem(img)
        if hi - lo > 1e-12:
            n = 9
            for k in range(1, n + 1):
                level = lo + (hi - lo) * k / (n + 1)
                col = parula(k / (n + 1))
                iso = pg.IsocurveItem(data=arr, level=level, pen=pg.mkPen(col.darker(120), width=1.6))
                self.plot.addItem(iso)
        pts = [(cc, rr) for rr, cc in sel if rr < rows and cc < cols and vals[rr][cc] is not None]
        if pts:
            self.plot.plot([p[0] for p in pts], [p[1] for p in pts], pen=None, symbol="o",
                           symbolSize=9, symbolBrush=pg.mkBrush("#ff0000"), symbolPen=pg.mkPen("#7a0000"))
        self.plot.setXRange(-0.5, cols - 0.5, padding=0.02)
        self.plot.setYRange(-0.5, rows - 0.5, padding=0.02)

    # ---- 3B / contour üzerinden seçim ve düzenleme ---------------------------
    def _select_cell(self, r: int, c: int, additive: bool = False):
        if r >= self.table.rowCount() or c >= self.table.columnCount():
            return
        item = self.table.item(r, c)
        if item is None:
            return
        if additive:
            item.setSelected(not item.isSelected())
            self.table.setCurrentItem(item, QItemSelectionModel.NoUpdate)
        else:
            self.table.clearSelection()
            self.table.setCurrentCell(r, c)
            item.setSelected(True)
        self.table.scrollToItem(item)

    def _on_mesh_picked(self, r: int, c: int, additive: bool):
        self._select_cell(r, c, additive)

    def _on_mesh_dragged(self, r: int, c: int, value: float):
        """3B yüzeyde düğüm sürükleme: tablo hücresi canlı güncellenir; geri-al adımı bırakınca atılır."""
        item = self.table.item(r, c)
        if item is None or not self.is_cell_editable():
            return
        self._updating_table = True
        item.setText(_fmt(value))
        self._updating_table = False
        self._refresh_cell_colors()

    def _on_contour_clicked(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        vals = self._values()
        if not self._is_2d(vals):
            return
        vb = self.plot.getPlotItem().vb
        if not vb.sceneBoundingRect().contains(ev.scenePos()):
            return
        p = vb.mapSceneToView(ev.scenePos())
        r, c = int(round(p.y())), int(round(p.x()))
        if 0 <= r < len(vals) and 0 <= c < len(vals[0]):
            self._select_cell(r, c, bool(ev.modifiers() & Qt.ControlModifier))

    def _cell_name(self, r: int, c: int, rows: int, cols: int) -> str:
        n = self.characteristic.name
        if rows == 1:
            return f"{n}[{c}]"
        return f"{n}[{r}][{c}]"

    def _build_details_rows(self):
        rows, cols = self._shape()
        self._updating_details = True
        self.details_table.setRowCount(rows * cols)
        for r in range(rows):
            for c in range(cols):
                i = r * cols + c
                for col, text in enumerate(("", "", PLACEHOLDER, self._cell_name(r, c, rows, cols),
                                            str(self.characteristic.datatype or ""),
                                            str(self.characteristic.unit or ""))):
                    it = QTableWidgetItem(text)
                    if col != 2:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    self.details_table.setItem(i, col, it)
        self._updating_details = False

    def _on_toggle_details(self, shown: bool):
        self.details_table.setVisible(shown)
        self.details_button.setText("<< Ayrıntıları gizle" if shown else "Ayrıntıları göster >>")
        if shown:
            self._refresh_details()

    def _refresh_details(self, vals=None):
        if not self.details_table.isVisible() and not self.details_button.isChecked():
            return
        from app.ccp import codec as ccp_codec
        c = self.characteristic
        rows, cols = self._shape()
        if self.details_table.rowCount() != rows * cols:
            self._build_details_rows()
        vals = vals if vals is not None else self._values()
        try:
            size = ccp_codec.datatype_size(c.datatype)
        except Exception:
            size = 0
        self._updating_details = True
        for r in range(rows):
            for col in range(cols):
                i = r * cols + col
                v = vals[r][col] if r < len(vals) and col < len(vals[r]) else None
                addr = (c.address or 0) + i * size
                hex_text = ""
                if v is not None and size:
                    try:
                        raw = ccp_codec.physical_to_raw(c.compu_method, v)
                        hex_text = ccp_codec.encode_value(c.datatype, raw, c.byte_order).hex().upper()
                    except Exception:
                        hex_text = "?"
                self.details_table.item(i, 0).setText(f"{addr:08X}")
                self.details_table.item(i, 1).setText(hex_text)
                self.details_table.item(i, 2).setText(_fmt(v))
        self._updating_details = False

    def _on_details_item_changed(self, item):
        if self._updating_details or item.column() != 2:
            return
        rows, cols = self._shape()
        i = item.row()
        r, c = divmod(i, cols)
        main = self.table.item(r, c)
        if main is None or not self.is_cell_editable():
            return
        if _parse_number(item.text()) is None:
            self._refresh_details()   # geçersiz giriş: eski değere dön
            return
        main.setText(_fmt(_parse_number(item.text())))   # itemChanged -> undo adımı + yenileme

    def is_cell_editable(self) -> bool:
        return True

    # ---- Değer erişimi ----------------------------------------------------
    def _values(self) -> list:
        """Tablodaki değerler; geçersiz/yer tutucu hücre None."""
        out = []
        for r in range(self.table.rowCount()):
            row = []
            for c in range(self.table.columnCount()):
                item = self.table.item(r, c)
                row.append(_parse_number(item.text()) if item else None)
            out.append(row)
        return out

    def current_grid(self) -> list:
        """Tablodaki değerler (geçersiz hücre 0.0 döner; yazmadan önce is_writable() kontrol edilir)."""
        return [[0.0 if v is None else v for v in row] for row in self._values()]

    def is_writable(self) -> bool:
        return all(v is not None for row in self._values() for v in row)

    def is_modified(self) -> bool:
        if self._original_grid is None:
            return True
        cur = self._values()
        if len(cur) != len(self._original_grid):
            return True
        for r, row in enumerate(cur):
            if len(row) != len(self._original_grid[r]):
                return True
            for c, v in enumerate(row):
                if v is None or abs(v - self._original_grid[r][c]) > 1e-9:
                    return True
        return False

    # ---- MainWindow'un çağırdığı erişimciler -------------------------------
    def set_grid_from_ecu(self, grid: list):
        self._original_grid = copy.deepcopy(grid)
        self._fill_table(grid)
        self._history = [self._values()]
        self._history_index = 0
        self._update_buttons()
        self._set_status("ECU'dan okundu.", ok=True)
        self.changed.emit()

    def set_error(self, message: str):
        self._set_status(message, ok=False)

    def set_write_result(self, ok: bool, message: str):
        self._set_status(message, ok=ok)
        if ok:
            # Yazma sonrası "ECU'daki" değer artık tablodaki değer -> yeni baz
            self._original_grid = copy.deepcopy(self.current_grid())
            self._refresh_cell_colors()
            self.changed.emit()

    def load_grid_as_edit(self, grid: list):
        """Değerleri tabloya DÜZENLEME olarak getirir (ECU'ya yazılmaz; geri alınabilir tek undo adımı)."""
        self._fill_table(grid)
        self._push_history()

    def _set_status(self, message: str, ok: bool = True, warn: bool = False):
        self.status_label.setText(message)
        color = theme.WARN_INK if warn else (theme.OK if ok else theme.DANGER)
        self.status_label.setStyleSheet(f"color: {color};")

    def _on_write_clicked(self):
        # Onay diyaloğu YOK (kullanıcı isteği): doğrudan sinyal.
        if self.is_writable():
            self.write_requested.emit()

    # ---- Tablo doldurma / renklendirme -------------------------------------
    def _fill_table(self, grid: list):
        self._updating_table = True
        for r, row_vals in enumerate(grid):
            for c, val in enumerate(row_vals):
                item = self.table.item(r, c)
                if item is None:
                    if r >= self.table.rowCount() or c >= self.table.columnCount():
                        continue
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignCenter)
                    self.table.setItem(r, c, item)
                item.setText(_fmt(val))
        self._updating_table = False
        self._refresh_cell_colors()

    def _update_buttons(self):
        self.undo_button.setEnabled(self._history_index > 0)
        self.redo_button.setEnabled(self._history_index < len(self._history) - 1)
        self.write_button.setEnabled(self.is_writable())
        has_sel = bool(self.table.selectedIndexes())
        for b in (self.assign_button, self.add_button, self.mul_button, self.pct_button):
            b.setEnabled(has_sel)

    def _on_selection_changed(self):
        self._refresh_plot()
        has_sel = bool(self.table.selectedIndexes())
        for b in (self.assign_button, self.add_button, self.mul_button, self.pct_button):
            b.setEnabled(has_sel)

    def _push_history(self):
        """Mevcut tablo durumunu TEK undo adımı olarak geçmişe ekler."""
        snap = self._values()
        if self._history and self._history_index >= 0 and snap == self._history[self._history_index]:
            self._refresh_cell_colors()
            self._update_buttons()
            return
        # Redo geçmişini kes, yeni durumu ekle (klasik undo/redo yığın davranışı)
        self._history = self._history[: self._history_index + 1]
        self._history.append(snap)
        self._history_index = len(self._history) - 1
        self._refresh_cell_colors()
        self._update_buttons()
        self.changed.emit()

    def _on_item_changed(self, _item: QTableWidgetItem):
        if self._updating_table:
            return
        self._push_history()

    def _refresh_cell_colors(self):
        vals = self._values()
        heatmap_on = self.heatmap_checkbox.isChecked()

        flat = [v for row in vals for v in row if v is not None]
        vmin, vmax = (min(flat), max(flat)) if flat else (0.0, 0.0)
        span = (vmax - vmin) or 1.0

        # setBackground/setForeground/setFont de QTableWidgetItem.itemChanged
        # sinyalini tetikler (sadece metin değil) — bunlar gerçek bir
        # kullanıcı düzenlemesi DEĞİL, bu yüzden undo/redo geçmişine
        # eklenmesinler diye _updating_table bayrağıyla koruyoruz.
        self._updating_table = True
        for r, row_vals in enumerate(vals):
            for c, val in enumerate(row_vals):
                item = self.table.item(r, c)
                if item is None:
                    continue
                modified = (
                    val is not None
                    and self._original_grid is not None
                    and r < len(self._original_grid) and c < len(self._original_grid[r])
                    and abs(self._original_grid[r][c] - val) > 1e-9
                )
                if val is None:
                    item.setBackground(QColor(theme.paint("@@SURFACE_SUBTLE@@")))
                    item.setForeground(QColor(theme.INK))
                elif heatmap_on:
                    ratio = (val - vmin) / span
                    # MATLAB Lookup Table Editor: mor (düşük) -> açık mavi (yüksek)
                    color = QColor(int(150 - 40 * ratio), int(125 + 60 * ratio), int(222 + 25 * ratio))
                    item.setBackground(color)
                    item.setForeground(HEAT_MODIFIED_FG if modified else QColor(theme.INK))
                else:
                    item.setBackground(MODIFIED_BG if modified else QColor(theme.paint("@@SURFACE_SUBTLE@@")))
                    item.setForeground(MODIFIED_FG if modified else QColor(theme.INK))
                font = item.font()
                font.setBold(modified)
                item.setFont(font)
        self._updating_table = False
        self._refresh_plot(vals)
        self._refresh_details(vals)

    # ---- Toplu işlemler ---------------------------------------------------
    def _selected_cells(self) -> list:
        return sorted({(i.row(), i.column()) for i in self.table.selectedIndexes()})

    def apply_to_selection(self, op: str) -> tuple:
        """Seçili hücrelere op ('set'|'add'|'mul'|'pct') uygular; TEK undo
        adımı. (güncellenen, atlanan) sayısını döner."""
        cells = self._selected_cells()
        if not cells:
            self._set_status("Önce tabloda hücre seçin.", ok=False)
            return 0, 0
        operand = _parse_number(self.value_edit.text())
        if operand is None:
            self._set_status("Geçerli bir sayı girin.", ok=False)
            return 0, 0

        updated = skipped = 0
        self._updating_table = True
        for r, c in cells:
            item = self.table.item(r, c)
            cur = _parse_number(item.text()) if item else None
            if op == "set":
                new = operand
            elif cur is None:
                skipped += 1      # sayı olmayan ("-") hücreye göreli işlem uygulanamaz
                continue
            elif op == "add":
                new = cur + operand
            elif op == "mul":
                new = cur * operand
            else:  # pct
                new = cur * (1.0 + operand / 100.0)
            if not math.isfinite(new):
                skipped += 1
                continue
            item.setText(_fmt(new))
            updated += 1
        self._updating_table = False
        self._push_history()
        self._report_bulk(updated, skipped)
        return updated, skipped

    def _report_bulk(self, updated: int, skipped: int):
        msg = f"{updated} hücre güncellendi."
        if skipped:
            msg += f" {skipped} hücre atlandı (geçersiz sayı)."
        self._set_status(msg, ok=True, warn=bool(skipped))

    # ---- Panoya kopyala / yapıştır ---------------------------------------
    def copy_selection(self):
        cells = self._selected_cells()
        if not cells:
            return
        sel = set(cells)
        r0, r1 = min(r for r, _ in cells), max(r for r, _ in cells)
        c0, c1 = min(c for _, c in cells), max(c for _, c in cells)
        lines = []
        for r in range(r0, r1 + 1):
            parts = []
            for c in range(c0, c1 + 1):
                item = self.table.item(r, c)
                parts.append(item.text() if (r, c) in sel and item else "")
            lines.append("\t".join(parts))
        QApplication.clipboard().setText("\n".join(lines))

    def paste_from_clipboard(self) -> tuple:
        """Panodaki bloğu (sekme/satır ayraçlı) geçerli hücreden başlayarak
        yapıştırır; tablo dışına taşan kısım atılır. TEK undo adımı.
        (güncellenen, atlanan) döner."""
        text = QApplication.clipboard().text()
        if not text or not text.strip():
            return 0, 0
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        while lines and lines[-1] == "":
            lines.pop()
        block = [ln.split("\t") for ln in lines]

        rows, cols = self.table.rowCount(), self.table.columnCount()
        cells = self._selected_cells()
        # Tek değer + çoklu seçim: değer tüm seçili hücrelere
        single = len(block) == 1 and len(block[0]) == 1
        targets = []
        if single and len(cells) > 1:
            targets = [(r, c, block[0][0]) for r, c in cells]
        else:
            if self.table.currentItem() is not None and self.table.currentRow() >= 0:
                r0, c0 = self.table.currentRow(), self.table.currentColumn()
            elif cells:
                r0, c0 = cells[0]
            else:
                r0, c0 = 0, 0
            for i, parts in enumerate(block):
                for j, cell in enumerate(parts):
                    r, c = r0 + i, c0 + j
                    if r < rows and c < cols:
                        targets.append((r, c, cell))

        updated = skipped = 0
        self._updating_table = True
        for r, c, cell in targets:
            v = _parse_number(cell)
            if v is None:
                skipped += 1
                continue
            self.table.item(r, c).setText(_fmt(v))
            updated += 1
        self._updating_table = False
        self._push_history()
        self._report_bulk(updated, skipped)
        return updated, skipped

    # ---- Undo / Redo -----------------------------------------------------
    def undo(self):
        if self._history_index <= 0:
            return
        self._history_index -= 1
        self._fill_table(self._history[self._history_index])
        self._update_buttons()
        self.changed.emit()

    def redo(self):
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        self._fill_table(self._history[self._history_index])
        self._update_buttons()
        self.changed.emit()


class MapEditorTab(QWidget):
    read_requested = Signal()        # geçerli dokümanı ECU'dan oku
    write_requested = Signal()       # geçerli dokümanı ECU'ya (RAM) yaz
    read_all_requested = Signal()    # açık tüm dokümanları ECU'dan oku
    write_all_requested = Signal()   # açık tüm dokümanları ECU'ya (RAM) yaz

    def __init__(self):
        super().__init__()
        self.a2l_db = None

        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_tree_panel())
        splitter.addWidget(self._build_editor_panel())
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter)

    # ---- Nesne tarayıcı ---------------------------------------------------
    def _build_tree_panel(self) -> QWidget:
        box, body, _head = make_card("A2L nesneleri", "sliders")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("İsme göre ara...")
        self.search_edit.textChanged.connect(self._apply_filter)

        self.tree = new_tree(self._on_item_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.search_edit)
        layout.addWidget(self.tree)
        body.addLayout(layout, 1)
        box.setMinimumWidth(180)
        return box

    def _reconcile_open_documents(self):
        """Yeni A2L yüklenince açık tabloları yeni nesnelerle eşleştirir.
        Nesne yoksa ya da adres/veri tipi/boyut değiştiyse sekme KAPATILIR:
        aksi halde 'ECU'ya Yaz' önceki revizyonun adresine yazardı."""
        summary = getattr(self.a2l_db, "summary", None) if self.a2l_db is not None else None
        fresh = {c.name: c for c in summary.characteristics} if summary else {}
        for doc in list(self.documents()):
            old = doc.characteristic
            new = fresh.get(old.name)
            same = (new is not None and new.address == old.address and new.datatype == old.datatype
                    and new.byte_order == old.byte_order and doc._shape() == _grid_shape(new)
                    and getattr(new, "index_mode", None) == getattr(old, "index_mode", None))
            if same:
                doc.characteristic = new
            else:
                self._on_tab_close(self.tabs.indexOf(doc))

    def refresh_objects(self):
        self._reconcile_open_documents()
        self.tree.clear()
        if self.a2l_db is None or self.a2l_db.summary is None:
            return
        roots = {
            "CURVE": QTreeWidgetItem(["Eğriler (1D)"]),
            "MAP": QTreeWidgetItem(["Haritalar (2D)"]),
            "ARRAY": QTreeWidgetItem(["Diziler (VAL_BLK)"]),
        }
        for c in self.a2l_db.summary.characteristics:
            if c.kind not in roots:
                continue
            roots[c.kind].addChild(payload_item(c.name, c))
        for root in roots.values():
            self.tree.addTopLevelItem(root)
        self.tree.expandAll()

    def _apply_filter(self, text: str):
        filter_tree(self.tree, text)

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int):
        obj = item.data(0, ROLE_OBJECT)
        if obj is None:
            return
        self.open_characteristic(obj)

    # ---- Doküman sekmeleri --------------------------------------------------
    def _build_editor_panel(self) -> QWidget:
        panel = QWidget()
        self.read_all_button = QPushButton("Tümünü ECU'dan Oku")
        self.read_all_button.clicked.connect(self.read_all_requested.emit)
        self.write_all_button = QPushButton("Tümünü ECU'ya Yaz (RAM)")
        self.write_all_button.setProperty("primary", True)
        self.write_all_button.clicked.connect(self.write_all_requested.emit)
        self.read_all_button.setEnabled(False)
        self.write_all_button.setEnabled(False)
        self.restore_button = QPushButton("Yedekten Yükle…")
        self.restore_button.setToolTip("Bu tablonun, ECU'ya yazılmadan önce otomatik alınan yedeklerinden birini tabloya "
                                       "yükler (ECU'ya yazılmaz; 'ECU'ya Yaz' ile ayrıca yazarsınız).")
        self.restore_button.clicked.connect(self._on_restore_clicked)
        self.restore_button.setEnabled(False)

        top = QHBoxLayout()
        top.addWidget(self.read_all_button)
        top.addWidget(self.write_all_button)
        top.addWidget(self.restore_button)
        top.addStretch()

        self.empty_label = QLabel("Soldaki listeden bir nesneye tıklayarak tabloyu yeni bir sekmede açın.")
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.setDocumentMode(False)
        self.tabs.tabCloseRequested.connect(self._on_tab_close)
        self.tabs.setVisible(False)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(top)
        layout.addWidget(self.empty_label, stretch=1)
        layout.addWidget(self.tabs, stretch=1)
        return panel

    def _on_restore_clicked(self):
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from app.ccp import mapio, table_backup
        from app.paths import data_path
        doc = self.current_document()
        if doc is None:
            return
        ch = doc.characteristic
        backups = table_backup.list_backups(data_path("tablo_yedekleri"), ch)
        if not backups:
            QMessageBox.information(self.window(), "Yedek yok", f"{ch.name} için kayıtlı bir yedek yok. Yedekler, tablo "
                                                                 "ECU'ya yazılmadan hemen önce otomatik alınır.")
            return
        label, ok = QInputDialog.getItem(self.window(), "Yedekten yükle", f"{ch.name}: yedek seçin (en yenisi üstte)",
                                         [b.label for b in backups], 0, False)
        if not ok:
            return
        chosen = next(b for b in backups if b.label == label)
        try:
            grid = table_backup.load(chosen.path, ch, mapio.grid_shape(ch))
        except ValueError as exc:
            QMessageBox.warning(self.window(), "Yedek yüklenemedi", str(exc))
            return
        doc.load_grid_as_edit(grid)
        # set_write_result KULLANILMAZ: başarıda tabloyu "ECU ile aynı" sayıp değişiklik işaretini silerdi.
        doc._set_status(f"Yedek yüklendi ({label.split('  ')[0]}); ECU'ya HENÜZ yazılmadı. "
                        "Yazmak için 'ECU'ya Yaz'ı kullanın.", ok=True, warn=True)

    def open_characteristic(self, characteristic) -> MapDocument:
        """Nesneyi yeni sekmede açar; zaten açıksa o sekmeye geçer."""
        for doc in self.documents():
            if doc.characteristic.name == characteristic.name:
                self.tabs.setCurrentWidget(doc)
                return doc
        doc = MapDocument(characteristic)
        doc.set_online(getattr(self, "_online", False))
        doc.read_requested.connect(self.read_requested.emit)
        doc.write_requested.connect(self.write_requested.emit)
        doc.changed.connect(lambda d=doc: self._update_tab_title(d))
        idx = self.tabs.addTab(doc, characteristic.name)
        self.tabs.setTabToolTip(idx, f"{characteristic.name} ({characteristic.kind})")
        self.tabs.setCurrentIndex(idx)
        self._refresh_visibility()
        return doc

    def _update_tab_title(self, doc: MapDocument):
        idx = self.tabs.indexOf(doc)
        if idx < 0:
            return
        mark = "● " if (doc._original_grid is not None and doc.is_modified()) else ""
        self.tabs.setTabText(idx, mark + doc.characteristic.name)

    def _on_tab_close(self, index: int):
        doc = self.tabs.widget(index)
        self.tabs.removeTab(index)
        if doc is not None:
            doc.deleteLater()
        self._refresh_visibility()

    def _refresh_visibility(self):
        has_docs = self.tabs.count() > 0
        self.tabs.setVisible(has_docs)
        self.empty_label.setVisible(not has_docs)
        self.read_all_button.setEnabled(has_docs)
        self.write_all_button.setEnabled(has_docs)
        self.restore_button.setEnabled(has_docs)

    def set_online(self, online: bool):
        """CCP bağlantı durumunu tüm açık dokümanlara (ve yenilerine) yansıtır."""
        self._online = bool(online)
        for doc in self.documents():
            doc.set_online(online)

    def documents(self) -> list:
        return [self.tabs.widget(i) for i in range(self.tabs.count())]

    def current_document(self):
        w = self.tabs.currentWidget()
        return w if isinstance(w, MapDocument) else None

    # ---- Geriye uyumluluk (geçerli dokümana yönlendirme) -------------------
    @property
    def table(self):
        d = self.current_document()
        return d.table if d else None

    @property
    def undo_button(self):
        d = self.current_document()
        return d.undo_button if d else None

    @property
    def redo_button(self):
        d = self.current_document()
        return d.redo_button if d else None

    @property
    def write_button(self):
        d = self.current_document()
        return d.write_button if d else None

    def selected_characteristic(self):
        d = self.current_document()
        return d.characteristic if d else None

    def current_grid(self) -> list:
        d = self.current_document()
        return d.current_grid() if d else []

    def set_grid_from_ecu(self, grid: list):
        d = self.current_document()
        if d:
            d.set_grid_from_ecu(grid)

    def set_error(self, message: str):
        d = self.current_document()
        if d:
            d.set_error(message)

    def set_write_result(self, ok: bool, message: str):
        d = self.current_document()
        if d:
            d.set_write_result(ok, message)

    def _undo(self):
        d = self.current_document()
        if d:
            d.undo()

    def _redo(self):
        d = self.current_document()
        if d:
            d.redo()
