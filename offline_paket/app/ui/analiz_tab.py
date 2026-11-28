"""Analiz sekmesi: Çalışma Alanı (WorkspaceTab) iç sekme çubuğuyla sarılır. WorkspaceTab DEĞİŞMEDEN yeniden kullanılır;
MainWindow ona ``workspace_tab`` takma adıyla ulaşmaya devam eder, bu yüzden sinyal bağlantıları ve CCP/CAN besleme
kodu aynen çalışır. (Performans sayfası kaldırıldı: motora özel sabit düzen, Worksheets Scope ve Çalışma Alanı ile
aynı sinyaller çizilebiliyor.)"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class AnalizTab(QWidget):
    def __init__(self, workspace):
        super().__init__()
        self.workspace = workspace

        self.inner_tabs = QTabWidget()
        self.inner_tabs.setObjectName("innerTabs")
        self.inner_tabs.addTab(self.workspace, "Çalışma Alanı")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.addWidget(self.inner_tabs)

    def select(self, widget) -> bool:
        """İç sekmelerden birini öne getirir."""
        if self.inner_tabs.indexOf(widget) == -1:
            return False
        self.inner_tabs.setCurrentWidget(widget)
        return True
