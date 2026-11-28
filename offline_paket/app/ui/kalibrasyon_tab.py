"""Kalibrasyon (Calibration Tools) sayfası: Kalibrasyon (CCP) ve Kalibrasyon Geçmişi, TEK sayfada İÇ (nested) bir
sekme çubuğuyla. MainWindow onlara `kalibrasyon_tab.ccp`, `.history` üzerinden ulaşır.

A2L'nin kendi sekmesi YOK: A2L dosyası Project Manager'daki workbase'den (ya da profilden) yüklenir, nesneler
Worksheets'in Variable list'inde gezilir, bilgi için `Ctrl+I` kullanılır. Yükleme/ayrıştırma arka planda ``A2LTab``
nesnesinde (MainWindow.a2l_tab) yapılır; bu nesne ekranda gösterilmez. Haritalar (CURVE/MAP/ARRAY) Worksheets (Modas)
penceresinde açılır.

İç sekme çubuğu, dış (üst düzey) sekme çubuğuyla karışmasın diye
`objectName("innerTabs")` ile işaretlenir ve app/theme.py'de
`QTabWidget#innerTabs` seçicisiyle görsel olarak ayırt edilir (farklı
renk/kalınlık).
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from app.ui.ccp_tab import CCPTab
from app.ui.history_tab import HistoryTab


class KalibrasyonTab(QWidget):
    def __init__(self):
        super().__init__()

        self.ccp = CCPTab()
        self.history = HistoryTab()

        self.inner_tabs = QTabWidget()
        self.inner_tabs.setObjectName("innerTabs")
        self.inner_tabs.addTab(self.ccp, "CCP")
        self.inner_tabs.addTab(self.history, "Geçmiş")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.addWidget(self.inner_tabs)
