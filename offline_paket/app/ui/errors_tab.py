"""Hatalar: uygulama genelindeki hataları TEK bir yerde toplar — CAN bağlantı/donanım hataları (bus-off vb.),
CCP hataları/zaman aşımları, kalibrasyon yazma hataları, DIAG_SERVICE hataları. Kaynağı ne olursa olsun her hata
zaten app.eventlog.EventLog'a "HATA" kategorisiyle düşer (bkz. MainWindow._log_event); bu bileşen o günlüğün
hata alt kümesini canlı gösterir. CAN bağlantısının GERÇEK zamanlı sağlık durumu da burada, tek bakışta görünür.
Koyu tema: "CAN bağlantı durumu" ve "Hata günlüğü" kartları."""

import time

from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.ui.dash_widgets import make_card


class ErrorsTab(QWidget):
    clear_requested = Signal()

    def __init__(self):
        super().__init__()
        health_card, hv, _h = make_card("CAN bağlantı durumu", "plane")
        self.health_label = QLabel("● Bağlı değil")
        self.health_label.setObjectName("chipBad")
        self.health_label.setWordWrap(True)
        hv.addWidget(self.health_label)

        errors_card, ev, head = make_card("Hata günlüğü", "warn")
        self.clear_button = QPushButton("Günlüğü temizle")
        self.clear_button.setProperty("compact", True)
        self.clear_button.clicked.connect(self.clear_requested.emit)
        head.addWidget(self.clear_button)
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Zaman", "Kullanıcı/Rol", "Kategori", "Mesaj"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        ev.addWidget(self.table, 1)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(health_card)
        outer.addWidget(errors_card, 1)

    # ---- MainWindow'un çağırdığı erişimciler -------------------------
    def set_health(self, ok: bool, message: str):
        self.health_label.setText(f"● {message}")
        self.health_label.setObjectName("chipGreen" if ok else "chipBad")
        self.health_label.style().unpolish(self.health_label)
        self.health_label.style().polish(self.health_label)

    def set_errors(self, entries: list):
        """entries: app.eventlog.EventEntry listesi (yalnızca kategori=='HATA' olanlar)."""
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(e.timestamp))))
            self.table.setItem(row, 1, QTableWidgetItem(f"{e.user} / {e.role}"))
            cat_item = QTableWidgetItem(e.category)
            cat_item.setForeground(QColor("#ff9a9a"))
            self.table.setItem(row, 2, cat_item)
            self.table.setItem(row, 3, QTableWidgetItem(e.message))
        self.table.setColumnWidth(0, 80)
        self.table.setColumnWidth(1, 140)
        self.table.setColumnWidth(2, 90)
        self.table.scrollToBottom()
