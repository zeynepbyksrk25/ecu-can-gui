"""Kullanıcı / Profil içeriği (Ayarlar penceresinde, bkz. settings_dialog.py): kullanıcı ismi (denetim kayıtları için; tek rol
Mühendis) ve bağlantı+CCP ayarlarını isimli profiller olarak kaydedip yeniden uygulama.

Bu bir kimlik doğrulama (authentication) sistemi DEĞİLDİR — bkz. app/user_roles.py docstring'i.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from app.ui.dash_widgets import make_card
from app.user_roles import ROL_ADI


class UserTab(QWidget):
    user_applied = Signal(str)               # kullanıcı adı
    profile_apply_requested = Signal(str)    # profil ismi
    profile_save_requested = Signal(str)     # profil ismi (mevcut form alanlarından)
    profile_delete_requested = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)
        left = QVBoxLayout()
        left.addWidget(self._build_user_card())
        left.addStretch(1)
        layout.addLayout(left, 4)
        layout.addWidget(self._build_profile_card(), 5)

    def _build_user_card(self):
        card, v, head = make_card("Kullanıcı", "plane")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Kullanıcı ismi")
        apply_button = QPushButton("Uygula")
        apply_button.setProperty("tone", "go")
        apply_button.clicked.connect(self._on_apply_user)
        self.user_edit.returnPressed.connect(self._on_apply_user)
        self.current_label = QLabel(f"Aktif: - ({ROL_ADI})")
        self.current_label.setObjectName("chipBlue")
        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        form.addRow("Kullanıcı ismi:", self.user_edit)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(apply_button)
        row.addWidget(self.current_label)
        row.addStretch()
        note = QLabel(f"Tek rol vardır: {ROL_ADI}. İşlemler denetim günlüğüne bu kullanıcı adıyla kaydedilir; "
                      "bu bir kimlik doğrulama değildir.")
        note.setObjectName("mutedSmall")
        note.setWordWrap(True)
        v.addLayout(form)
        v.addLayout(row)
        v.addWidget(note)
        return card

    def _on_apply_user(self):
        name = self.user_edit.text().strip() or "bilinmeyen"
        self.user_applied.emit(name)
        self.current_label.setText(f"Aktif: {name} ({ROL_ADI})")

    def _build_profile_card(self):
        card, v, _head = make_card("Profiller", "sliders")
        self.profile_list = QListWidget()
        self.profile_name_edit = QLineEdit()
        self.profile_name_edit.setPlaceholderText("Yeni profil ismi")

        save_button = QPushButton("Mevcut ayarları profil olarak kaydet")
        save_button.clicked.connect(self._on_save)
        apply_button = QPushButton("Seçili profili uygula")
        apply_button.setProperty("tone", "go")
        apply_button.clicked.connect(self._on_apply)
        delete_button = QPushButton("Sil")
        delete_button.clicked.connect(self._on_delete)

        row = QHBoxLayout()
        row.addWidget(self.profile_name_edit, 1)
        row.addWidget(save_button)
        row2 = QHBoxLayout()
        row2.addWidget(apply_button)
        row2.addWidget(delete_button)
        row2.addStretch()
        hint = QLabel("Profil: bağlantı (baudrate), CCP (CRO/DTO/istasyon) ve A2L dosya yolu.")
        hint.setObjectName("mutedSmall")
        v.addWidget(self.profile_list, 1)
        v.addLayout(row)
        v.addLayout(row2)
        v.addWidget(hint)
        return card

    def _selected_profile_name(self):
        item = self.profile_list.currentItem()
        return item.text() if item else None

    def _on_save(self):
        name = self.profile_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self.window(), "İsim gerekli", "Kaydetmek için bir profil ismi girin.")
            return
        self.profile_save_requested.emit(name)

    def _on_apply(self):
        name = self._selected_profile_name()
        if not name:
            QMessageBox.warning(self.window(), "Profil seçin", "Önce listeden bir profil seçin.")
            return
        self.profile_apply_requested.emit(name)

    def _on_delete(self):
        name = self._selected_profile_name()
        if not name:
            return
        self.profile_delete_requested.emit(name)

    def set_profiles(self, names: list):
        self.profile_list.clear()
        for n in names:
            self.profile_list.addItem(QListWidgetItem(n))
