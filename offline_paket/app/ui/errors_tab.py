"""Hatalar sekmesi: uygulama genelindeki hataları TEK bir yerde toplar —
CAN bağlantı/donanım hataları (bus-off vb.), CCP hataları/zaman aşımları,
kalibrasyon yazma hataları, DIAG_SERVICE hataları. Kaynağı ne olursa
olsun her hata zaten app.eventlog.EventLog'a "HATA" kategorisiyle
düşer (bkz. MainWindow._log_event); bu sekme sadece o günlüğün hata
alt kümesini canlı gösterir — ayrı bir hata izleme mekanizması icat
etmez.

CAN bağlantısının GERÇEK zamanlı sağlık durumu (bkz. app/can_worker.py
CanConnection.is_healthy) da burada, tek bakışta görünür.
"""

import time

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)


class ErrorsTab(QWidget):
    clear_requested = Signal()

    def __init__(self):
        super().__init__()

        health_box = QGroupBox("CAN bağlantı durumu")
        self.health_label = QLabel("Bağlı değil")
        health_row = QHBoxLayout()
        health_row.addWidget(self.health_label)
        health_row.addStretch()
        health_box.setLayout(health_row)

        errors_box = QGroupBox("Hata günlüğü")
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Zaman", "Kullanıcı/Rol", "Kategori", "Mesaj"])
        self.table.horizontalHeader().setStretchLastSection(True)

        self.clear_button = QPushButton("Günlüğü temizle")
        self.clear_button.clicked.connect(self.clear_requested.emit)

        errors_layout = QVBoxLayout()
        errors_layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(self.clear_button)
        row.addStretch()
        errors_layout.addLayout(row)
        errors_box.setLayout(errors_layout)

        outer = QVBoxLayout(self)
        outer.addWidget(health_box)
        outer.addWidget(errors_box)

    # ---- MainWindow'un çağırdığı erişimciler -------------------------
    def set_health(self, ok: bool, message: str):
        color = "#3ecf8e" if ok else "#e5484d"
        self.health_label.setText(f"● {message}")
        self.health_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    def set_errors(self, entries: list):
        """entries: app.eventlog.EventEntry listesi (yalnızca kategori=='HATA' olanlar)."""
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(
                time.strftime("%H:%M:%S", time.localtime(e.timestamp))
            ))
            self.table.setItem(row, 1, QTableWidgetItem(f"{e.user} / {e.role}"))
            cat_item = QTableWidgetItem(e.category)
            cat_item.setForeground(QColor("#e5484d"))
            self.table.setItem(row, 2, cat_item)
            self.table.setItem(row, 3, QTableWidgetItem(e.message))
        self.table.scrollToBottom()
