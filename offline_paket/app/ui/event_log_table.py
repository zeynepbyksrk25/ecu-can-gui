"""Olay günlüğü tablosu: ``app.eventlog.EventLog`` girişlerini TEK yerde gösterir.

Eskiden Hata günlüğü (yalnızca ``HATA``) ve Test Oturumu günlüğü (tümü) aynı 4 sütunlu tabloyu
ayrı ayrı kuruyordu; burada tek bileşen ve "Tümü | Yalnız hatalar" süzgeci vardır.
"""

import time

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

ERROR_CATEGORY = "HATA"


class EventLogTable(QWidget):
    def __init__(self):
        super().__init__()
        self._entries: list = []
        self._errors_only = False

        self.btn_all = QPushButton("Tümü")
        self.btn_errors = QPushButton("Yalnız hatalar")
        for b in (self.btn_all, self.btn_errors):
            b.setCheckable(True)
            b.setProperty("seg", True)       # seçili olan belirgin (dark_theme: QPushButton[seg]:checked)
        self.btn_all.setChecked(True)
        group = QButtonGroup(self)
        group.setExclusive(True)
        group.addButton(self.btn_all)
        group.addButton(self.btn_errors)
        self.btn_all.clicked.connect(lambda: self.set_errors_only(False))
        self.btn_errors.clicked.connect(lambda: self.set_errors_only(True))
        self.count_label = QLabel("")
        self.count_label.setObjectName("mutedSmall")

        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(self.btn_all)
        bar.addWidget(self.btn_errors)
        bar.addWidget(self.count_label)
        bar.addStretch(1)

        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Zaman", "Kullanıcı / Rol", "Kategori", "Mesaj"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setColumnWidth(0, 96)
        self.table.setColumnWidth(1, 190)
        self.table.setColumnWidth(2, 140)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addLayout(bar)
        lay.addWidget(self.table, 1)

    @property
    def error_count(self) -> int:
        return sum(1 for e in self._entries if e.category == ERROR_CATEGORY)

    def set_errors_only(self, on: bool):
        self._errors_only = bool(on)
        self.btn_errors.setChecked(self._errors_only)
        self.btn_all.setChecked(not self._errors_only)
        self._render()

    def set_entries(self, entries: list):
        """entries: app.eventlog.EventEntry listesi (tümü; süzgeç burada uygulanır)."""
        self._entries = list(entries)
        self._render()

    def _render(self):
        shown = [e for e in self._entries if not self._errors_only or e.category == ERROR_CATEGORY]
        self.table.setRowCount(len(shown))
        for row, e in enumerate(shown):
            self.table.setItem(row, 0, QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(e.timestamp))))
            self.table.setItem(row, 1, QTableWidgetItem(f"{e.user} / {e.role}"))
            cat = QTableWidgetItem(e.category)
            if e.category == ERROR_CATEGORY:
                cat.setForeground(QColor("#C22A1D"))
            self.table.setItem(row, 2, cat)
            self.table.setItem(row, 3, QTableWidgetItem(e.message))
        self.count_label.setText(f"{self.error_count} hata · {len(self._entries)} olay")
        self.table.scrollToBottom()
