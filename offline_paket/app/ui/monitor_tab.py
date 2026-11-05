"""CAN izleme tablosu (PCAN-View mantığı): her (yön, CAN ID) çifti için TEK satır.

Performans: tablo bir ``QAbstractTableModel`` + ``QSortFilterProxyModel`` ile çalışır.
Gelen her mesaj yalnızca bellekteki satır nesnesini günceller (Qt çağrısı yok); görünümü
10 Hz'de toplu yenilenir ve DBC çözümleme yalnızca GÖRÜNEN satırlar için, veri
değiştiğinde yapılır. Filtreler (ID / mesaj / yön / hata) mevcut satırlara da uygulanır.
"""
import time

import can
from PySide6.QtCore import (
    QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QTimer,
)
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QSplitter, QTableView, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.can_stats import CanStats

COLUMNS = ["Yön", "CAN ID", "Mesaj", "DLC", "Data", "Periyot ms", "Sinyaller", "Sayaç"]
C_DIR, C_ID, C_NAME, C_DLC, C_DATA, C_PERIOD, C_SIGS, C_COUNT = range(8)
DIRECTION_ALL = "Tümü"
REFRESH_MS = 100
CHANGE_HIGHLIGHT_S = 0.6
STALE_MIN_S = 2.0
MAX_SIGNALS_IN_CELL = 5


class _Row:
    __slots__ = ("direction", "can_id", "extended", "name", "dlc", "data", "prev", "period_ms",
                 "count", "last_t", "last_wall", "changed_at", "is_error", "sig_data", "sig_cache")

    def __init__(self, direction: str, can_id: int, extended: bool):
        self.direction, self.can_id, self.extended = direction, can_id, extended
        self.name = ""
        self.dlc = 0
        self.data = b""
        self.prev = b""
        self.period_ms: float | None = None
        self.count = 0
        self.last_t = 0.0
        self.last_wall = 0.0
        self.changed_at = 0.0
        self.is_error = False
        self.sig_data = None
        self.sig_cache: list = []


class MonitorModel(QAbstractTableModel):
    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self.rows: list[_Row] = []
        self._index: dict = {}
        self.hex_mode = True

    # ---- Qt arayüzü --------------------------------------------------------
    def rowCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):  # noqa: N802
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return COLUMNS[section]
        return None

    def _fmt_id(self, r: _Row) -> str:
        return f"0x{r.can_id:X}" if self.hex_mode else str(r.can_id)

    def _fmt_data(self, r: _Row) -> str:
        if self.hex_mode:
            return r.data.hex(sep=" ").upper()
        return " ".join(str(b) for b in r.data)

    def signals(self, r: _Row) -> list:
        """[(ad, değer, birim)] — veri değişmedikçe önbellekten."""
        if r.sig_data == r.data:
            return r.sig_cache
        out = []
        msg = self._owner.message_of(r.can_id)
        if msg is not None:
            try:
                dec = msg.decode(bytes(r.data))
                units = {s.name: (s.unit or "") for s in msg.signals}
                out = [(k, v, units.get(k, "")) for k, v in dec.items()]
            except Exception:
                out = []
        r.sig_data, r.sig_cache = r.data, out
        return out

    @staticmethod
    def _fmt_val(v) -> str:
        if isinstance(v, float):
            return f"{v:.4g}"
        return str(v)

    def sig_text(self, r: _Row, limit: int | None = MAX_SIGNALS_IN_CELL) -> str:
        sigs = self.signals(r)
        parts = [f"{n}={self._fmt_val(v)}{(' ' + u) if u else ''}" for n, v, u in sigs]
        if limit is not None and len(parts) > limit:
            return ", ".join(parts[:limit]) + f"  … (+{len(parts) - limit})"
        return ", ".join(parts)

    def data(self, index, role=Qt.DisplayRole):
        r = self.rows[index.row()]
        c = index.column()
        if role == Qt.DisplayRole:
            if c == C_DIR:
                return "HATA" if r.is_error else r.direction
            if c == C_ID:
                return self._fmt_id(r)
            if c == C_NAME:
                return r.name
            if c == C_DLC:
                return str(r.dlc)
            if c == C_DATA:
                return self._fmt_data(r)
            if c == C_PERIOD:
                return "—" if r.period_ms is None else f"{r.period_ms:.1f}"
            if c == C_SIGS:
                return self.sig_text(r)
            if c == C_COUNT:
                return str(r.count)
        elif role == Qt.UserRole:                       # sıralama değerleri
            return {C_DIR: r.direction, C_ID: r.can_id, C_NAME: r.name, C_DLC: r.dlc,
                    C_DATA: bytes(r.data), C_PERIOD: r.period_ms or 0.0, C_SIGS: r.name,
                    C_COUNT: r.count}[c]
        elif role == Qt.ToolTipRole:
            if c == C_SIGS:
                return self.sig_text(r, None) or None
            if c == C_DATA:
                return "Ondalık: " + " ".join(str(b) for b in r.data)
            if c == C_ID:
                return f"0x{r.can_id:X} = {r.can_id}" + (" (extended)" if r.extended else " (standard)")
        elif role == Qt.ForegroundRole:
            now = time.monotonic()
            stale_after = max(STALE_MIN_S, (r.period_ms or 0) * 5 / 1000.0)
            if now - r.last_wall > stale_after:
                return QColor("#7C8B98")                # uzun süredir gelmeyen mesaj soluk
            if r.is_error:
                return QColor("#C22A1D")
            if c == C_DIR:
                return QColor("#0E6E8C" if r.direction == "TX" else "#1B8A4C")
        elif role == Qt.BackgroundRole:
            if c == C_DATA and time.monotonic() - r.changed_at < CHANGE_HIGHLIGHT_S:
                return QColor(245, 158, 11, 70)          # değişen veri kısa süre vurgulanır
        elif role == Qt.TextAlignmentRole:
            if c in (C_DLC, C_PERIOD, C_COUNT):
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return int(Qt.AlignLeft | Qt.AlignVCenter)
        return None

    # ---- veri güncelleme -----------------------------------------------------
    def row_for(self, direction: str, can_id: int, extended: bool) -> tuple:
        key = (direction, can_id)
        pos = self._index.get(key)
        if pos is None:
            pos = len(self.rows)
            self.beginInsertRows(QModelIndex(), pos, pos)
            self.rows.append(_Row(direction, can_id, extended))
            self._index[key] = pos
            self.endInsertRows()
        return self.rows[pos], pos

    def notify_changed(self):
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, len(COLUMNS) - 1))

    def reset(self):
        self.beginResetModel()
        self.rows.clear()
        self._index.clear()
        self.endResetModel()

    def refresh_names(self):
        for r in self.rows:
            msg = self._owner.message_of(r.can_id)
            r.name = msg.name if msg is not None else ""
            r.sig_data = None
        self.notify_changed()


class _FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.id_text = ""
        self.name = None
        self.direction = DIRECTION_ALL
        self.errors_only = False
        self.setSortRole(Qt.UserRole)
        self.setDynamicSortFilter(True)

    def set_filters(self, id_text, name, direction, errors_only):
        self.id_text, self.name, self.direction, self.errors_only = id_text, name, direction, errors_only
        self.invalidate()

    def filterAcceptsRow(self, row, parent):  # noqa: N802
        r = self.sourceModel().rows[row]
        if self.id_text and self.id_text not in f"{r.can_id:X}":
            return False
        if self.name is not None and r.name != self.name:
            return False
        if self.direction != DIRECTION_ALL and r.direction != self.direction:
            return False
        if self.errors_only and not r.is_error:
            return False
        return True


class MonitorTab(QWidget):
    def __init__(self):
        super().__init__()
        self.dbc = None  # MainWindow tarafından TransmitTab.dbc ile aynı nesneye bağlanır
        self.stats = CanStats()
        self.frame_hook = None          # callable(msg, direction): günlükleme vb. (duraklatılsa da çağrılır)
        self._paused = False
        self._t0 = None
        self._dirty = False

        self.model = MonitorModel(self)
        self.proxy = _FilterProxy()
        self.proxy.setSourceModel(self.model)

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("ID ara (hex)")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.setMaximumWidth(150)
        self.filter_edit.textChanged.connect(self._apply_filters)

        self.name_filter_combo = QComboBox()
        self.name_filter_combo.addItem(DIRECTION_ALL)
        self.name_filter_combo.setMinimumWidth(130)
        self.name_filter_combo.currentTextChanged.connect(self._apply_filters)

        self.direction_combo = QComboBox()
        self.direction_combo.addItems([DIRECTION_ALL, "RX", "TX"])
        self.direction_combo.currentTextChanged.connect(self._apply_filters)

        self.errors_only_check = QCheckBox("Sadece hatalar")
        self.errors_only_check.toggled.connect(self._apply_filters)
        self.hex_check = QCheckBox("Hex")
        self.hex_check.setChecked(True)
        self.hex_check.toggled.connect(self._on_hex_toggled)

        self.clear_button = QPushButton("Temizle")
        self.clear_button.setProperty("compact", True)
        self.clear_button.clicked.connect(self.clear)
        self.pause_button = QPushButton("Duraklat")
        self.pause_button.setProperty("compact", True)
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._on_pause_toggled)

        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(C_ID, Qt.AscendingOrder)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableView.NoEditTriggers)
        self.table.setSelectionBehavior(QTableView.SelectRows)
        self.table.setSelectionMode(QTableView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setWordWrap(False)
        hdr = self.table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.Interactive)
        hdr.setStretchLastSection(False)
        widths = {C_DIR: 46, C_ID: 70, C_NAME: 118, C_DLC: 38, C_DATA: 164, C_PERIOD: 78, C_SIGS: 360, C_COUNT: 58}
        for col, w in widths.items():
            self.table.setColumnWidth(col, w)
        hdr.setSectionResizeMode(C_SIGS, QHeaderView.Stretch)
        self.table.selectionModel().selectionChanged.connect(lambda *_: self._refresh_detail())

        # ---- seçili mesajın sinyalleri
        self.detail = QTableWidget(0, 4)
        self.detail.setHorizontalHeaderLabels(["Sinyal", "Değer", "Birim", "Ham"])
        self.detail.verticalHeader().setVisible(False)
        self.detail.verticalHeader().setDefaultSectionSize(22)
        self.detail.setEditTriggers(QTableWidget.NoEditTriggers)
        self.detail.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.detail_title = QLabel("Ayrıntı: bir mesaj satırı seçin (DBC yüklüyse sinyaller listelenir)")
        self.detail_title.setObjectName("mutedSmall")
        detail_box = QWidget()
        dl = QVBoxLayout(detail_box)
        dl.setContentsMargins(0, 2, 0, 0)
        dl.setSpacing(2)
        dl.addWidget(self.detail_title)
        dl.addWidget(self.detail, 1)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.table)
        split.addWidget(detail_box)
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        split.setChildrenCollapsible(False)

        self.chip_rx = QLabel("RX 0")
        self.chip_tx = QLabel("TX 0")
        self.chip_rate = QLabel("0.0 msg/s")
        self.chip_load = QLabel("Bus yükü —")
        for c in (self.chip_rx, self.chip_tx, self.chip_rate, self.chip_load):
            c.setObjectName("statChip")

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(self.filter_edit)
        top.addWidget(self.name_filter_combo)
        top.addWidget(self.direction_combo)
        top.addWidget(self.errors_only_check)
        top.addWidget(self.hex_check)
        top.addStretch(1)
        top.addWidget(self.pause_button)
        top.addWidget(self.clear_button)

        chips = QHBoxLayout()
        chips.setSpacing(6)
        for c in (self.chip_rx, self.chip_tx, self.chip_rate, self.chip_load):
            chips.addWidget(c)
        chips.addStretch(1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        layout.addLayout(chips)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._flush)
        self._timer.start()

    # ---- DBC ------------------------------------------------------------------
    def message_of(self, can_id: int):
        if self.dbc is not None and self.dbc.is_loaded:
            return self.dbc.get_message_by_frame_id(can_id)
        return None

    def refresh_dbc_messages(self):
        """DBC yüklendiğinde/değiştiğinde çağrılır: mesaj-adı filtresi + satır adları güncellenir."""
        self.name_filter_combo.blockSignals(True)
        self.name_filter_combo.clear()
        self.name_filter_combo.addItem(DIRECTION_ALL)
        if self.dbc and self.dbc.is_loaded:
            self.name_filter_combo.addItems(self.dbc.message_names())
        self.name_filter_combo.blockSignals(False)
        self.model.refresh_names()
        self._apply_filters()

    # ---- filtreler ------------------------------------------------------------
    def _apply_filters(self, *_):
        name = self.name_filter_combo.currentText()
        self.proxy.set_filters(self.filter_edit.text().strip().upper().replace("0X", ""),
                               None if name == DIRECTION_ALL else name,
                               self.direction_combo.currentText(), self.errors_only_check.isChecked())

    def _on_hex_toggled(self, checked: bool):
        self.model.hex_mode = checked
        self.model.notify_changed()

    def _on_pause_toggled(self, checked: bool):
        self._paused = checked
        self.pause_button.setText("Devam ettir" if checked else "Duraklat")

    def set_bitrate(self, bitrate: int | None):
        self.stats.set_bitrate(bitrate)

    # ---- mesaj işleme -----------------------------------------------------------
    def add_message(self, msg: can.Message, direction: str = "RX"):
        is_error = bool(getattr(msg, "is_error_frame", False))
        if direction == "RX":
            self.stats.record_rx(msg.dlc, msg.is_extended_id, msg.timestamp)
        else:
            self.stats.record_tx()
        if self.frame_hook is not None:
            try:
                self.frame_hook(msg, direction)
            except Exception:
                pass
        if self._paused:
            return

        row, _pos = self.model.row_for(direction, msg.arbitration_id, bool(msg.is_extended_id))
        data = bytes(msg.data)
        now = time.monotonic()
        if row.count == 0:
            msg_def = self.message_of(msg.arbitration_id)
            row.name = msg_def.name if msg_def is not None else ""
        else:
            dt = (msg.timestamp - row.last_t) * 1000.0
            if dt > 0:
                row.period_ms = dt if row.period_ms is None else 0.7 * row.period_ms + 0.3 * dt
        if data != row.data:
            if row.count:
                row.changed_at = now
            row.prev = row.data
            row.data = data
        row.dlc = msg.dlc
        row.count += 1
        row.last_t = msg.timestamp
        row.last_wall = now
        row.is_error = row.is_error or is_error
        self._dirty = True

    def _flush(self):
        if self._dirty or self.model.rows:
            self.model.notify_changed()
            self._dirty = False
        self._update_chips()
        self._refresh_detail()

    def _update_chips(self):
        s = self.stats
        load = s.bus_load_percent()
        self.chip_rx.setText(f"RX {s.total_rx}")
        self.chip_tx.setText(f"TX {s.total_tx}")
        self.chip_rate.setText(f"{s.rx_rate():.1f} msg/s")
        self.chip_load.setText(f"Bus yükü {load:.1f}%" if load is not None else "Bus yükü —")

    def selected_row(self):
        idx = self.table.currentIndex()
        if not idx.isValid():
            return None
        return self.model.rows[self.proxy.mapToSource(idx).row()]

    def _refresh_detail(self):
        r = self.selected_row()
        if r is None:
            return
        msg = self.message_of(r.can_id)
        if msg is None:
            self.detail_title.setText(f"0x{r.can_id:X}: DBC'de tanımlı değil (ham veri: {self.model._fmt_data(r)})")
            self.detail.setRowCount(0)
            return
        sigs = self.model.signals(r)
        try:
            raw = msg.decode(bytes(r.data), decode_choices=False, scaling=False)
        except Exception:
            raw = {}
        self.detail_title.setText(f"{msg.name}  (0x{r.can_id:X}, DLC {r.dlc})  —  {len(sigs)} sinyal")
        if self.detail.rowCount() != len(sigs):
            self.detail.setRowCount(len(sigs))
        for i, (name, val, unit) in enumerate(sigs):
            for col, text in enumerate((name, self.model._fmt_val(val), unit, str(raw.get(name, "")))):
                item = self.detail.item(i, col)
                if item is None:
                    item = QTableWidgetItem()
                    self.detail.setItem(i, col, item)
                if item.text() != text:
                    item.setText(text)

    def clear(self):
        self.model.reset()
        self._t0 = None
        self.stats.reset()
        self.detail.setRowCount(0)
        self.detail_title.setText("Ayrıntı: bir mesaj satırı seçin (DBC yüklüyse sinyaller listelenir)")
        self._update_chips()
