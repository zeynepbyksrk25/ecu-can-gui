import can
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.can_stats import CanStats
from app.validators import validate_can_id

COLUMNS = ["Yön", "Zaman (ms)", "CAN ID", "Mesaj İsmi", "DLC", "Data", "Sinyaller", "Hata", "Sayaç"]
DIRECTION_ALL = "Tümü"


class MonitorTab(QWidget):
    """Her CAN ID için TEK satır tutulur; aynı ID'den yeni mesaj geldiğinde
    yeni satır EKLENMEZ, mevcut satır güncellenir (PCAN-View mantığı).
    DBC yüklüyse (TransmitTab ile PAYLAŞILAN aynı DbcDatabase nesnesi
    üzerinden) mesaj ismi ve sinyal değerleri de gösterilir."""

    def __init__(self):
        super().__init__()
        self.dbc = None  # MainWindow tarafından TransmitTab.dbc ile aynı nesneye bağlanır
        self.stats = CanStats()

        self._paused = False
        self._id_filter: int | None = None
        self._name_filter: str | None = None
        self._direction_filter: str = DIRECTION_ALL
        self._errors_only = False
        self._t0 = None
        # Anahtar (id, extended): aynı sayısal standard ve extended ID'ler ayrı satırdır.
        self._row_by_id: dict[tuple, int] = {}
        self._counts: dict[tuple, int] = {}

        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("ID filtrele (hex, örn. 1A0) - boş = tümü")
        self.filter_edit.textChanged.connect(self._on_filter_changed)

        self.name_filter_combo = QComboBox()
        self.name_filter_combo.addItem(DIRECTION_ALL)
        self.name_filter_combo.currentTextChanged.connect(self._on_name_filter_changed)

        self.direction_combo = QComboBox()
        self.direction_combo.addItems([DIRECTION_ALL, "RX", "TX"])
        self.direction_combo.currentTextChanged.connect(self._on_direction_filter_changed)

        self.errors_only_check = QCheckBox("Sadece hatalar")
        self.errors_only_check.toggled.connect(self._on_errors_only_toggled)

        self.clear_button = QPushButton("Temizle")
        self.clear_button.clicked.connect(self.clear)

        self.pause_button = QPushButton("Duraklat")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._on_pause_toggled)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)

        self.stats_label = QLabel("Toplam RX: 0   Toplam TX: 0   RX hızı: 0.0 msg/s   Bus Load: -")

        top = QHBoxLayout()
        top.addWidget(QLabel("ID:"))
        top.addWidget(self.filter_edit)
        top.addWidget(QLabel("Mesaj:"))
        top.addWidget(self.name_filter_combo)
        top.addWidget(QLabel("Yön:"))
        top.addWidget(self.direction_combo)
        top.addWidget(self.errors_only_check)
        top.addStretch()
        top.addWidget(self.pause_button)
        top.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.table)
        layout.addWidget(self.stats_label)

    # ---- Filtreler -----------------------------------------------------
    def _on_filter_changed(self, text: str):
        text = text.strip()
        if not text:
            self._id_filter = None
            return
        try:
            self._id_filter = validate_can_id(text, extended=True)
        except ValueError:
            self._id_filter = None

    def _on_name_filter_changed(self, name: str):
        self._name_filter = None if name == DIRECTION_ALL else name

    def _on_direction_filter_changed(self, direction: str):
        self._direction_filter = direction

    def _on_errors_only_toggled(self, checked: bool):
        self._errors_only = checked

    def _on_pause_toggled(self, checked: bool):
        self._paused = checked
        self.pause_button.setText("Devam ettir" if checked else "Duraklat")

    def refresh_dbc_messages(self):
        """DBC yüklendiğinde/değiştiğinde TransmitTab tarafından çağrılır;
        mesaj ismi filtresi kombosunu günceller."""
        self.name_filter_combo.blockSignals(True)
        self.name_filter_combo.clear()
        self.name_filter_combo.addItem(DIRECTION_ALL)
        if self.dbc and self.dbc.is_loaded:
            self.name_filter_combo.addItems(self.dbc.message_names())
        self.name_filter_combo.blockSignals(False)
        # Combo "Tümü"ne döndü; eski isim filtresi etkin kalırsa tüm kareler gizlenirdi.
        self._name_filter = None

    def set_bitrate(self, bitrate: int | None):
        self.stats.set_bitrate(bitrate)

    # ---- Mesaj işleme ----------------------------------------------------
    def add_message(self, msg: can.Message, direction: str = "RX"):
        is_error = bool(getattr(msg, "is_error_frame", False))

        if direction == "RX":
            self.stats.record_rx(msg.dlc, msg.is_extended_id, msg.timestamp)
        else:
            self.stats.record_tx()
        self._update_stats_label()

        if self._paused:
            return
        if self._id_filter is not None and msg.arbitration_id != self._id_filter:
            return
        if self._direction_filter != DIRECTION_ALL and direction != self._direction_filter:
            return
        if self._errors_only and not is_error:
            return

        decoded_name, decoded_signals = None, None
        if self.dbc and self.dbc.is_loaded:
            result = self.dbc.decode_frame(msg.arbitration_id, msg.data)
            if result is not None:
                decoded_name, decoded_signals = result

        if self._name_filter is not None and decoded_name != self._name_filter:
            return

        if self._t0 is None:
            self._t0 = msg.timestamp
        relative_ms = (msg.timestamp - self._t0) * 1000.0

        can_id = msg.arbitration_id
        key = (can_id, bool(msg.is_extended_id))
        self._counts[key] = self._counts.get(key, 0) + 1

        row = self._row_by_id.get(key)
        if row is None:
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._row_by_id[key] = row
            self.table.setItem(row, 2, QTableWidgetItem(f"0x{can_id:X}"))

        signal_text = ""
        if decoded_signals is not None:
            signal_text = ", ".join(f"{k}={v}" for k, v in decoded_signals.items())

        self.table.setItem(row, 0, QTableWidgetItem(direction))
        self.table.setItem(row, 1, QTableWidgetItem(f"{relative_ms:.1f}"))
        self.table.setItem(row, 3, QTableWidgetItem(decoded_name or ""))
        self.table.setItem(row, 4, QTableWidgetItem(str(msg.dlc)))
        self.table.setItem(row, 5, QTableWidgetItem(msg.data.hex(sep=" ").upper()))
        self.table.setItem(row, 6, QTableWidgetItem(signal_text))
        self.table.setItem(row, 7, QTableWidgetItem("EVET" if is_error else ""))
        self.table.setItem(row, 8, QTableWidgetItem(str(self._counts[key])))

    def _update_stats_label(self):
        bus_load = self.stats.bus_load_percent()
        bus_load_text = f"{bus_load:.1f}%" if bus_load is not None else "-"
        self.stats_label.setText(
            f"Toplam RX: {self.stats.total_rx}   Toplam TX: {self.stats.total_tx}   "
            f"RX hızı: {self.stats.rx_rate():.1f} msg/s   Bus Load: {bus_load_text}"
        )

    def clear(self):
        self.table.setRowCount(0)
        self._t0 = None
        self._row_by_id.clear()
        self._counts.clear()
        self.stats.reset()
        self._update_stats_label()
