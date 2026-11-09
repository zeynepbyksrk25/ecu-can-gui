"""Analiz sekmesi: eskiden ayrı üst sekmeler olan Grafik, Çalışma Alanı ve Performans'ın TEK
sayfada, İÇ (nested) sekme çubuğuyla birleştirilmiş hali (Kalibrasyon sekmesiyle aynı kalıp).

İç widget'lar (GraphTab, WorkspaceTab, PerformanceTab) DEĞİŞMEDEN yeniden kullanılır;
MainWindow onlara ``graph_tab`` / ``workspace_tab`` / ``performance_tab`` takma adlarıyla
ulaşmaya devam eder, bu yüzden sinyal bağlantıları ve CCP/CAN besleme kodu aynen çalışır.
"""

from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class AnalizTab(QWidget):
    def __init__(self, graph, workspace, performance):
        super().__init__()
        self.graph = graph
        self.workspace = workspace
        self.performance = performance

        self.inner_tabs = QTabWidget()
        self.inner_tabs.setObjectName("innerTabs")
        self.inner_tabs.addTab(self.graph, "Grafik")
        self.inner_tabs.addTab(self.workspace, "Çalışma Alanı")
        self.inner_tabs.addTab(self.performance, "Performans")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.addWidget(self.inner_tabs)

    def select(self, widget) -> bool:
        """İç sekmelerden birini öne getirir (ör. Ana Sayfa'daki 'Grafik' düğmesi)."""
        if self.inner_tabs.indexOf(widget) == -1:
            return False
        self.inner_tabs.setCurrentWidget(widget)
        return True
