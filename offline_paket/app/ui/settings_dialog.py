"""Ayarlar penceresi: kullanıcı ve bağlantı+CCP profilleri.

Eskiden ayrı bir "Profil" üst sekmesiydi; seyrek kullanılan bu ayarlar artık komut şeridindeki
"⚙ Ayarlar" düğmesinden (ya da "Kullanıcı: …" etiketine tıklayarak) açılan pencerededir. İçindeki
``UserTab`` widget'ı değişmeden yeniden kullanılır; MainWindow onun sinyallerine bağlı kalır.
"""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from app.ui.dark_theme import dark_scroll_page


class SettingsDialog(QDialog):
    mappings_requested = Signal()

    def __init__(self, user_tab, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Ayarlar")
        self.setModal(True)
        self.resize(980, 520)
        self.user_tab = user_tab

        mappings = QPushButton("⚙  Eşleşmeleri düzenle…")
        mappings.setToolTip("Sensör, eyleyici, motor komutu ve giriş sinyallerinin CAN (DBC) / A2L eşleşmeleri")
        mappings.clicked.connect(self._on_mappings)
        close = QPushButton("Kapat")
        close.clicked.connect(self.accept)
        close.setDefault(True)
        buttons = QHBoxLayout()
        buttons.setContentsMargins(14, 0, 14, 10)
        buttons.addWidget(mappings)
        buttons.addStretch(1)
        buttons.addWidget(close)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(dark_scroll_page(user_tab), 1)
        lay.addLayout(buttons)

    def _on_mappings(self):
        # Eşleşmeler penceresi bu pencerenin üstünde açılmasın: önce kapat, sonra aç.
        self.accept()
        QTimer.singleShot(0, self.mappings_requested.emit)
