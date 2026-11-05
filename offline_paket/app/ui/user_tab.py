"""Kullanıcı / Profil sekmesi (SRS Faz 5): rol seçimi (Operatör/Mühendis/
Yönetici) ve bağlantı+CCP ayarlarını isimli profiller olarak kaydedip
yeniden uygulama.

Bu bir kimlik doğrulama (authentication) sistemi DEĞİLDİR — bkz.
app/user_roles.py docstring'i.
"""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
    QWidget,
)

from app.user_roles import Role


class UserTab(QWidget):
    role_applied = Signal(str, str)          # kullanıcı adı, rol (Role.value)
    profile_apply_requested = Signal(str)    # profil ismi
    profile_save_requested = Signal(str)     # profil ismi (mevcut form alanlarından)
    profile_delete_requested = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_user_group())
        layout.addWidget(self._build_profile_group())
        layout.addStretch()

    def _build_user_group(self) -> QGroupBox:
        box = QGroupBox("Kullanıcı")
        self.user_edit = QLineEdit()
        self.user_edit.setPlaceholderText("Kullanıcı ismi")
        self.role_combo = QComboBox()
        for role in Role:
            self.role_combo.addItem(role.value, role)

        apply_button = QPushButton("Rolü Uygula")
        apply_button.clicked.connect(self._on_apply_role)

        self.current_label = QLabel("Aktif: - (Operatör)")
        self.current_label.setStyleSheet("font-weight: bold;")

        form = QFormLayout()
        form.addRow("Kullanıcı ismi:", self.user_edit)
        form.addRow("Rol:", self.role_combo)

        row = QHBoxLayout()
        row.addWidget(apply_button)
        row.addWidget(self.current_label)
        row.addStretch()

        outer = QVBoxLayout()
        outer.addLayout(form)
        outer.addLayout(row)
        box.setLayout(outer)
        return box

    _RANK = {Role.OPERATOR: 0, Role.ENGINEER: 1, Role.ADMIN: 2}

    def _on_apply_role(self):
        name = self.user_edit.text().strip() or "bilinmeyen"
        role: Role = self.role_combo.currentData()
        current = getattr(self, "_current_role", Role.OPERATOR)
        # Yetki YÜKSELTME bilinçli bir adım olmalı (combo'da kazara seçim).
        if self._RANK[role] > self._RANK[current]:
            extra = ("RAM'e kalibrasyon, harita yazma, ham tanı komutu ve eyleyici override"
                     if role == Role.ENGINEER else
                     "yukarıdakilere ek olarak KALICI (flaş) yazma")
            ans = QMessageBox.question(
                self, "Yetki yükseltme",
                f"'{role.value}' rolüne geçiliyor. Bu rol {extra} işlemlerini açar ve ECU'ya "
                f"zarar verebilir. İşlemler denetim günlüğüne '{name}' adıyla kaydedilir.\n\n"
                f"Devam edilsin mi?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                return
        self._current_role = role
        self.role_applied.emit(name, role.value)
        self.current_label.setText(f"Aktif: {name} ({role.value})")

    def _build_profile_group(self) -> QGroupBox:
        box = QGroupBox("Profiller")
        self.profile_list = QListWidget()
        self.profile_name_edit = QLineEdit()
        self.profile_name_edit.setPlaceholderText("Yeni profil ismi")

        save_button = QPushButton("Mevcut ayarları profil olarak kaydet")
        save_button.clicked.connect(self._on_save)
        apply_button = QPushButton("Seçili profili uygula")
        apply_button.clicked.connect(self._on_apply)
        delete_button = QPushButton("Sil")
        delete_button.clicked.connect(self._on_delete)

        row = QHBoxLayout()
        row.addWidget(self.profile_name_edit)
        row.addWidget(save_button)

        row2 = QHBoxLayout()
        row2.addWidget(apply_button)
        row2.addWidget(delete_button)
        row2.addStretch()

        layout = QVBoxLayout()
        layout.addWidget(self.profile_list)
        layout.addLayout(row)
        layout.addLayout(row2)
        box.setLayout(layout)
        return box

    def _selected_profile_name(self):
        item = self.profile_list.currentItem()
        return item.text() if item else None

    def _on_save(self):
        name = self.profile_name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "İsim gerekli", "Kaydetmek için bir profil ismi girin.")
            return
        self.profile_save_requested.emit(name)

    def _on_apply(self):
        name = self._selected_profile_name()
        if not name:
            QMessageBox.warning(self, "Profil seçin", "Önce listeden bir profil seçin.")
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
