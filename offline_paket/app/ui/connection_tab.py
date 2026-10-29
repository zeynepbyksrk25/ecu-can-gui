from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QWidget,
)

BAUDRATES = [125_000, 250_000, 500_000, 1_000_000]


class ConnectionTab(QWidget):
    """Bağlantı kurma/kesme isteklerini sinyal olarak dışarı bildirir;
    gerçek python-can çağrılarını MainWindow üstlenir (tek sorumluluk)."""

    connect_requested = Signal(str, str, int)   # interface, channel, bitrate
    disconnect_requested = Signal()

    def __init__(self):
        super().__init__()

        self.interface_combo = QComboBox()
        self.interface_combo.addItems(["virtual", "udp_multicast", "pcan"])
        self.interface_combo.setToolTip(
            "virtual: TEK pencere içi test (iki ayrı pencere birbirini GÖRMEZ).\n"
            "udp_multicast: bu bilgisayarda AÇIK BİRDEN FAZLA pencere arasında "
            "gönder-al test etmek için (donanımsız, gerçekçi test).\n"
            "pcan: Windows + gerçek PCAN-USB donanımı için."
        )
        self.interface_combo.currentTextChanged.connect(self._on_interface_changed)

        self.channel_edit = QLineEdit()
        self.channel_edit.setText("test")

        self.baudrate_combo = QComboBox()
        for rate in BAUDRATES:
            self.baudrate_combo.addItem(f"{rate // 1000} kbps", rate)
        self.baudrate_combo.setCurrentIndex(2)  # 500 kbps varsayılan

        self.connect_button = QPushButton("Bağlan")
        self.disconnect_button = QPushButton("Bağlantıyı kes")
        self.disconnect_button.setEnabled(False)

        self.status_label = QLabel("● Bağlı değil")
        self.status_label.setStyleSheet("color: red; font-weight: bold;")

        self.health_label = QLabel("")

        self._interface_label = QLabel("Arayüz:")

        form = QFormLayout()
        self.channel_edit.setMaximumWidth(260)
        self.baudrate_combo.setMaximumWidth(260)
        self.interface_combo.setMaximumWidth(260)
        form.addRow(self._interface_label, self.interface_combo)
        form.addRow("Kanal:", self.channel_edit)
        form.addRow("Baudrate:", self.baudrate_combo)

        buttons = QHBoxLayout()
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        buttons.addStretch()
        buttons.addWidget(self.status_label)

        layout = QFormLayout(self)
        layout.addRow(form)
        layout.addRow(buttons)
        layout.addRow("Bağlantı durumu:", self.health_label)

        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)

    def set_interface_row_visible(self, visible: bool):
        """CanMonitorTab, bu satırı varsayılan olarak "▸ Gelişmiş ayarlar"
        bölmesinin arkasına gizlemek için kullanır; kanal/baudrate/
        bağlan-kes/sağlık her zaman görünür kalır."""
        self._interface_label.setVisible(visible)
        self.interface_combo.setVisible(visible)

    def _on_interface_changed(self, interface: str):
        defaults = {
            "virtual": "test",
            "udp_multicast": "239.0.0.1",
            "pcan": "PCAN_USBBUS1",
        }
        self.channel_edit.setText(defaults.get(interface, ""))

    def _on_connect_clicked(self):
        interface = self.interface_combo.currentText()
        channel = self.channel_edit.text().strip()
        bitrate = self.baudrate_combo.currentData()
        self.connect_requested.emit(interface, channel, bitrate)

    def set_connected(self, connected: bool):
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.interface_combo.setEnabled(not connected)
        self.channel_edit.setEnabled(not connected)
        self.baudrate_combo.setEnabled(not connected)
        if connected:
            self.status_label.setText("● Bağlı")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.status_label.setText("● Bağlı değil")
            self.status_label.setStyleSheet("color: red; font-weight: bold;")
            self.health_label.setText("")

    def set_lost(self, lost: bool):
        """Bağlantı (adaptör) kaybı durumunu gösterir; set_connected() sıfırlar."""
        if lost:
            self.status_label.setText("● Bağlantı KOPTU — yeniden bağlanılıyor…")
            self.status_label.setStyleSheet("color: #c00000; font-weight: bold;")
        elif self.disconnect_button.isEnabled():
            self.status_label.setText("● Bağlı")
            self.status_label.setStyleSheet("color: green; font-weight: bold;")

    def apply_profile_values(self, interface: str, channel: str, bitrate: int):
        """Bir konfigürasyon profili uygulanırken alanları doldurur
        (bağlıyken çağrılmaz — MainWindow bunu garanti eder)."""
        self.interface_combo.setCurrentText(interface)
        self.channel_edit.setText(channel)
        idx = self.baudrate_combo.findData(bitrate)
        if idx >= 0:
            self.baudrate_combo.setCurrentIndex(idx)

    def set_health(self, ok: bool, message: str):
        """MainWindow'daki periyodik sağlık kontrolü tarafından çağrılır;
        can.Bus() çağrısının başarılı olması ile donanımın GERÇEKTEN
        sağlıklı olması farklı şeylerdir, bu ikincisini gösterir."""
        color = "green" if ok else "#b06a00"
        self.health_label.setText(message)
        self.health_label.setStyleSheet(f"color: {color};")
