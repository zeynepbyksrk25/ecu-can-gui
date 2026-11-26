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
    QComboBox, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.change_tracker import format_delta

from app import theme
from app.ui.dash_widgets import make_card


class HistoryTab(QWidget):
    revert_requested = Signal(int)  # history.entries listesindeki index

    def __init__(self):
        super().__init__()
        self.history = None  # MainWindow tarafından paylaşılır (app.history.CalibrationHistory)

        box, body, _head = make_card("Kalibrasyon geçmişi (CCP RAM ve FLAŞ yazımları)", "trend")
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels(
            ["Zaman", "Tür", "Kullanıcı", "Rol", "Nesne", "Eski Değer", "Yeni Değer", "Değişim", "Yazma"]
        )
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(220)
        self.filter_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        self._shown: list[int] = []        # tablo satırı -> history.entries indeksi
        self.table.horizontalHeader().setStretchLastSection(True)

        self.revert_button = QPushButton("Seçili kaydın ESKİ değerine geri yaz")
        self.revert_button.clicked.connect(self._on_revert)

        layout = QVBoxLayout()
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Parametre:"))
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch()
        layout.addLayout(filter_row)
        layout.addWidget(self.table)
        row = QHBoxLayout()
        row.addWidget(self.revert_button)
        row.addStretch()
        layout.addLayout(row)
        body.addLayout(layout, 1)

        outer = QVBoxLayout(self)
        outer.addWidget(box)

    def _sync_filter(self, names: list[str]):
        current = self.filter_combo.currentData()
        self.filter_combo.blockSignals(True)
        self.filter_combo.clear()
        self.filter_combo.addItem("Tümü", None)
        for n in names:
            self.filter_combo.addItem(n, n)
        idx = self.filter_combo.findData(current)
        self.filter_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.filter_combo.blockSignals(False)

    def refresh(self):
        if self.history is None:
            return
        entries = self.history.entries
        names = sorted({e.object_name for e in entries})
        known = [self.filter_combo.itemData(i) for i in range(1, self.filter_combo.count())]
        if known != names:
            self._sync_filter(names)
        only = self.filter_combo.currentData()
        self._shown = [i for i, e in enumerate(entries) if only is None or e.object_name == only]
        self.table.setRowCount(len(self._shown))
        for row, idx in enumerate(self._shown):
            e = entries[idx]
            self.table.setItem(row, 0, QTableWidgetItem(time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(e.timestamp))))
            kind_item = QTableWidgetItem("FLAŞ (kalıcı)" if e.persistent else "RAM (geçici)")
            if e.persistent:
                kind_item.setForeground(QColor(theme.WARN_INK))
            self.table.setItem(row, 1, kind_item)
            self.table.setItem(row, 2, QTableWidgetItem(e.user))
            self.table.setItem(row, 3, QTableWidgetItem(e.role))
            self.table.setItem(row, 4, QTableWidgetItem(e.object_name))
            detail = getattr(e, "detail", "")
            if detail:
                self.table.setItem(row, 5, QTableWidgetItem("-"))
                self.table.setItem(row, 6, QTableWidgetItem(detail))
                self.table.setItem(row, 7, QTableWidgetItem(""))
            else:
                old_text = "-" if e.old_value is None else f"{e.old_value:g} {e.unit}".strip()
                self.table.setItem(row, 5, QTableWidgetItem(old_text))
                self.table.setItem(row, 6, QTableWidgetItem(f"{e.new_value:g} {e.unit}".strip()))
                delta = QTableWidgetItem(format_delta(e.old_value, e.new_value, e.unit))
                delta.setForeground(QColor("#C62828"))
                self.table.setItem(row, 7, delta)
            ok_item = QTableWidgetItem("ECU'ya yazıldı" if e.write_ok else "BAŞARISIZ (uygulanmadı)")
            if not e.write_ok:
                ok_item.setForeground(QColor(theme.DANGER))
            self.table.setItem(row, 8, ok_item)
        self.table.scrollToBottom()

    def _on_revert(self):
        row = self.table.currentRow()
        if row < 0 or row >= len(self._shown):
            return
        entry = self.history.entries[self._shown[row]]
        if not entry.write_ok:
            return                          # başarısız yazma geri alınacak bir şey değildir
        self.revert_requested.emit(self._shown[row])
