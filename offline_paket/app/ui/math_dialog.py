"""Matematik sinyali tanımı penceresi: ölçekle (a·x + b) / işlem (A ○ B) / hareketli ortalama (Scope'tan açılır)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QLabel, QLineEdit, QVBoxLayout,
)

from app import theme
from app.signal_hub import OP_LABELS


class MathDialog(QDialog):
    """Matematik sinyali tanımı: ölçekle / işlem / hareketli ortalama."""

    def __init__(self, ids: list, existing: tuple | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Matematik sinyali")
        self.resize(460, 330)
        self.name = QLineEdit()
        self.name.setPlaceholderText("örn. P3_P2")
        self.kind = QComboBox()
        self.kind.addItems(["Ölçekle  (a·x + b)", "İşlem  (A ○ B)", "Hareketli ortalama"])
        self.src = self._id_combo(ids)
        self.src2 = self._id_combo(ids)
        self.op = QComboBox()
        for k, lab in OP_LABELS.items():
            self.op.addItem(lab, k)
        self.gain = QDoubleSpinBox()
        self.gain.setRange(-1e9, 1e9)
        self.gain.setDecimals(6)
        self.gain.setValue(1.0)
        self.offset = QDoubleSpinBox()
        self.offset.setRange(-1e9, 1e9)
        self.offset.setDecimals(6)
        self.window = QDoubleSpinBox()
        self.window.setRange(0.1, 3600.0)
        self.window.setDecimals(1)
        self.window.setValue(2.0)
        self.window.setSuffix(" sn")

        form = QFormLayout()
        form.addRow("İsim", self.name)
        form.addRow("Tür", self.kind)
        form.addRow("Sinyal (A)", self.src)
        self.row_b = (QLabel("Sinyal (B)"), self.src2)
        form.addRow(*self.row_b)
        self.row_op = (QLabel("İşlem"), self.op)
        form.addRow(*self.row_op)
        self.row_gain = (QLabel("Çarpan (a)"), self.gain)
        form.addRow(*self.row_gain)
        self.row_off = (QLabel("Toplanan (b)"), self.offset)
        form.addRow(*self.row_off)
        self.row_win = (QLabel("Pencere"), self.window)
        form.addRow(*self.row_win)
        self.error = QLabel("")
        self.error.setStyleSheet(f"color:{theme.DANGER};")
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.error)
        lay.addStretch()
        lay.addWidget(bb)
        self.kind.currentIndexChanged.connect(self._sync)
        if existing:
            self._load(*existing)
        self._sync()

    @staticmethod
    def _id_combo(ids):
        cb = QComboBox()
        cb.setEditable(True)
        cb.setInsertPolicy(QComboBox.NoInsert)
        cb.addItems(ids)
        cb.setCurrentIndex(-1)
        cb.lineEdit().setPlaceholderText("İsme göre ara...")
        comp = QCompleter(ids, cb)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        cb.setCompleter(comp)
        return cb

    def _sync(self):
        k = self.kind.currentIndex()
        for w in self.row_b:
            w.setVisible(k == 1)
        for w in self.row_op:
            w.setVisible(k == 1)
        for w in self.row_gain + self.row_off:
            w.setVisible(k == 0)
        for w in self.row_win:
            w.setVisible(k == 2)

    def _load(self, name, spec):
        self.name.setText(name.split(":", 1)[1] if name.startswith("math:") else name)
        self.kind.setCurrentIndex({"scale": 0, "op": 1, "movavg": 2}.get(spec["kind"], 0))
        self.src.setCurrentText(spec.get("src", ""))
        self.src2.setCurrentText(spec.get("src2", "") or "")
        i = self.op.findData(spec.get("op", "+"))
        self.op.setCurrentIndex(max(i, 0))
        self.gain.setValue(float(spec.get("gain", 1.0)))
        self.offset.setValue(float(spec.get("offset", 0.0)))
        self.window.setValue(float(spec.get("window", 2.0)))

    def _accept(self):
        name = self.name.text().strip()
        if not name or ":" in name:
            self.error.setText("İsim boş olamaz ve ':' içeremez.")
            return
        if not self.src.currentText().strip():
            self.error.setText("Sinyal (A) seçin.")
            return
        if self.kind.currentIndex() == 1 and not self.src2.currentText().strip():
            self.error.setText("Sinyal (B) seçin.")
            return
        self.accept()

    def result_spec(self) -> tuple[str, dict]:
        k = self.kind.currentIndex()
        spec = {"src": self.src.currentText().strip()}
        if k == 0:
            spec.update(kind="scale", gain=self.gain.value(), offset=self.offset.value())
        elif k == 1:
            spec.update(kind="op", src2=self.src2.currentText().strip(), op=self.op.currentData())
        else:
            spec.update(kind="movavg", window=self.window.value())
        return self.name.text().strip(), spec
