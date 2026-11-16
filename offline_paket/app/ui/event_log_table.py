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

from app import theme

ERROR_CATEGORY = "HATA"


class EventLogTable(QWidget):
    def __init__(self):
        super().__init__()
        self._entries: list = []
        self._error_count = 0
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
        return self._error_count

    def set_errors_only(self, on: bool):
        self._errors_only = bool(on)
        self.btn_errors.setChecked(self._errors_only)
        self.btn_all.setChecked(not self._errors_only)
        self._render()

    def _shown(self, e) -> bool:
        return not self._errors_only or e.category == ERROR_CATEGORY

    def set_entries(self, entries: list):
        """entries: app.eventlog.EventEntry listesi (tümü; süzgeç burada uygulanır).

        Her olayda çağrılır; bu yüzden tablo baştan kurulmaz. Yeni liste eskisinin devamıysa (sona
        eklenmiş, belki baştan kırpılmış) yalnızca fark uygulanır: baştan düşen satırlar silinir, yeni
        olaylar sona eklenir. Liste başka bir listeyse tablo baştan çizilir."""
        old = self._entries
        new = list(entries)
        if not old or not new:
            self._entries = new
            self._render()
            return
        # Eski listenin son girişini yeni listede (sondan başlayarak) bul.
        last = old[-1]
        j = next((i for i in range(len(new) - 1, -1, -1) if new[i] is last), -1)
        dropped = len(old) - (j + 1)                  # baştan kırpılan giriş sayısı
        if j < 0 or dropped < 0 or new[0] is not old[dropped]:
            self._entries = new
            self._render()
            return
        removed, added = old[:dropped], new[j + 1:]
        self._entries = new
        if not removed and not added:
            return
        at_bottom = self._at_bottom()
        for e in removed:
            if e.category == ERROR_CATEGORY:
                self._error_count -= 1
        n_remove = sum(1 for e in removed if self._shown(e))
        if n_remove:
            self.table.model().removeRows(0, n_remove)
        for e in added:
            if e.category == ERROR_CATEGORY:
                self._error_count += 1
            if self._shown(e):
                row = self.table.rowCount()
                self.table.insertRow(row)
                self._fill_row(row, e)
        self._update_count()
        if at_bottom:
            self.table.scrollToBottom()

    def _at_bottom(self) -> bool:
        """Kullanıcı eski kayıtlara bakmak için yukarı kaydırdıysa yeni olay görünümü sürüklemesin."""
        bar = self.table.verticalScrollBar()
        return bar.value() >= bar.maximum() - 2

    def _fill_row(self, row: int, e):
        self.table.setItem(row, 0, QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(e.timestamp))))
        self.table.setItem(row, 1, QTableWidgetItem(f"{e.user} / {e.role}"))
        cat = QTableWidgetItem(e.category)
        if e.category == ERROR_CATEGORY:
            cat.setForeground(QColor(theme.DANGER))
        self.table.setItem(row, 2, cat)
        self.table.setItem(row, 3, QTableWidgetItem(e.message))

    def _update_count(self):
        self.count_label.setText(f"{self._error_count} hata · {len(self._entries)} olay")

    def _render(self):
        """Tabloyu baştan çizer (süzgeç değişti ya da liste değişti)."""
        self._error_count = sum(1 for e in self._entries if e.category == ERROR_CATEGORY)
        shown = [e for e in self._entries if self._shown(e)]
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(shown))
            for row, e in enumerate(shown):
                self._fill_row(row, e)
        finally:
            self.table.setUpdatesEnabled(True)
        self._update_count()
        self.table.scrollToBottom()
