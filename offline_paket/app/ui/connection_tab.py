"""CAN Monitor üst şeridindeki bağlantı bölümü.

Canlı kullanım için arayüz (backend) ve kanal seçimi arayüzden KALDIRILDI: arayüz
sabit ``pcan`` (PCAN-USB), kanal varsayılan ``PCAN_USBBUS1``. Birden fazla PCAN
adaptörü algılanırsa yalnızca o durumda küçük bir adaptör seçici görünür. Çevrimdışı
geliştirme/test için ``OPENECU_CAN_INTERFACE=virtual`` (veya ``udp_multicast``)
ortam değişkeni arayüzü değiştirir; arayüzde görünmez.

Gerçek python-can çağrılarını MainWindow yapar; bu widget yalnızca istekleri sinyal
olarak bildirir. Son baudrate ve "açılışta otomatik bağlan" seçimi diske kaydedilir.
"""
import json
import os

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QWidget,
)

BAUDRATES = [100_000, 125_000, 250_000, 500_000, 800_000, 1_000_000]
DEFAULT_BAUDRATE = 500_000
DEFAULT_CHANNELS = {"pcan": "PCAN_USBBUS1", "virtual": "test", "udp_multicast": "239.0.0.1"}


def default_interface() -> str:
    iface = os.environ.get("OPENECU_CAN_INTERFACE", "pcan").strip() or "pcan"
    return iface if iface in DEFAULT_CHANNELS else "pcan"


def normalize_interface(interface: str, channel: str) -> tuple:
    """Eski profillerdeki 'virtual/udp_multicast' değerleri canlı kullanımda PCAN'a çevrilir
    (ortam değişkeniyle geliştirme arayüzü seçilmişse olduğu gibi bırakılır)."""
    wanted = default_interface()
    if wanted != "pcan":
        return wanted, DEFAULT_CHANNELS[wanted]
    if interface != "pcan" or not channel or channel == "test":
        return "pcan", DEFAULT_CHANNELS["pcan"]
    return "pcan", channel


def detect_pcan_channels() -> list:
    """Takılı PCAN adaptörlerinin kanal adları; sürücü yoksa/hata olursa boş liste."""
    try:
        import can
        return [c["channel"] for c in can.detect_available_configs("pcan")]
    except Exception:
        return []


class ConnectionTab(QWidget):
    """Bağlantı kurma/kesme isteklerini sinyal olarak dışarı bildirir;
    gerçek python-can çağrılarını MainWindow üstlenir (tek sorumluluk)."""

    connect_requested = Signal(str, str, int)   # interface, channel, bitrate
    disconnect_requested = Signal()
    settings_changed = Signal()

    def __init__(self):
        super().__init__()
        self._interface = default_interface()
        self._channel = DEFAULT_CHANNELS[self._interface]
        self._connected = False
        self._settings_path: str | None = None

        self.status_dot = QLabel("●")
        self.status_dot.setObjectName("statusDot")
        self.status_dot.setProperty("state", "bad")
        self.status_label = QLabel("Bağlı değil")
        self.status_label.setObjectName("rowName")

        self.baudrate_combo = QComboBox()
        for rate in BAUDRATES:
            self.baudrate_combo.addItem(f"{rate / 1000:g} kbit/s", rate)
        self.baudrate_combo.setCurrentIndex(BAUDRATES.index(DEFAULT_BAUDRATE))
        self.baudrate_combo.currentIndexChanged.connect(lambda _i: self._changed())

        # Yalnız birden fazla PCAN adaptörü varsa görünür.
        self.adapter_combo = QComboBox()
        self.adapter_combo.setVisible(False)
        self.adapter_combo.setToolTip("Birden fazla PCAN adaptörü algılandı")
        self.adapter_combo.currentIndexChanged.connect(self._on_adapter_changed)

        self.connect_button = QPushButton("Bağlan")
        self.connect_button.setProperty("tone", "go")
        self.disconnect_button = QPushButton("Bağlantıyı kes")
        self.disconnect_button.setEnabled(False)
        self.auto_connect_check = QCheckBox("Açılışta otomatik bağlan")
        self.auto_connect_check.toggled.connect(lambda _c: self._changed())
        self.health_label = QLabel("")
        self.health_label.setObjectName("mutedSmall")

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        lay.addWidget(self.status_dot)
        lay.addWidget(self.status_label)
        lay.addSpacing(6)
        lay.addWidget(QLabel("Baudrate"))
        lay.addWidget(self.baudrate_combo)
        lay.addWidget(self.adapter_combo)
        lay.addWidget(self.connect_button)
        lay.addWidget(self.disconnect_button)
        lay.addWidget(self.auto_connect_check)
        lay.addWidget(self.health_label, 1)

        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)
        self.refresh_adapters()

    # ---- arayüz/kanal (görünmez; yalnız değerleri okunur) ---------------------
    def current_interface(self) -> str:
        return self._interface

    def current_channel(self) -> str:
        return self._channel

    def current_bitrate(self) -> int:
        return self.baudrate_combo.currentData()

    def refresh_adapters(self):
        """Takılı PCAN adaptörlerini tarar; birden fazlaysa seçiciyi gösterir."""
        if self._interface != "pcan" or self._connected:
            return
        channels = detect_pcan_channels()
        self.adapter_combo.blockSignals(True)
        self.adapter_combo.clear()
        for ch in channels:
            self.adapter_combo.addItem(ch.replace("PCAN_USBBUS", "PCAN-USB "), ch)
        if self._channel in channels:
            self.adapter_combo.setCurrentIndex(channels.index(self._channel))
        elif channels:
            self._channel = channels[0]
        self.adapter_combo.blockSignals(False)
        self.adapter_combo.setVisible(len(channels) > 1)

    def _on_adapter_changed(self, _i):
        data = self.adapter_combo.currentData()
        if data:
            self._channel = data
            self._changed()

    def _on_connect_clicked(self):
        self.refresh_adapters()
        self.connect_requested.emit(self._interface, self._channel, self.current_bitrate())

    # ---- durum ---------------------------------------------------------------
    def _set_state(self, state: str, text: str):
        self.status_dot.setProperty("state", state)
        self.status_dot.style().unpolish(self.status_dot)
        self.status_dot.style().polish(self.status_dot)
        self.status_label.setText(text)

    def _adapter_name(self) -> str:
        return {"pcan": "PCAN-USB", "virtual": "Sanal kanal", "udp_multicast": "UDP"}[self._interface]

    def set_connected(self, connected: bool):
        self._connected = connected
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.baudrate_combo.setEnabled(not connected)
        self.adapter_combo.setEnabled(not connected)
        if connected:
            self._set_state("ok", f"Bağlı · {self._adapter_name()} · {self.current_bitrate() / 1000:g} kbit/s")
        else:
            self._set_state("bad", "Bağlı değil")
            self.health_label.setText("")

    def set_lost(self, lost: bool):
        """Bağlantı (adaptör) kaybı durumunu gösterir; set_connected() sıfırlar."""
        if lost:
            self._set_state("bad", "Bağlantı KOPTU — yeniden bağlanılıyor…")
        elif self.disconnect_button.isEnabled():
            self._set_state("ok", f"Bağlı · {self._adapter_name()} · {self.current_bitrate() / 1000:g} kbit/s")

    def apply_profile_values(self, interface: str, channel: str, bitrate: int):
        """Bir konfigürasyon profili uygulanırken değerleri doldurur (bağlıyken çağrılmaz)."""
        self._interface, self._channel = normalize_interface(interface, channel)
        idx = self.baudrate_combo.findData(bitrate)
        if idx >= 0:
            self.baudrate_combo.setCurrentIndex(idx)
        self.refresh_adapters()

    def set_health(self, ok: bool, message: str):
        """Periyodik sağlık kontrolü: can.Bus() açılması ile donanımın GERÇEKTEN sağlıklı
        olması farklı şeylerdir, ikincisini gösterir."""
        self.health_label.setText(message)
        self.health_label.setObjectName("okSmall" if ok else "warnSmall")
        self.health_label.style().unpolish(self.health_label)
        self.health_label.style().polish(self.health_label)
        if self.disconnect_button.isEnabled():
            self._set_state("ok" if ok else "warn",
                            f"Bağlı · {self._adapter_name()} · {self.current_bitrate() / 1000:g} kbit/s")

    # ---- kalıcı ayarlar -------------------------------------------------------
    def attach_settings(self, path: str):
        """Son baudrate ve otomatik-bağlan seçimini yükler; değişince diske yazar."""
        self._settings_path = None
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError):
            raw = {}
        idx = self.baudrate_combo.findData(raw.get("bitrate"))
        if idx >= 0:
            self.baudrate_combo.setCurrentIndex(idx)
        if raw.get("channel") and self._interface == "pcan":
            self._channel = raw["channel"]
            self.refresh_adapters()
        self.auto_connect_check.setChecked(bool(raw.get("auto_connect", False)))
        self._settings_path = path

    def auto_connect_enabled(self) -> bool:
        return self.auto_connect_check.isChecked()

    def _changed(self):
        self.settings_changed.emit()
        if not self._settings_path:
            return
        try:
            with open(self._settings_path, "w", encoding="utf-8") as f:
                json.dump({"bitrate": self.current_bitrate(), "channel": self._channel,
                           "auto_connect": self.auto_connect_check.isChecked()}, f, indent=2)
        except OSError:
            pass
