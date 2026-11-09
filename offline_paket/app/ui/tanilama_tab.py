"""Tanılama ve Oturum sayfası (koyu tema).

Sol: **CCP tanılama** (bağlantı testi + DIAG_SERVICE).
Sağ: **CAN sağlığı** + **test oturumu** (başlat/bitir, PDF rapor) + TEK **olay günlüğü**
("Tümü | Yalnız hatalar" süzgeçli). Eskiden ayrı olan Tanılama ve Test Oturumu sekmeleri birleşti;
`tanilama_tab.diagnostics`, `.errors` (sağlık) ve `.session` üzerinden erişilir."""

from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.ui.diagnostics_tab import DiagnosticsTab
from app.ui.errors_tab import ErrorsTab
from app.ui.session_tab import SessionTab


class TanilamaTab(QWidget):
    def __init__(self):
        super().__init__()
        self.diagnostics = DiagnosticsTab()
        self.errors = ErrorsTab()
        self.session = SessionTab()
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        right.addWidget(self.errors, 0)
        right.addWidget(self.session, 1)
        right_w = QWidget()
        right_w.setLayout(right)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(14, 8, 14, 8)
        outer.setSpacing(10)
        outer.addWidget(self.diagnostics, 5)
        outer.addWidget(right_w, 6)
