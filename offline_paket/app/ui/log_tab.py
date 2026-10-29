import os
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QWidget,
)


from app.paths import data_dir, data_path


class LogTab(QWidget):
    start_requested = Signal(str)   # directory
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self._file_path = ""
        self._size_text = ""

        self.dir_edit = QLineEdit(data_path("can_loglari"))
        browse_button = QPushButton("Klasör seç...")
        browse_button.clicked.connect(self._browse)

        self.start_button = QPushButton("Kaydı başlat")
        self.stop_button = QPushButton("Kaydı durdur")
        self.stop_button.setEnabled(False)
        self.start_button.clicked.connect(lambda: self.start_requested.emit(self.dir_edit.text()))
        self.stop_button.clicked.connect(self.stop_requested.emit)

        self.status_label = QLabel("Kayıt yapılmıyor.")
        self.count_label = QLabel("Kaydedilen mesaj: 0")

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("Kayıt klasörü:"))
        dir_row.addWidget(self.dir_edit, stretch=1)
        dir_row.addWidget(browse_button)

        button_row = QHBoxLayout()
        button_row.addWidget(self.start_button)
        button_row.addWidget(self.stop_button)
        button_row.addStretch()

        open_button = QPushButton("Klasörü aç")
        open_button.clicked.connect(self._open_dir)
        dir_row.addWidget(open_button)

        layout = QVBoxLayout(self)
        layout.addLayout(dir_row)
        layout.addLayout(button_row)
        layout.addWidget(self.status_label)
        layout.addWidget(self.count_label)
        layout.addStretch()

    def _browse(self):
        directory = QFileDialog.getExistingDirectory(self, "Kayıt klasörü seç", self.dir_edit.text())
        if directory:
            self.dir_edit.setText(directory)

    def _open_dir(self):
        path = self.dir_edit.text().strip() or data_dir()
        if not Path(path).exists():
            path = data_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def set_active(self, active: bool, file_path: str = ""):
        self.start_button.setEnabled(not active)
        self.stop_button.setEnabled(active)
        self.dir_edit.setEnabled(not active)
        self._file_path = file_path if active else ""
        self._size_text = ""
        self.status_label.setText(f"Kayıt ediliyor: {file_path}" if active else "Kayıt yapılmıyor.")

    def set_count(self, count: int):
        text = f"Kaydedilen mesaj: {count}" + (self._size_text if self._file_path else "")
        if self._file_path and count % 100 == 0:
            try:
                self._size_text = f"   (dosya boyutu: {os.path.getsize(self._file_path) / 1024:.1f} KB)"
            except OSError:
                pass
        self.count_label.setText(text)
