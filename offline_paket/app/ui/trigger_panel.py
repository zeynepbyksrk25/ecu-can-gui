"""Tetikleyici ile otomatik kayıt paneli (eşik / sayaç artışı / durum geçişi, pre/post-trigger).
Eşik değerleri kullanıcıdan gelir; varsayılan eşik yoktur. Mantık: app/record_trigger.py."""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget,
)

from app.record_trigger import COUNTER_INCREASE, OPS, THRESHOLD, TRANSITION, Trigger
from app.ui.dash_widgets import make_card


class TriggerPanel(QWidget):
    config_changed = Signal(object, float, float)      # Trigger | None, pre_s, post_s

    def __init__(self, parent=None):
        super().__init__(parent)
        card, v, head = make_card("Tetikleyici ile otomatik kayıt", "flag")
        self.arm_check = QCheckBox("Kuruldu")
        self.arm_check.setToolTip("Kuruluyken koşul gerçekleşince kayıt otomatik başlar (tetik öncesi örnekler dahil) ve "
                                  "tetik sonrası süre dolunca durur. Bir kez çalışır.")
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("Eşik", THRESHOLD)
        self.kind_combo.addItem("Sayaç artışı (ör. CAN hata sayısı)", COUNTER_INCREASE)
        self.kind_combo.addItem("Durum geçişi (ör. motor durumu)", TRANSITION)
        self.signal_edit = QLineEdit()
        self.signal_edit.setPlaceholderText("MESAJ.SİNYAL (DBC)")
        self.op_combo = QComboBox()
        self.op_combo.addItems(list(OPS))
        self.value_spin = QDoubleSpinBox()
        self.value_spin.setRange(-1e9, 1e9)
        self.value_spin.setDecimals(4)
        self.pre_spin = QDoubleSpinBox()
        self.pre_spin.setRange(0, 600)
        self.pre_spin.setValue(5)
        self.pre_spin.setSuffix(" sn önce")
        self.post_spin = QDoubleSpinBox()
        self.post_spin.setRange(0, 3600)
        self.post_spin.setValue(10)
        self.post_spin.setSuffix(" sn sonra")
        self.status_label = QLabel("Kurulu değil.")
        row = QHBoxLayout()
        for w in (self.arm_check, self.kind_combo, self.signal_edit, self.op_combo, self.value_spin, self.pre_spin,
                  self.post_spin):
            row.addWidget(w)
        v.addLayout(row)
        v.addWidget(self.status_label)
        out = QVBoxLayout(self)
        out.setContentsMargins(0, 0, 0, 0)
        out.addWidget(card)
        self.arm_check.toggled.connect(self._emit)

    def trigger(self) -> Trigger:
        return Trigger(self.kind_combo.currentData(), self.signal_edit.text().strip(), self.op_combo.currentText(),
                       self.value_spin.value())

    def _emit(self, on: bool):
        if not on:
            self.status_label.setText("Kurulu değil.")
            self.config_changed.emit(None, 0.0, 0.0)
            return
        trg = self.trigger()
        try:
            trg.validate()
        except ValueError as exc:
            self.arm_check.blockSignals(True)
            self.arm_check.setChecked(False)
            self.arm_check.blockSignals(False)
            self.status_label.setText(f"Kurulamadı: {exc}")
            return
        self.status_label.setText(f"Kuruldu: {trg.signal} bekleniyor…")
        self.config_changed.emit(trg, self.pre_spin.value(), self.post_spin.value())

    def disarm(self, text: str = ""):
        self.arm_check.blockSignals(True)
        self.arm_check.setChecked(False)
        self.arm_check.blockSignals(False)
        self.status_label.setText(text or "Kurulu değil.")
