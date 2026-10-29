"""CAN Monitor sekmesi: eskiden ayrı olan Bağlantı, İzleme, Gönderim ve
Log sekmelerinin BİRLEŞTİRİLMİŞ hali. İçerideki widget'lar (ConnectionTab,
MonitorTab, TransmitTab, LogTab) hiç değiştirilmeden, olduğu gibi yeniden
kullanılır — burada sadece dışarıdan görünen yerleşim değişir. MainWindow
hâlâ bu iç widget'ların sinyallerine (örn. `can_monitor_tab.connection.
connect_requested`) bağlanır; CAN/DBC mantığının kendisi taşınmamıştır.

Yerleşim: üstte "Bağlantı" grubu (arayüz/backend seçimi varsayılan olarak
"▸ Gelişmiş ayarlar" açılır-kapanır bölmesinin ARKASINA gizlenir — kanal/
baudrate/bağlan-kes/sağlık her zaman görünür kalır), ortada iki sütunlu
"İzleme" / "Gönderim" bölmesi, altta "Log" bölümü.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGroupBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from app.ui.connection_tab import ConnectionTab
from app.ui.log_tab import LogTab
from app.ui.monitor_tab import MonitorTab
from app.ui.transmit_tab import TransmitTab


class CanMonitorTab(QWidget):
    def __init__(self):
        super().__init__()

        # ---- İç widget'lar (değiştirilmeden yeniden kullanılıyor) ----
        self.connection = ConnectionTab()
        self.monitor = MonitorTab()
        self.transmit = TransmitTab()
        self.log = LogTab()

        outer = QVBoxLayout(self)
        outer.addWidget(self._build_connection_section())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._wrap("İzleme", self.monitor))
        split.addWidget(self._wrap("Gönderim", self.transmit))
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        outer.addWidget(split, stretch=1)

        outer.addWidget(self._wrap("Log", self.log))

    @staticmethod
    def _wrap(title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(widget)
        box.setLayout(layout)
        return box

    def _build_connection_section(self) -> QGroupBox:
        box = QGroupBox("Bağlantı")
        layout = QVBoxLayout()

        # Kanal/baudrate/bağlan-kes/sağlık her zaman görünür; yalnızca
        # arayüz/backend (pcan/virtual/udp_multicast) seçimi, varsayılan
        # backend'i değiştirmek NADİREN gerektiği için "Gelişmiş ayarlar"ın
        # arkasına gizlenir (bkz. ConnectionTab.set_interface_row_visible).
        self.connection.set_interface_row_visible(False)

        self.advanced_toggle = QPushButton("▸ Gelişmiş ayarlar (arayüz/backend)")
        self.advanced_toggle.setCheckable(True)
        self.advanced_toggle.setFlat(True)
        self.advanced_toggle.toggled.connect(self._on_advanced_toggled)

        layout.addWidget(self.advanced_toggle)
        layout.addWidget(self.connection)
        box.setLayout(layout)
        return box

    def _on_advanced_toggled(self, checked: bool):
        self.connection.set_interface_row_visible(checked)
        self.advanced_toggle.setText(
            "▾ Gelişmiş ayarlar (arayüz/backend)" if checked else "▸ Gelişmiş ayarlar (arayüz/backend)"
        )
