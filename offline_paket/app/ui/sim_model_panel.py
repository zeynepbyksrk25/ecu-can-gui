"""Ana Sayfa > Simulink model kontrol paneli (yalnızca MIL modunda görünür).

Model durumu (NOT CONNECTED … ERROR) ile UDP bağlantı durumu AYRI gösterilir. "MIL Acil Dur" yalnızca modeli durdurur;
gerçek motor acil durdurmasının yerine GEÇMEZ.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from app.sim_bridge import matlab_ctl as mc

STATE_CHIP = {mc.NOT_CONNECTED: "chipDim", mc.CONNECTING: "chipDim", mc.READY: "chipDim", mc.RUNNING: "chipGreen",
              mc.PAUSED: "chipDim", mc.STOPPED: "chipDim", mc.ERROR: "chipDim"}
STATE_TR = {mc.NOT_CONNECTED: "BAĞLI DEĞİL", mc.CONNECTING: "BAĞLANIYOR", mc.READY: "HAZIR", mc.RUNNING: "ÇALIŞIYOR",
            mc.PAUSED: "DURAKLATILDI", mc.STOPPED: "DURDURULDU", mc.ERROR: "HATA"}


class SimModelPanel(QFrame):
    connect_requested = Signal(str, str)      # model adı, backend ("udp" | "matlab")
    command_requested = Signal(str, float)    # start|pause|resume|stop|reset|speed, argüman

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("trendCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        title = QLabel("SİMULİNK MODEL (MIL)")
        title.setObjectName("cardTitle")
        self.state_chip = QLabel(STATE_TR.get(mc.NOT_CONNECTED, mc.NOT_CONNECTED))
        self.state_chip.setObjectName("chipDim")
        self.udp_chip = QLabel("UDP: —")
        self.udp_chip.setObjectName("chipDim")
        self.time_label = QLabel("Sim. zamanı: —")
        self.time_label.setObjectName("mutedSmall")
        head.addWidget(title)
        head.addWidget(self.state_chip)
        head.addWidget(self.udp_chip)
        head.addStretch(1)
        head.addWidget(self.time_label)
        lay.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("Model adı (MATLAB Engine için)")
        self.model_edit.setMaximumWidth(180)
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("UDP kontrol", "udp")
        self.backend_combo.addItem("MATLAB Engine", "matlab")
        self.connect_button = QPushButton("Bağlan")
        self.connect_button.clicked.connect(lambda: self.connect_requested.emit(
            self.model_edit.text().strip(), self.backend_combo.currentData()))
        row.addWidget(self.model_edit)
        row.addWidget(self.backend_combo)
        row.addWidget(self.connect_button)
        row.addSpacing(10)
        self.buttons = {}
        for cmd, text in (("start", "Başlat"), ("pause", "Duraklat"), ("resume", "Sürdür"), ("stop", "Durdur"),
                          ("reset", "Sıfırla")):
            b = QPushButton(text)
            b.setEnabled(False)
            b.clicked.connect(lambda _c=False, c=cmd: self.command_requested.emit(c, 0.0))
            self.buttons[cmd] = b
            row.addWidget(b)
        self.speed_combo = QComboBox()
        for label, factor in mc.SPEEDS:
            self.speed_combo.addItem(label, factor)
        self.speed_combo.setCurrentIndex(2)
        self.speed_combo.setToolTip("Simülasyon hızı: Simulink pacing ile uygulanır (yalnızca GUI zamanlayıcısı değil)")
        self.speed_combo.activated.connect(lambda _i: self.command_requested.emit("speed", self.speed_combo.currentData()))
        row.addWidget(self.speed_combo)
        self.estop_button = QPushButton("MIL Acil Dur")
        self.estop_button.setProperty("tone", "danger")
        self.estop_button.setToolTip("Yalnızca MIL modelini durdurur. Gerçek motor acil durdurmasının YERİNE GEÇMEZ.")
        self.estop_button.setEnabled(False)
        self.estop_button.clicked.connect(lambda: self.command_requested.emit("stop", 0.0))
        row.addWidget(self.estop_button)
        row.addStretch(1)
        lay.addLayout(row)
        self.error_label = QLabel("")
        self.error_label.setObjectName("warnSmall")
        self.error_label.setWordWrap(True)
        self.error_label.setVisible(False)
        lay.addWidget(self.error_label)
        self.setVisible(False)

    def update_from(self, snap: dict, allowed):
        """``snap``: ModelController.snapshot(); ``allowed(cmd)``: komut geçerli mi."""
        st = snap["state"]
        self.state_chip.setText(STATE_TR.get(st, st))      # model durum kodları (READY …) ekranda Türkçe
        self.state_chip.setObjectName(STATE_CHIP.get(st, "chipDim"))
        self.state_chip.style().unpolish(self.state_chip)
        self.state_chip.style().polish(self.state_chip)
        self.udp_chip.setText(f"UDP: {snap['udp']}")
        self.udp_chip.setToolTip(snap.get("udp_text", ""))
        self.time_label.setText(f"Sim. zamanı: {snap['sim_time']:.3f} s" if snap["udp"] == "ok" else "Sim. zamanı: —")
        for cmd, b in self.buttons.items():
            b.setEnabled(bool(allowed(cmd)))
        self.estop_button.setEnabled(bool(allowed("stop")))
        self.connect_button.setEnabled(st in (mc.NOT_CONNECTED, mc.ERROR))
        self.error_label.setText(snap["error"] if st in (mc.ERROR, mc.NOT_CONNECTED) and snap["error"] else "")
        self.error_label.setVisible(bool(self.error_label.text()))
