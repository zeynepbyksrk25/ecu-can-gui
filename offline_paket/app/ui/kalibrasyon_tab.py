"""Kalibrasyon sekmesi: eskiden ayrı olan Kalibrasyon (CCP), Parametre Listesi,
Harita Editörü ve Kalibrasyon Geçmişi sekmelerinin TEK sayfada, İÇ (nested)
bir sekme çubuğuyla birleştirilmiş hali ("iç sekmeli" tasarım). İç widget'lar
(CCPTab, WatchTab, MapEditorTab, HistoryTab) yeniden kullanılır; MainWindow
onlara `kalibrasyon_tab.ccp`, `.watch`, `.map_editor`, `.history`
üzerinden ulaşır.

İç sekme çubuğu, dış (üst düzey) sekme çubuğuyla karışmasın diye
`objectName("innerTabs")` ile işaretlenir ve app/theme.py'de
`QTabWidget#innerTabs` seçicisiyle görsel olarak ayırt edilir (farklı
renk/kalınlık).
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget

from app.ui.ccp_tab import CCPTab
from app.ui.history_tab import HistoryTab
from app.ui.map_editor_tab import MapEditorTab
from app.ui.watch_tab import WatchTab


class KalibrasyonTab(QWidget):
    def __init__(self):
        super().__init__()

        self.ccp = CCPTab()
        self.watch = WatchTab()
        self.map_editor = MapEditorTab()
        self.history = HistoryTab()

        self.inner_tabs = QTabWidget()
        self.inner_tabs.setObjectName("innerTabs")
        self.inner_tabs.addTab(self.ccp, "CCP")
        self.inner_tabs.addTab(self.watch, "Parametre Listesi")
        self.inner_tabs.addTab(self.map_editor, "Harita Editörü")
        self.inner_tabs.addTab(self.history, "Geçmiş")

        layout = QVBoxLayout(self)
        layout.addWidget(self.inner_tabs)
