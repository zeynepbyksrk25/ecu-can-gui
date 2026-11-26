"""Test girişi pencereleri (Modas "Potiboard" mantığı): uçuş koşulu ve motor komutu girişleri worksheet içinde birer değer kutusu.

Beyaz kutu = ayarlanabilir. Değer yazılınca "bekleyen" (sarı) olur; **Enter** gönderir, Esc vazgeçer, M / N değeri
artırır / azaltır. Pencere hiçbir şeyi kendisi göndermez: istek ``submitted`` ile MainWindow'a gider ve mevcut güvenli
yoldan (rol denetimi + CAN/A2L eşleşmesi + gönderim kaydı) yapılır; sonuç ``set_result`` ile döner.

Girişler: Uçuş koşulları (Altitude, Alfa, Beta, Ma Number, Total Inlet Pressure, Ambient Pressure, Ambient Temperature)
ve Motor komutları (Start, Throttle).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from app import theme
from app.dashboard_config import ACTUATOR_LABELS, CONTROL_KEYS
from app.sim_interface import FLIGHT_DEFS, INPUT_BY_KEY
from app.ui.modas.windows import ModasSub, _ValueEdit, format_phys
from app.value_text import parse_value_text

PREFIX = "Input: "


@dataclass(frozen=True)
class TestInputDef:
    __test__ = False

    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    group: str           # "flight" | "control"
    step: float

    @property
    def title(self) -> str:
        return PREFIX + self.label


def _step(lo: float, hi: float) -> float:
    span = hi - lo
    for s in (0.01, 0.05, 0.1, 0.5, 1.0, 5.0):
        if span / s <= 200:
            return s
    return 5.0


def _build_defs() -> list:
    defs = [TestInputDef(d.key, d.label, d.unit, d.minimum, d.maximum, "flight", _step(d.minimum, d.maximum))
            for d in FLIGHT_DEFS]
    for key in CONTROL_KEYS:
        d = INPUT_BY_KEY.get(key)
        lo, hi = (d.minimum, d.maximum) if d is not None else (0.0, 120.0)
        label = d.label if d is not None else ACTUATOR_LABELS.get(key, key)
        defs.append(TestInputDef(key, label, d.unit if d is not None else "", lo, hi,
                                 "control", 1.0 if hi - lo >= 20 else _step(lo, hi)))
    return defs


TEST_INPUTS: list = _build_defs()
BY_KEY = {d.key: d for d in TEST_INPUTS}
BY_TITLE = {d.title: d for d in TEST_INPUTS}


class TestInputWindow(ModasSub):
    __test__ = False                               # pytest bunu test sınıfı sanmasın
    submitted = Signal(object, float)             # (pencere, değer): gönderim isteği

    def __init__(self, key: str):
        d = BY_KEY[key]
        super().__init__(d.title, theme.WARN)
        self.defn = d
        self.key = key
        self._allowed = True
        self._pending = False
        self._value: float | None = None
        body = QWidget()
        body.setObjectName("modasWinBody")
        row = QHBoxLayout(body)
        row.setContentsMargins(4, 3, 4, 3)
        row.setSpacing(4)
        glyph = QLabel("⇢")
        glyph.setObjectName("modasWinLabel")
        row.addWidget(glyph)
        self.edit = _ValueEdit()
        self.edit.setObjectName("modasValue")
        self.edit.setProperty("kind", "cal")
        self.edit.setMinimumWidth(90)
        self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.edit.textEdited.connect(lambda _t: self._set_pending(True))
        self.edit.returnPressed.connect(self._on_commit)
        self.edit.nudge.connect(self._on_nudge)
        self.edit.cancelled.connect(self.discard_pending)
        self.edit.remove.connect(self.close)
        row.addWidget(self.edit, 1)
        self.unit_label = QLabel(d.unit)
        self.unit_label.setObjectName("modasWinUnit")
        row.addWidget(self.unit_label)
        self.setWidget(body)
        self.resize(max(240, 150 + 8 * len(d.title)), 54)
        self._apply_editable()
        self._tip()

    # ---- durum ---------------------------------------------------------------------
    @property
    def has_pending(self) -> bool:
        return self._pending

    @property
    def value(self) -> float | None:
        return self._value

    def _tip(self, extra: str = ""):
        d = self.defn
        base = (f"{d.label}: test girişi ({d.minimum:g} … {d.maximum:g} {d.unit}).\n"
                "Enter: gönder · Esc: vazgeç · M / N: artır / azalt")
        self.edit.setToolTip(f"{base}\n\n{extra}" if extra else base)

    def set_allowed(self, allowed: bool, reason: str = ""):
        """Rol (Mühendis / Yönetici) giriş göndermeye izin veriyor mu."""
        self._allowed = bool(allowed)
        if not self._allowed:
            self.discard_pending()
        self._apply_editable()
        self._tip("" if self._allowed else (reason or "Yetki yok: Mühendis veya Yönetici rolü gerekir."))

    def _apply_editable(self):
        self.edit.setReadOnly(not self._allowed)

    def _set_pending(self, on: bool):
        self._pending = on
        self.edit.setProperty("pending", on)
        self.refresh_style(self.edit)

    def set_value(self, value: float | None):
        """Gösterilen değeri günceller (dışarıdan senkron). Kullanıcı yazarken ezilmez."""
        self._value = None if value is None else float(value)
        if not self._pending:
            self._render()

    def _render(self):
        self.edit.setText(format_phys(self._value) if self._value is not None else "")
        self.edit.setCursorPosition(0)
        self.edit.setModified(False)

    def discard_pending(self):
        if self._pending:
            self._set_pending(False)
        self.edit.setProperty("bad", False)
        self.refresh_style(self.edit)
        self._render()

    # ---- gönderim ------------------------------------------------------------------
    def _check(self, text: str) -> float:
        """Metni sayıya çevirir ve aralığı denetler; geçersizse ValueError (nedeniyle)."""
        v = parse_value_text(text)
        d = self.defn
        if not d.minimum <= v <= d.maximum:
            raise ValueError(f"{d.label} {d.minimum:g} … {d.maximum:g} {d.unit} aralığında olmalı.")
        return float(v)

    def _on_commit(self):
        if not self._pending or self.edit.isReadOnly():
            return
        try:
            v = self._check(self.edit.text())
        except ValueError as exc:
            self.set_result(False, str(exc))
            return
        self.submitted.emit(self, v)

    def _on_nudge(self, direction: int):
        if self.edit.isReadOnly():
            return
        cur = self._value if self._value is not None else 0.0
        v = min(max(cur + direction * self.defn.step, self.defn.minimum), self.defn.maximum)
        self.submitted.emit(self, round(v, 9))

    def set_result(self, ok: bool, message: str = ""):
        """MainWindow gönderim sonucunu bildirir: başarıda bekleyen biter, hatada kırmızı kalır."""
        if ok:
            self._set_pending(False)
            self.edit.setProperty("bad", False)
            self.edit.setModified(False)
            self.refresh_style(self.edit)
            self._tip(f"✔ {message}" if message else "")
        else:
            self.edit.setProperty("bad", True)
            self.refresh_style(self.edit)
            self._tip(f"⚠ {message}")

    def state(self) -> dict:
        return {"kind": "input", "name": self.label, "key": self.key, "geom": self.geometry_state()}
