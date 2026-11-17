"""Kompakt CAN kayıt denetimi (İzleme kartının başlığında): tek "Kayıt" düğmesi, sayaç,
klasör seçimi ve açma. Hem RX hem TX mesajları kaydedilir (bkz. MainWindow._on_monitor_frame)."""
import os
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton, QWidget,
)

from app.paths import data_dir, data_path
from app.ui.dash_widgets import IconButton


class LogTab(QWidget):
    start_requested = Signal(str)   # directory
    stop_requested = Signal()

    def __init__(self):
        super().__init__()
        self._file_path = ""
        self._size_text = ""
        self._active = False

        self.dir_edit = QLineEdit(data_path("can_loglari"))   # görünmez; seçili klasörü tutar
        self.dir_edit.setVisible(False)

        self.record_button = QPushButton("● Kayıt")
        self.record_button.setProperty("compact", True)
        self.record_button.setProperty("tone", "rec")
        self.record_button.setCheckable(True)
        self.record_button.setToolTip("CAN trafiğini (RX ve TX) CSV dosyasına kaydet")
        self.record_button.clicked.connect(self._on_record_clicked)

        self.count_label = QLabel("Kayıt yok")
        self.count_label.setObjectName("chipDim")

        self.folder_button = IconButton("settings", 26)
        menu = QMenu(self.folder_button)
        menu.addAction("Kayıt klasörünü seç…", self._browse)
        menu.addAction("Klasörü aç", self._open_dir)
        self._excel_action = menu.addAction("Durdurunca Excel (.xlsx) dosyası da oluştur")
        self._excel_action.setCheckable(True)
        self._excel_action.setChecked(True)
        self.folder_button.setMenu(menu)
        self.folder_button.setToolTip("Kayıt klasörü")

        # eski API uyumu
        self.start_button = self.record_button
        self.stop_button = self.record_button
        self.status_label = self.count_label

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addWidget(self.record_button)
        lay.addWidget(self.count_label)
        lay.addWidget(self.folder_button)

    def excel_on_stop(self) -> bool:
        """Kayıt durunca CSV'ye ek olarak Excel dosyası da üretilsin mi (varsayılan: evet)."""
        return self._excel_action.isChecked()

    def _on_record_clicked(self):
        if self._active:
            self.stop_requested.emit()
        else:
            self.start_requested.emit(self.dir_edit.text())
        # gerçek durumu MainWindow set_active ile bildirir
        self.record_button.setChecked(self._active)

    def _browse(self):
        directory = QFileDialog.getExistingDirectory(self.window(), "Kayıt klasörü seç", self.dir_edit.text())
        if directory:
            self.dir_edit.setText(directory)

    def _open_dir(self):
        path = self.dir_edit.text().strip() or data_dir()
        if not Path(path).exists():
            path = data_dir()
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    def set_active(self, active: bool, file_path: str = ""):
        self._active = active
        self.record_button.setChecked(active)
        self.record_button.setText("■ Kaydı durdur" if active else "● Kayıt")
        self.folder_button.setEnabled(not active)
        self._file_path = file_path if active else ""
        self._size_text = ""
        self.count_label.setToolTip(f"Kayıt dosyası: {file_path}" if active else "")
        self.count_label.setText("0 mesaj" if active else "Kayıt yok")

    def set_count(self, count: int):
        if self._file_path and count % 100 == 0:
            try:
                self._size_text = f" · {os.path.getsize(self._file_path) / 1024:.0f} KB"
            except OSError:
                pass
        self.count_label.setText(f"{count} mesaj" + (self._size_text if self._file_path else ""))
