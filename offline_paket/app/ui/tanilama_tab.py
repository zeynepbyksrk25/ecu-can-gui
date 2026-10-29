"""Tanılama sekmesi: eskiden ayrı olan Diagnostics (CCP bağlantı testi +
ham DIAG_SERVICE isteği) ve Hatalar (CAN sağlığı + birleşik HATA olay
listesi) sekmelerinin BİRLEŞTİRİLMİŞ hali. İç widget'lar (DiagnosticsTab,
ErrorsTab) değiştirilmeden yeniden kullanılır; MainWindow onların
sinyallerine/erişimcilerine `tanilama_tab.diagnostics` ve
`tanilama_tab.errors` üzerinden ulaşır.
"""

from PySide6.QtWidgets import QGroupBox, QVBoxLayout, QWidget

from app.ui.diagnostics_tab import DiagnosticsTab
from app.ui.errors_tab import ErrorsTab


class TanilamaTab(QWidget):
    def __init__(self):
        super().__init__()

        self.diagnostics = DiagnosticsTab()
        self.errors = ErrorsTab()

        outer = QVBoxLayout(self)
        outer.addWidget(self._wrap("CCP Tanılama", self.diagnostics))
        outer.addWidget(self._wrap("CAN Sağlığı ve Hata Günlüğü", self.errors), stretch=1)

    @staticmethod
    def _wrap(title: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(title)
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(widget)
        box.setLayout(layout)
        return box
