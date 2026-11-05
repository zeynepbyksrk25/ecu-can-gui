"""CAN Monitor sayfası (Ana Sayfa ile aynı koyu tasarım): üstte bağlantı şeridi, altta iki kart:
**İzleme** (sol; başlığında DBC yükle + kayıt) ve **Gönderim** (sağ; Manuel / Periyodik sekmeleri).

İç widget'lar (ConnectionTab, MonitorTab, TransmitTab, LogTab) MainWindow'un bağlandığı
sinyalleri/özellikleri taşımaya devam eder; burada yalnızca dışarıdan görünen yerleşim ve stil vardır.
"""
import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from app.ui.connection_tab import ConnectionTab
from app.ui.dark_theme import dark_qss
from app.ui.dash_widgets import DK_CYAN, IconLabel
from app.ui.log_tab import LogTab
from app.ui.monitor_tab import MonitorTab
from app.ui.transmit_tab import TransmitTab


class CanMonitorTab(QWidget):
    def __init__(self):
        super().__init__()
        self.connection = ConnectionTab()
        self.monitor = MonitorTab()
        self.transmit = TransmitTab()
        self.log = LogTab()

        # Koyu stil yalnızca bu iç gövdeye uygulanır (QMessageBox/QDialog açık temada kalır).
        body = QWidget()
        body.setObjectName("canBody")
        body.setStyleSheet(dark_qss("canBody"))
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body)

        lay = QVBoxLayout(body)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(10)

        strip = QFrame()
        strip.setObjectName("stripBar")
        sl = QHBoxLayout(strip)
        sl.setContentsMargins(14, 8, 14, 8)
        sl.addWidget(self.connection)
        lay.addWidget(strip)

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._monitor_card())
        split.addWidget(self._transmit_card())
        split.setStretchFactor(0, 7)
        split.setStretchFactor(1, 4)
        split.setSizes([800, 480])
        split.setChildrenCollapsible(False)
        lay.addWidget(split, 1)

        self.transmit.dbc_loaded.connect(self._update_dbc_chip)

    # ---- kartlar ----------------------------------------------------------------
    @staticmethod
    def _card(title: str, icon: str) -> tuple:
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(14, 10, 14, 10)
        cl.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel(icon, DK_CYAN, 18))
        t = QLabel(title)
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        cl.addLayout(head)
        return card, cl, head

    def _monitor_card(self) -> QFrame:
        card, cl, head = self._card("İZLEME", "trend")
        self.dbc_button = QPushButton("DBC Yükle…")
        self.dbc_button.setProperty("compact", True)
        self.dbc_button.setToolTip("Mesaj adları ve sinyal değerleri için DBC dosyası yükle")
        self.dbc_button.clicked.connect(self.transmit.load_dbc_dialog)
        self.dbc_chip = QLabel("DBC yok")
        self.dbc_chip.setObjectName("chipDim")
        head.addWidget(self.dbc_button)
        head.addWidget(self.dbc_chip)
        head.addSpacing(10)
        head.addWidget(self.log)
        cl.addWidget(self.monitor, 1)
        return card

    def _transmit_card(self) -> QFrame:
        card, cl, _head = self._card("GÖNDERİM", "spark")
        cl.addWidget(self.transmit, 1)
        return card

    def _update_dbc_chip(self):
        dbc = self.transmit.dbc
        if dbc.is_loaded:
            self.dbc_chip.setText(f"{os.path.basename(dbc.path or '')} · {len(dbc.message_names())} mesaj")
            self.dbc_chip.setToolTip(dbc.path or "")
        else:
            self.dbc_chip.setText("DBC yok")
