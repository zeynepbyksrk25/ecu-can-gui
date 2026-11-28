"""Modas veri seti pencereleri.

* :class:`DatasetChoiceDialog` — "Veri setini seç" (kılavuz §4 NOTICE): bağlanınca PC ve ECU veri setleri farklıysa
  kullanıcı hangisiyle devam edeceğini seçer. Hiçbir seçim kendiliğinden uygulanmaz; yazma yetkisi yoksa "PC verisini ECU'ya yaz" pasiftir.
* :class:`DiffListDialog` — WP ↔ RP fark listesi; seçilen etiketler RP değerine geri alınabilir.

Pencereler yalnızca seçimi bildirir; ECU'ya yazma / okuma MainWindow'daki mevcut güvenli yollarla yapılır.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from app import theme
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

WRITE_PC, READ_ECU, LATER = "write_pc", "read_ecu", "later"


def value_text(v) -> str:
    """Tablo hücresi için kısa metin: sayı olduğu gibi, tablo 'RxC tablo' olarak."""
    if isinstance(v, list):
        return f"{len(v)}×{len(v[0]) if v else 0} tablo"
    try:
        return f"{float(v):.9g}"
    except (TypeError, ValueError):
        return str(v)


def _table(headers: list, rows: list, multi: bool = False) -> QTableWidget:
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.ExtendedSelection if multi else QAbstractItemView.NoSelection)
    t.verticalHeader().setVisible(False)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)         # etiket / değer sütunları eşit genişlikte
    for r, row in enumerate(rows):
        for c, text in enumerate(row):
            it = QTableWidgetItem(text)
            it.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter if c == 0 else Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, c, it)
    return t


class DatasetChoiceDialog(QDialog):
    def __init__(self, diffs: list, can_write: bool, deny_reason: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle("Veri setini seç")
        self.setMinimumSize(560, 380)
        self.choice = LATER
        self.diffs = diffs
        v = QVBoxLayout(self)
        head = QLabel(f"<b>PC ve ECU veri setleri farklı</b> ({len(diffs)} etiket). Hangisiyle devam edilsin?<br>"
                      f"<span style='color:{theme.MUTED}'>Yalnızca çalışma alanındaki (worksheet) etiketler karşılaştırıldı.</span>")
        head.setWordWrap(True)
        v.addWidget(head)
        self.table = _table(["Etiket", "PC (kayıtlı)", "ECU"], [[d.name, value_text(d.pc), value_text(d.ecu)] for d in diffs])
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_write = QPushButton("PC verisini ECU'ya yaz")
        self.btn_write.setToolTip("PC'deki değerleri ECU RAM'ine yazar (yedek + geri okuma doğrulamasıyla)")
        self.btn_read = QPushButton("ECU'dan veri oku")
        self.btn_read.setToolTip("ECU'daki değerlerle devam et; PC veri seti ECU ile güncellenir")
        self.btn_later = QPushButton("Sonra karar ver")
        self.btn_later.setToolTip("Hiçbir şey yazılmaz / değişmez; fark Diff sayacında görünür kalır")
        if not can_write:
            self.btn_write.setEnabled(False)
            self.btn_write.setToolTip(deny_reason or "Yazma yetkisi yok")
        self.btn_write.clicked.connect(lambda: self._done(WRITE_PC))
        self.btn_read.clicked.connect(lambda: self._done(READ_ECU))
        self.btn_later.clicked.connect(lambda: self._done(LATER))
        for b in (self.btn_write, self.btn_read, self.btn_later):
            row.addWidget(b)
        v.addLayout(row)
        if not can_write and deny_reason:
            note = QLabel(deny_reason)
            note.setStyleSheet(f"color:{theme.DANGER};")
            note.setWordWrap(True)
            v.addWidget(note)

    def _done(self, choice: str):
        self.choice = choice
        self.accept()

    def reject(self):               # pencereyi kapatmak = Decide later (hiçbir şey yazılmaz)
        self.choice = LATER
        super().reject()


class DiffListDialog(QDialog):
    def __init__(self, rows: list, can_write: bool, deny_reason: str = "", parent=None,
                 headers: tuple = ("Etiket", "WP", "RP"), title: str = "Fark — WP ≠ RP",
                 action_text: str = "Revert selected (RP → WP)", intro: str | None = None):
        """``rows``: ``[(etiket, WP değeri, karşı değer), ...]`` (karşı değer: RP ya da dosya)."""
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumSize(520, 360)
        self.names = [r[0] for r in rows]
        v = QVBoxLayout(self)
        v.addWidget(QLabel(intro or (f"{len(rows)} etiketin WP (çalışma) ve RP (referans) değeri farklı."
                                     if rows else "WP ve RP aynı.")))
        self.table = _table(list(headers), [[n, value_text(w), value_text(r)] for n, w, r in rows], multi=True)
        v.addWidget(self.table, 1)
        row = QHBoxLayout()
        self.btn_revert = QPushButton(action_text)
        self.btn_revert.setToolTip("Seçili etiketleri karşı değere yazar (ECU RAM)")
        self.btn_revert.setEnabled(False)
        self.btn_close = QPushButton("Kapat")
        self.btn_close.clicked.connect(self.reject)
        self.btn_revert.clicked.connect(self.accept)
        self._can_write = can_write
        if not can_write:
            self.btn_revert.setToolTip(deny_reason or "Yazma yetkisi yok")
        self.table.itemSelectionChanged.connect(self._sync)
        row.addStretch(1)
        row.addWidget(self.btn_revert)
        row.addWidget(self.btn_close)
        v.addLayout(row)

    def _sync(self):
        self.btn_revert.setEnabled(self._can_write and bool(self.selected_names()))

    def selected_names(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.names[r] for r in rows]
