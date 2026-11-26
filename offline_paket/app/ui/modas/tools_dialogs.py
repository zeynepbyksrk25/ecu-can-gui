"""Modas araç pencereleri: Parameter file manager ve Macro manager.

Pencereler yalnızca düzenleme / seçim arayüzüdür; dosya yazma, ECU'ya yazma ve macro oynatma MainWindow'daki
(``mainwin/modas_tools.py``) güvenli yollardan yapılır; pencere bunlara geri çağrı (callback) ile bağlanır.
"""
from __future__ import annotations

import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from app import theme
from app.modas_macros import describe


class ParameterFilesDialog(QDialog):
    """Parameter file manager: projenin parametre dosyalarını listeler; WP'yi yeni dosya olarak kaydeder, dosyayı WP ile
    karşılaştırıp uygular, siler. ``on_save(ad)``, ``on_apply(yol)``, ``on_delete(ad)`` MainWindow'a bağlanır."""

    def __init__(self, folder, on_save, on_apply, on_delete, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Parameter file manager")
        self.setMinimumSize(520, 380)
        self.folder = folder
        self._on_save, self._on_apply, self._on_delete = on_save, on_apply, on_delete
        v = QVBoxLayout(self)
        self.info = QLabel(f"Klasör: {folder.folder}")
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.info)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.itemSelectionChanged.connect(self._sync)
        self.list.itemDoubleClicked.connect(lambda *_: self._apply())
        v.addWidget(self.list, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        row = QHBoxLayout()
        self.btn_save = QPushButton("Save WP as…")
        self.btn_save.setToolTip("Worksheet'teki ayar değerlerini (WP) yeni bir parametre dosyası olarak kaydet")
        self.btn_apply = QPushButton("Compare / Apply…")
        self.btn_apply.setToolTip("Seçili dosyayı WP ile karşılaştır; seçtiğin farkları ECU RAM'ine yaz")
        self.btn_delete = QPushButton("Delete")
        self.btn_close = QPushButton("Close")
        self.btn_save.clicked.connect(self._save)
        self.btn_apply.clicked.connect(self._apply)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_close.clicked.connect(self.reject)
        for b in (self.btn_save, self.btn_apply, self.btn_delete):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        v.addLayout(row)
        self.refresh()

    def refresh(self):
        keep = self.selected()
        self.list.clear()
        for name, path, mtime in self.folder.list():
            it = QListWidgetItem(f"{name}    ({time.strftime('%Y-%m-%d %H:%M', time.localtime(mtime))})")
            it.setData(Qt.UserRole, (name, path))
            self.list.addItem(it)
            if keep is not None and keep[0] == name:
                self.list.setCurrentItem(it)              # yenilemede seçim korunur
        self._sync()

    def selected(self):
        items = self.list.selectedItems()
        return items[0].data(Qt.UserRole) if items else None

    def _sync(self):
        has = self.selected() is not None
        self.btn_apply.setEnabled(has)
        self.btn_delete.setEnabled(has)

    def _msg(self, text: str, error: bool = False):
        self.status.setStyleSheet(f"color:{theme.DANGER};" if error else "")
        self.status.setText(text)

    def _save(self):
        res = self._on_save()                          # (ok, mesaj) döner; ad sorma MainWindow'da
        if res:
            self._msg(res[1], not res[0])
        self.refresh()

    def _apply(self):
        sel = self.selected()
        if sel is not None:
            res = self._on_apply(sel[1])
            if res:
                self._msg(res[1], not res[0])

    def _delete(self):
        sel = self.selected()
        if sel is None:
            return
        res = self._on_delete(sel[0])
        if res:
            self._msg(res[1], not res[0])
        self.refresh()


class MacroDialog(QDialog):
    """Macro manager (kalıcı, kalıcı-olmayan pencere): kayıtlı macro'ları listeler, kaydı başlatıp bitirir, oynatır, siler.

    Kayıt sürerken pencere açık kalır (worksheet'te çalışabilmen için); ``Stop`` macro'yu adlandırıp kaydeder."""

    def __init__(self, store, recorder, on_record_toggle, on_play, on_delete, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Macro manager")
        self.setMinimumSize(520, 420)
        self.setWindowFlag(Qt.Tool, True)
        self.store, self.recorder = store, recorder
        self._on_record_toggle, self._on_play, self._on_delete = on_record_toggle, on_play, on_delete
        v = QVBoxLayout(self)
        self.info = QLabel("Kayıt sırasında yaptığın başarılı yazımlar (değer, tablo, test girişi) macro'ya eklenir.")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.list = QListWidget()
        self.list.itemSelectionChanged.connect(self._sync)
        v.addWidget(QLabel("Kayıtlı macro'lar"))
        v.addWidget(self.list, 1)
        v.addWidget(QLabel("Adımlar"))
        self.steps = QListWidget()
        self.steps.setSelectionMode(QAbstractItemView.NoSelection)
        v.addWidget(self.steps, 1)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        v.addWidget(self.status)
        row = QHBoxLayout()
        self.btn_record = QPushButton("● Record")
        self.btn_play = QPushButton("▶ Play")
        self.btn_delete = QPushButton("Delete")
        self.btn_close = QPushButton("Close")
        self.btn_record.clicked.connect(self._record)
        self.btn_play.clicked.connect(self._play)
        self.btn_delete.clicked.connect(self._delete)
        self.btn_close.clicked.connect(self.close)
        for b in (self.btn_record, self.btn_play, self.btn_delete):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(self.btn_close)
        v.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._live)
        self._timer.start()
        self.refresh()

    def refresh(self):
        keep = self.selected()
        self.list.clear()
        for n in self.store.names():
            self.list.addItem(n)
            if n == keep:
                self.list.setCurrentRow(self.list.count() - 1)
        self._sync()

    def selected(self):
        items = self.list.selectedItems()
        return items[0].text() if items else None

    def _msg(self, text: str, error: bool = False):
        self.status.setStyleSheet(f"color:{theme.DANGER};" if error else "")
        self.status.setText(text)

    def _sync(self):
        rec = self.recorder.active
        has = self.selected() is not None
        self.btn_record.setText("■ Stop && save" if rec else "● Record")
        self.btn_play.setEnabled(has and not rec)
        self.btn_delete.setEnabled(has and not rec)
        self.list.setEnabled(not rec)
        if rec:
            self._show_steps(self.recorder.steps, live=True)
        elif has:
            try:
                self._show_steps(self.store.load(self.selected()))
            except Exception as exc:  # noqa: BLE001 - bozuk macro listede hata olarak görünür
                self.steps.clear()
                self._msg(str(exc), True)
        else:
            self.steps.clear()

    def _show_steps(self, steps: list, live: bool = False):
        self.steps.clear()
        for i, s in enumerate(steps, 1):
            self.steps.addItem(f"{i}. {describe(s)}")
        if live:
            self.status.setStyleSheet(f"color:{theme.DANGER};")
            self.status.setText(f"● Kayıt sürüyor: {len(steps)} adım")

    def _live(self):
        if self.recorder.active and self.isVisible():
            self._show_steps(self.recorder.steps, live=True)

    def _record(self):
        res = self._on_record_toggle()
        if res:
            self._msg(res[1], not res[0])
        self.refresh()

    def _play(self):
        name = self.selected()
        if name:
            res = self._on_play(name)
            if res:
                self._msg(res[1], not res[0])

    def _delete(self):
        name = self.selected()
        if name:
            res = self._on_delete(name)
            if res:
                self._msg(res[1], not res[0])
            self.refresh()

    def closeEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)
