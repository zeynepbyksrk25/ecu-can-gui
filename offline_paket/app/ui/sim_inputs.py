"""Ana Sayfa'daki iki giriş kartı: **Uçuş Koşulları** (uçaktan gelen değerler) ve
**Motor Kontrol** (kullanıcı komutları). Değerler CAN hattından (DBC) basılır;
gönderimi MainWindow yapar, bu widget yalnızca ``values_changed({anahtar: değer})``
sinyali yayar. Sinyal eşleşmeleri "Eşleşmeler" penceresinden yapılır."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from app.ui.noscroll import no_wheel
from app.sim_interface import INPUT_BY_KEY, INPUT_DEFS, SimConfig, auto_match, list_sources
from app.ui.dash_widgets import DK_CYAN, DK_MUT, IconLabel, ToggleSwitch

FLIGHT_LEFT = ["altitude", "ma", "alfa", "beta"]
FLIGHT_RIGHT = ["p_amb", "t_amb", "p_total"]
CONTROL_ORDER = ["start", "spark", "throttle", "primary_fuel"]

ICON_OF = {
    "altitude": "alt", "ma": "mach", "alfa": "alpha", "beta": "beta",
    "p_amb": "cloud", "t_amb": "temp", "p_total": "pin",
    "start": "power", "spark": "spark", "throttle": "throttle", "primary_fuel": "fuel",
}
DECIMALS = {"altitude": 1, "ma": 2, "alfa": 1, "beta": 1, "p_amb": 3, "t_amb": 1, "p_total": 3, "throttle": 1}

_FALLBACK_DEFAULTS = {"ma": 0.0, "p_total": 1.013, "p_amb": 1.013, "t_amb": 15.0}


def card_title(text: str, icon: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(IconLabel(icon, DK_CYAN, 18))
    t = QLabel(text.upper())
    t.setObjectName("cardTitle")
    row.addWidget(t)
    row.addStretch(1)
    return row


class SimInputsPanel(QWidget):
    values_changed = Signal(dict)

    def __init__(self, config: SimConfig | None = None, parent=None):
        super().__init__(parent)
        self.config = config or SimConfig()
        self._dbc = None
        self._sources = []
        self._src = {}
        self._allowed = True
        self._ctrl: dict[str, dict] = {}
        self._building = False
        self._build()

    # ------------------------------------------------------------ yapı
    def _build(self):
        self._building = True
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        # ---- Uçuş Koşulları
        self.flight_card = QFrame()
        self.flight_card.setObjectName("card")
        fl = QVBoxLayout(self.flight_card)
        fl.setContentsMargins(14, 8, 14, 6)
        fl.setSpacing(2)
        head = card_title("Uçuş Koşulları", "plane")
        self.flight_cycle = QLabel("")
        self.flight_cycle.setObjectName("mutedSmall")
        head.addWidget(self.flight_cycle)
        fl.addLayout(head)
        cols = QHBoxLayout()
        cols.setSpacing(16)
        for keys in (FLIGHT_LEFT, FLIGHT_RIGHT):
            col = QVBoxLayout()
            col.setSpacing(0)
            if keys is FLIGHT_RIGHT:
                col.addStretch(1)      # 3 satır, soldaki 4 satıra göre dikey ortalanır
            for k in keys:
                col.addLayout(self._flight_row(INPUT_BY_KEY[k]))
            col.addStretch(1)
            cols.addLayout(col, 9 if keys is FLIGHT_LEFT else 11)
            if keys is FLIGHT_LEFT:
                sep = QFrame()
                sep.setObjectName("vsep")
                sep.setFixedWidth(1)
                cols.addWidget(sep)
        fl.addLayout(cols)
        root.addWidget(self.flight_card)

        # ---- Motor Kontrol
        self.control_card = QFrame()
        self.control_card.setObjectName("card")
        cl = QVBoxLayout(self.control_card)
        cl.setContentsMargins(14, 8, 14, 6)
        cl.setSpacing(0)
        head = card_title("Motor Kontrol", "sliders")
        self.send_all_button = QPushButton("Hepsini gönder")
        self.send_all_button.setProperty("compact", True)
        self.send_all_button.setProperty("tone", "go")
        self.send_all_button.clicked.connect(self._send_all)
        self.reset_button = QPushButton("Varsayılan")
        self.reset_button.setProperty("compact", True)
        self.reset_button.clicked.connect(self._reset)
        head.addWidget(self.reset_button)
        head.addWidget(self.send_all_button)
        cl.addLayout(head)
        for k in CONTROL_ORDER:
            cl.addLayout(self._control_row(INPUT_BY_KEY[k]))
        # Tek satırlık durum: gönderim sonucu varsa o, yoksa eşleşme uyarısı
        self._info_text = ""
        self._status_text = ""
        self._status_ok = True
        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedSmall")
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        cl.addWidget(self.status_label)
        root.addWidget(self.control_card)

        self._building = False
        for d in INPUT_DEFS:
            self._set_widget(d.key, self._initial(d.key))
        self._refresh_warn()

    def _name_label(self, d) -> QLabel:
        lab = QLabel(d.display)
        lab.setObjectName("rowName")
        lab.setToolTip(f"{d.label} [{d.unit}]" if d.unit else d.label)
        return lab

    def _spin(self, d) -> QDoubleSpinBox:
        spin = no_wheel(QDoubleSpinBox())
        spin.setRange(d.minimum, d.maximum)
        spin.setDecimals(DECIMALS.get(d.key, 2))
        spin.setSingleStep(1.0 if d.kind == "slider" else 0.1)
        spin.setAlignment(Qt.AlignRight)
        if d.unit:
            spin.setSuffix(f" {d.unit}")
        spin.setObjectName("valueSpin")
        spin.setKeyboardTracking(False)
        return spin

    def _flight_row(self, d) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(6)
        row.setContentsMargins(0, 0, 0, 0)
        spin = self._spin(d)
        spin.setObjectName("flightSpin")
        spin.setMinimumWidth(108)
        spin.editingFinished.connect(lambda k=d.key: self._emit_one(k))
        warn = QLabel("")
        warn.setObjectName("warnDot")
        warn.setVisible(False)
        lab = self._name_label(d)
        # dar sütunda metin kırpılabilsin diye etiket küçülebilir (kart taşmaz)
        lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        row.addWidget(IconLabel(ICON_OF[d.key], DK_MUT, 16))
        row.addWidget(lab, 1)
        row.addWidget(warn)
        row.addWidget(spin)
        if not d.enabled:
            spin.setEnabled(False)
            lab.setEnabled(False)
        self._ctrl[d.key] = {"kind": "num", "w": spin, "warn": warn, "label": lab}
        wrap = QFrame()
        wrap.setObjectName("rowFrame")
        wrap.setLayout(row)
        wrap.setMinimumHeight(34)
        outer = QHBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(wrap)
        return outer

    def _control_row(self, d) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setSpacing(0)
        box.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.setContentsMargins(0, 0, 0, 0)
        lab = self._name_label(d)
        warn = QLabel("")
        warn.setObjectName("warnDot")
        row.addWidget(IconLabel(ICON_OF[d.key], DK_MUT, 18))
        row.addWidget(lab, 1)
        row.addWidget(warn)
        if d.kind == "switch":
            sw = ToggleSwitch()
            sw.toggled.connect(lambda checked, k=d.key: self._on_switch(k, checked))
            row.addWidget(sw)
            self._ctrl[d.key] = {"kind": "switch", "w": sw, "warn": warn, "label": lab}
        else:
            spin = self._spin(d)
            spin.setMinimumWidth(108)
            sl = no_wheel(QSlider(Qt.Horizontal))
            sl.setRange(int(d.minimum * 10), int(d.maximum * 10))
            sl.sliderReleased.connect(lambda k=d.key: self._emit_one(k))
            sl.valueChanged.connect(lambda v, k=d.key: self._slider_moved(k, v))
            spin.editingFinished.connect(lambda k=d.key: self._spin_done(k))
            row.addWidget(spin)
            self._ctrl[d.key] = {"kind": "slider", "w": spin, "slider": sl, "warn": warn, "label": lab}
        wrap = QFrame()
        wrap.setObjectName("rowFrame")
        wrap.setLayout(row)
        wrap.setMinimumHeight(34)
        box.addWidget(wrap)
        if d.kind == "slider":
            srow = QHBoxLayout()
            srow.setContentsMargins(28, 0, 0, 2)
            srow.setSpacing(8)
            lo, hi = QLabel(f"{d.minimum:g}%"), QLabel(f"{d.maximum:g}%")
            for x in (lo, hi):
                x.setObjectName("mutedSmall")
            srow.addWidget(lo)
            srow.addWidget(self._ctrl[d.key]["slider"], 1)
            srow.addWidget(hi)
            box.addLayout(srow)
        return box

    # ------------------------------------------------------------ değerler
    def _default_of(self, key: str) -> float:
        d = INPUT_BY_KEY[key]
        s = self._src.get(self.config.input_map.get(key, ""))
        if s is not None and s.initial is not None:
            return max(d.minimum, min(d.maximum, float(s.initial)))
        if key in _FALLBACK_DEFAULTS:  # DBC başlangıç değeri yoksa: deniz seviyesi (ISA)
            return _FALLBACK_DEFAULTS[key]
        return 0.0 if d.minimum <= 0 <= d.maximum else float(d.minimum)

    def _initial(self, key: str) -> float:
        if key in self.config.input_values:
            return self.config.input_values[key]
        return self._default_of(key)

    def _set_widget(self, key: str, value: float):
        c = self._ctrl[key]
        self._building = True
        try:
            if c["kind"] == "switch":
                c["w"].setChecked(bool(round(value)))
            else:
                c["w"].setValue(value)
                if "slider" in c:
                    c["slider"].setValue(int(round(value * 10)))
        finally:
            self._building = False

    def value_of(self, key: str) -> float:
        c = self._ctrl[key]
        if c["kind"] == "switch":
            return 1.0 if c["w"].isChecked() else 0.0
        return float(c["w"].value())

    def values(self) -> dict:
        return {d.key: self.value_of(d.key) for d in INPUT_DEFS}

    def send_value(self, key: str, value: float):
        """Dışarıdan (Çalışma Alanı > Kontrol) değer gönderir: widget'ı günceller ve
        Ana Sayfa'daki gönderimle AYNI yolu (rol kilidi dahil) izler."""
        if key not in self._ctrl:
            return
        self._set_widget(key, float(value))
        self._emit({key: float(value)})

    def set_values(self, values: dict):
        """Dışarıdan (Kontrol Paneli uygulanınca vb.) senkronlama; sinyal yayılmaz."""
        for k, v in values.items():
            if k in self._ctrl and v is not None:
                self._set_widget(k, float(v))
                self.config.input_values[k] = float(v)
        self.config.save()

    def mapped(self, key: str):
        """(mesaj, sinyal) ya da None."""
        s = self._src.get(self.config.input_map.get(key, ""))
        return (s.where, s.name) if s is not None else None

    def sendable_keys(self) -> list:
        return [d.key for d in INPUT_DEFS if d.enabled and self.mapped(d.key) is not None]

    # ------------------------------------------------------------ olaylar
    def _on_switch(self, key, checked):
        if self._building:
            return
        self._emit({key: 1.0 if checked else 0.0})

    def _slider_moved(self, key, v):
        if self._building:
            return
        c = self._ctrl[key]
        self._building = True
        c["w"].setValue(v / 10.0)
        self._building = False
        if not c["slider"].isSliderDown():       # ok tuşları / tekerlek
            self._emit({key: v / 10.0})

    def _spin_done(self, key):
        c = self._ctrl[key]
        self._building = True
        c["slider"].setValue(int(round(c["w"].value() * 10)))
        self._building = False
        self._emit({key: self.value_of(key)})

    def _emit_one(self, key):
        if self._building:
            return
        self._emit({key: self.value_of(key)})

    def _emit(self, vals: dict):
        if not self._allowed:
            self.set_status("🔒 Operatör rolünde girişler kilitli (Mühendis veya Yönetici gerekir).", False)
            return
        for k, v in vals.items():
            self.config.input_values[k] = float(v)
        self.set_status("gönderiliyor…", True)
        self.config.save()
        self.values_changed.emit(vals)

    def _send_all(self):
        keys = self.sendable_keys()
        if not keys:
            self.set_status("Bağlı giriş yok: ⚙ Eşleşmeler ile DBC sinyallerini seçin.", False)
            return
        self._emit({k: self.value_of(k) for k in keys})

    def _reset(self):
        for d in INPUT_DEFS:
            self._set_widget(d.key, self._default_of(d.key))
            self.config.input_values.pop(d.key, None)
        self.config.save()
        self.set_status("Değerler varsayılana döndü (gönderilmedi).", True)

    # ------------------------------------------------------------ dışarıdan
    def set_allowed(self, allowed: bool):
        self._allowed = allowed
        for d in INPUT_DEFS:
            c = self._ctrl[d.key]
            on = allowed and d.enabled
            c["w"].setEnabled(on)
            if "slider" in c:
                c["slider"].setEnabled(on)
        self.send_all_button.setEnabled(allowed)
        self.reset_button.setEnabled(allowed)
        if not allowed:
            self.set_status("🔒 Operatör rolünde girişler kilitli.", False)
        elif self.status_label.text().startswith("🔒"):
            self.set_status("", True)

    def set_sent(self, keys, ok: bool = True):
        """Gönderim sonucunu tek satırlık durumda gösterir."""
        keys = list(keys)
        if keys:
            self.set_status(f"✓ {len(keys)} değer gönderildi" if ok else "✕ Gönderilemedi", ok)

    def set_status(self, text: str, ok: bool):
        self._status_text, self._status_ok = text, ok
        self._render_status()

    def _render_status(self):
        if self._status_text:
            text, name = self._status_text, ("okSmall" if self._status_ok else "errSmall")
        else:
            text, name = self._info_text, "warnSmall"
        self.status_label.setText(text)
        self.status_label.setObjectName(name if text else "mutedSmall")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        self.status_label.setToolTip(text)

    def refresh_sources(self, dbc=None):
        if dbc is not None:
            self._dbc = dbc
        ok = self._dbc if (self._dbc is not None and getattr(self._dbc, "is_loaded", False)) else None
        self._sources = list_sources(ok, None, dbc_only=True)
        self._src = {s.key: s for s in self._sources}
        changed = False
        for d in INPUT_DEFS:
            cur = self.config.input_map.get(d.key)
            if cur:
                continue
            hit = auto_match(d.aliases, d.label, self._sources)
            if hit is not None:
                self.config.input_map[d.key] = hit.key
                changed = True
                if d.key not in self.config.input_values:
                    self._set_widget(d.key, self._default_of(d.key))
        if changed:
            self.config.save()
        self._refresh_warn()

    def sources(self) -> list:
        return list(self._sources)

    def _refresh_warn(self):
        missing = []
        show = bool(self._sources)  # DBC hiç yokken satır satır uyarı yok; tek banner
        for d in INPUT_DEFS:
            c = self._ctrl[d.key]
            bound = self.mapped(d.key) is not None
            c["warn"].setText("" if (bound or not d.enabled or not show) else "⚠")
            c["warn"].setVisible(bool(c["warn"].text()))
            c["warn"].setToolTip("DBC sinyali bağlı değil — ⚙ Eşleşmeler")
            tip = (f"{self.config.input_map.get(d.key, '')}" if bound else
                   "DBC sinyali bağlı değil — ⚙ Eşleşmeler")
            c["w"].setToolTip(tip)
            if d.enabled and not bound:
                missing.append(d.display)
        m = self.mapped("altitude")
        msg = self._dbc.get_message(m[0]) if (m and self._dbc is not None) else None
        ct = getattr(msg, "cycle_time", None) if msg is not None else None
        self.flight_cycle.setText(f"CAN {ct} ms" if ct else ("CAN periyodik" if m else ""))
        if not self._sources:
            self._info_text = "DBC yüklenmedi (CAN Monitor → DBC)."
        elif missing:
            self._info_text = f"⚠ {len(missing)} giriş DBC sinyaline bağlı değil"
        else:
            self._info_text = ""
        self._render_status()
