"""Kalibrasyon Geçmişi sekmesi (SRS Faz 5, genişletilmiş): her CCP
Characteristic yazımının (RAM veya FLAŞ) eski/yeni değerini, kullanıcı/
rol, zaman ve tür (RAM/FLAŞ) bilgisiyle listeler; seçili bir kaydı eski
değerine geri yazmaya izin verir. RAM kayıtları RAM'e, FLAŞ kayıtları
(kalıcı yazım sonrası bile) tekrar FLAŞ'a geri yazılır — hangi yolun
kullanılacağına MainWindow, kaydın `persistent` alanına bakarak karar
verir. Harita/grid geri alma burada değil, Harita Editörü'ndeki Geri
Al/Yinele ile yapılır.
"""

import time

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)


class HistoryTab(QWidget):
    revert_requested = Signal(int)  # history.entries listesindeki index

    def __init__(self):
        super().__init__()
        self.history = None  # MainWindow tarafından paylaşılır (app.history.CalibrationHistory)

        box = QGroupBox("Kalibrasyon geçmişi (CCP RAM ve FLAŞ yazımları)")
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels(
            ["Zaman", "Tür", "Kullanıcı", "Rol", "Nesne", "Eski Değer", "Yeni Değer"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)

        self.revert_button = QPushButton("Seçili kaydın ESKİ değerine geri yaz")
        self.revert_button.clicked.connect(self._on_revert)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(self.revert_button)
        row.addStretch()
        layout.addLayout(row)
        box.setLayout(layout)

        outer = QVBoxLayout(self)
        outer.addWidget(box)

    def refresh(self):
        if self.history is None:
            return
        entries = self.history.entries
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(e.timestamp))))
            kind_item = QTableWidgetItem("FLAŞ (kalıcı)" if e.persistent else "RAM (geçici)")
            if e.persistent:
                kind_item.setForeground(QColor("#9A6208"))
            self.table.setItem(row, 1, kind_item)
            self.table.setItem(row, 2, QTableWidgetItem(e.user))
            self.table.setItem(row, 3, QTableWidgetItem(e.role))
            self.table.setItem(row, 4, QTableWidgetItem(e.object_name))
            detail = getattr(e, "detail", "")
            if detail:
                self.table.setItem(row, 5, QTableWidgetItem("-"))
                self.table.setItem(row, 6, QTableWidgetItem(detail))
            else:
                old_text = "-" if e.old_value is None else f"{e.old_value:g} {e.unit}".strip()
                self.table.setItem(row, 5, QTableWidgetItem(old_text))
                self.table.setItem(row, 6, QTableWidgetItem(f"{e.new_value:g} {e.unit}".strip()))
        self.table.scrollToBottom()

    def _on_revert(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.revert_requested.emit(row)
