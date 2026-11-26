"""Proje yöneticisi (Modas: F7). Mevcut proje / workbase bilgisini tek yerde gösterir ve ilgili ayarlara götürür.

Salt okunur özet: A2L dosyası, proje/modül, iletişim donanımı ve protokolü, CCP durumu, rol. İşlemler MainWindow'daki
mevcut ekranları açar (A2L yükle, bağlantı, profiller) — yeni iş mantığı içermez.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)


class ProjectManagerDialog(QDialog):
    load_a2l_requested = Signal()
    connection_requested = Signal()
    settings_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Project Manager")
        self.setMinimumWidth(520)
        v = QVBoxLayout(self)
        title = QLabel("<b>Workbase information</b>")
        v.addWidget(title)
        self.form = QFormLayout()
        self.form.setLabelAlignment(self.form.labelAlignment())
        v.addLayout(self.form)
        self._labels: dict[str, QLabel] = {}
        row = QHBoxLayout()
        self.btn_a2l = QPushButton("A2L yükle…")
        self.btn_conn = QPushButton("Bağlantı (CAN / CCP)…")
        self.btn_settings = QPushButton("Ayarlar / Profiller…")
        for b in (self.btn_a2l, self.btn_conn, self.btn_settings):
            row.addWidget(b)
        v.addLayout(row)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)
        self.btn_a2l.clicked.connect(self.load_a2l_requested.emit)
        self.btn_conn.clicked.connect(self.connection_requested.emit)
        self.btn_settings.clicked.connect(self.settings_requested.emit)

    def set_info(self, info: dict):
        """``{başlık: değer}`` — sırayı korur; önceki satırlar yenilenir."""
        while self.form.rowCount():
            self.form.removeRow(0)
        self._labels.clear()
        for key, value in info.items():
            lab = QLabel(str(value) if value not in (None, "") else "—")
            lab.setWordWrap(True)
            lab.setTextInteractionFlags(lab.textInteractionFlags() | lab.textInteractionFlags().TextSelectableByMouse)
            self.form.addRow(f"{key}:", lab)
            self._labels[key] = lab

    def info_text(self) -> dict:
        return {k: v.text() for k, v in self._labels.items()}
