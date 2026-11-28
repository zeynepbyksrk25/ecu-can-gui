"""Eyleyiciler çalışma sayfası penceresi: kilit (anahtar _sw) + değer kutusu.

Pencere YALNIZCA bir yansımadır: kilit / gönder istekleri sinyalle ana pencereye gider; orada Test Tezgâhı sayfasının
mevcut mantığı (eşleşme kontrolü, oturum onayı, ECU/CAN yazımı, bağlantı kopunca bırakma) çalışır. Durum tek yerdedir
(DashboardTab); bu pencere ``state_provider`` ile periyodik okur. ECU'ya doğrudan hiçbir şey yazmaz.
"""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import QGridLayout, QLabel, QLineEdit, QWidget

from app import theme
from app.dashboard_config import EYLEYICI_KEYS
from app.ui.dash_widgets import LockButton
from app.ui.dashboard_tab import ACTUATOR_SHORT
from app.ui.modas.windows import ModasSub

TITLE = "Eyleyiciler"


class ActuatorWindow(ModasSub):
    lock_requested = Signal(str, bool)     # (anahtar, kilidi aç?)
    submit_requested = Signal(str, str)    # (anahtar, kutudaki metin)

    def __init__(self, state_provider):
        """``state_provider()``: ``{anahtar: kilit_açık_mı}``. Satırlar Test Tezgâhı'ndaki eyleyicilerle aynıdır."""
        rows = [(k, ACTUATOR_SHORT[k]) for k in EYLEYICI_KEYS]
        super().__init__(TITLE, theme.WARN_INK)
        self._provider = state_provider
        self.locks: dict = {}
        self.boxes: dict = {}
        body = QWidget()
        body.setObjectName("modasWinBody")
        grid = QGridLayout(body)
        grid.setContentsMargins(6, 4, 6, 4)
        grid.setHorizontalSpacing(8)
        for c, text in enumerate(("Eyleyici", "Komut", "Manuel")):
            h = QLabel(text)
            h.setObjectName("modasWinUnit")
            grid.addWidget(h, 0, c)
        for r, (key, name) in enumerate(rows, 1):
            lab = QLabel(name)
            box = QLineEdit()
            box.setPlaceholderText("değer")
            box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            box.setFixedWidth(90)
            box.setValidator(QRegularExpressionValidator(QRegularExpression(r"^-?\d*[.,]?\d*$"), box))
            box.setEnabled(False)
            box.returnPressed.connect(lambda k=key, b=box: self.submit_requested.emit(k, b.text()))
            lock = LockButton(24)
            lock.lock_requested.connect(lambda want, k=key: self.lock_requested.emit(k, want))
            grid.addWidget(lab, r, 0)
            grid.addWidget(box, r, 1)
            grid.addWidget(lock, r, 2, Qt.AlignCenter)
            self.boxes[key], self.locks[key] = box, lock
        grid.setRowStretch(len(rows) + 1, 1)
        self.setWidget(body)
        self.resize(300, 56 + 34 * len(rows))
        self._timer = QTimer(self)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.sync)
        self._timer.start()
        self.sync()

    def sync(self):
        """Kilit durumlarını tek doğru kaynaktan (Test Tezgâhı) yansıtır; kapalı eyleyicinin kutusu pasiftir."""
        try:
            states = self._provider() or {}
        except Exception:  # noqa: BLE001 - yansıtma hatası pencereyi düşürmesin
            states = {}
        for key, lock in self.locks.items():
            opened = bool(states.get(key))
            if lock.is_open != opened:
                lock.set_open(opened)
            self.boxes[key].setEnabled(opened)

    def mark(self, key: str, bad: bool):
        box = self.boxes.get(key)
        if box is not None:
            box.setProperty("bad", bad)
            self.refresh_style(box)

    def state(self) -> dict:
        return {"kind": "actuator", "name": self.label, "geom": self.geometry_state()}

    def closeEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)
