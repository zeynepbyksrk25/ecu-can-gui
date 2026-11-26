"""Kalibrasyon sekmesi: eskiden ayrı olan A2L, Kalibrasyon (CCP), Parametre Listesi,
ve Kalibrasyon Geçmişi sekmelerinin TEK sayfada, İÇ (nested)
bir sekme çubuğuyla birleştirilmiş hali ("iç sekmeli" tasarım). İç widget'lar
(A2LTab, CCPTab, WatchTab, HistoryTab) yeniden kullanılır; MainWindow
onlara `kalibrasyon_tab.a2l`, `.ccp`, `.watch`, `.history`
üzerinden ulaşır. A2L, ilk iç sekmedir: tüm kalibrasyon sekmeleri onun yüklediği
dosyaya dayanır, bu yüzden akış A2L → CCP → Parametre sırasındadır. Haritalar (CURVE/MAP/ARRAY) Worksheets (Modas) sayfasında açılır.

İç sekme çubuğu, dış (üst düzey) sekme çubuğuyla karışmasın diye
`objectName("innerTabs")` ile işaretlenir ve app/theme.py'de
`QTabWidget#innerTabs` seçicisiyle görsel olarak ayırt edilir (farklı
renk/kalınlık).
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from app.ui.a2l_tab import A2LTab
from app.ui.ccp_tab import CCPTab
from app.ui.history_tab import HistoryTab
from app.ui.watch_tab import WatchTab


class KalibrasyonTab(QWidget):
    def __init__(self, a2l_tab: A2LTab | None = None):
        super().__init__()

        self.a2l = a2l_tab if a2l_tab is not None else A2LTab()
        self.ccp = CCPTab()
        self.watch = WatchTab()
        self.history = HistoryTab()

        self.inner_tabs = QTabWidget()
        self.inner_tabs.setObjectName("innerTabs")
        self.inner_tabs.addTab(self.a2l, "A2L")
        self.inner_tabs.addTab(self.ccp, "CCP")
        self.inner_tabs.addTab(self.watch, "Parametre Listesi")
        self.inner_tabs.addTab(self.history, "Geçmiş")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.addWidget(self.inner_tabs)
