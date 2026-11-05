"""Tanılama sayfası (koyu tema): solda **CCP tanılama** (bağlantı testi + DIAG_SERVICE), sağda **CAN sağlığı ve
hata günlüğü**. İç widget'lar (DiagnosticsTab, ErrorsTab) MainWindow'un bağlandığı sinyalleri taşır;
`tanilama_tab.diagnostics` ve `tanilama_tab.errors` üzerinden erişilir."""

from PySide6.QtWidgets import QHBoxLayout, QWidget

from app.ui.diagnostics_tab import DiagnosticsTab
from app.ui.errors_tab import ErrorsTab


class TanilamaTab(QWidget):
    def __init__(self):
        super().__init__()
        self.diagnostics = DiagnosticsTab()
        self.errors = ErrorsTab()
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(10)
        outer.addWidget(self.diagnostics, 5)
        outer.addWidget(self.errors, 6)
