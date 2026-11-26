"""Ana Sayfa'daki **Uçuş Koşulları** kartı (uçaktan gelen değerler). Her giriş CAN hattından (DBC sinyali)
ya da CCP ile A2L değişkenine yazılır; gönderimi MainWindow yapar, bu widget yalnızca
``values_changed({anahtar: değer})`` sinyali yayar. Sinyal eşleşmeleri "Eşleşmeler" penceresinden yapılır
(``input_map``: "dbc:MESAJ.SİNYAL" ya da "a2l:Değişken").

Motor Kontrol (Start/Spark/Gaz Kolu/Birincil Yakıt) artık buradan GİTMEZ: Eyleyiciler gibi kilitli
satırlardır (bkz. DashboardTab)."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.ui.noscroll import no_wheel
from app.sim_interface import FLIGHT_DEFS, INPUT_BY_KEY, SimConfig, SourceSig, auto_match, list_sources
from app.ui.dash_widgets import ACCENTS, DK_MUT, IconLabel

FLIGHT_LEFT = ["altitude", "ma", "alfa", "beta"]
FLIGHT_RIGHT = ["p_amb", "t_amb", "p_total"]

ICON_OF = {
    "altitude": "alt", "ma": "mach", "alfa": "alpha", "beta": "beta",
    "p_amb": "cloud", "t_amb": "temp", "p_total": "pin",
}
DECIMALS = {"altitude": 1, "ma": 2, "alfa": 1, "beta": 1, "p_amb": 3, "t_amb": 1, "p_total": 3}

_FALLBACK_DEFAULTS = {"ma": 0.0, "p_total": 1.013, "p_amb": 1.013, "t_amb": 15.0}


def card_title(text: str, icon: str) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(8)
    row.addWidget(IconLabel(icon, ACCENTS["blue"], 18))
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
        self._a2l_summary = None
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
        self.flight_card.setProperty("accent", "blue")
        fl = QVBoxLayout(self.flight_card)
        fl.setContentsMargins(14, 8, 14, 6)
        fl.setSpacing(2)
        head = card_title("Uçuş Koşulları", "plane")
        self.flight_cycle = QLabel("")
        self.flight_cycle.setObjectName("mutedSmall")
        head.addWidget(self.flight_cycle)
        self.send_all_button = QPushButton("Hepsini\ngönder")
        self.send_all_button.setProperty("compact", True)
        self.send_all_button.setProperty("tone", "go")
        self.send_all_button.clicked.connect(self._send_all)
        self.reset_button = QPushButton("Varsayılan")
        self.reset_button.setProperty("compact", True)
        self.reset_button.clicked.connect(self._reset)
        for b in (self.reset_button, self.send_all_button):   # dar ve biraz uzun: başlık satırında taşmaz
            b.setFixedSize(82, 42)
            b.setStyleSheet("padding: 2px 4px; font-size: 11px; font-weight: 700;")
        head.addWidget(self.reset_button)
        head.addWidget(self.send_all_button)
        fl.addLayout(head)
        # Izgara: sol ve sağ sütun satır satır AYNI yükseklikte hizalanır; etiket sütunları
        # yazı tipine göre kendi metin genişliğini ister (kırpılmaz).
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(0)
        for r, k in enumerate(FLIGHT_LEFT):
            grid.addWidget(self._flight_row(INPUT_BY_KEY[k]), r, 0)
        # Sağ sütun (3 satır) sol sütunla (4 satır) hizalı: ilki sol sütunun ilkiyle başlar, sonuncusu sonuncuyla
        # biter, aradaki boşluk eşit paylaşılır (sıkışık durmaz).
        right = QVBoxLayout()
        right.setSpacing(0)
        right.setContentsMargins(0, 0, 0, 0)
        for i, k in enumerate(FLIGHT_RIGHT):
            if i:
                right.addStretch(1)
            right.addWidget(self._flight_row(INPUT_BY_KEY[k]))
        grid.addLayout(right, 0, 2, len(FLIGHT_LEFT), 1)
        sep = QFrame()
        sep.setObjectName("vsep")
        sep.setFixedWidth(1)
        grid.addWidget(sep, 0, 1, len(FLIGHT_LEFT), 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        fl.addLayout(grid)
        root.addWidget(self.flight_card)

        # Tek satırlık durum: gönderim sonucu varsa o, yoksa eşleşme uyarısı
        self._info_text = ""
        self._status_text = ""
        self._status_ok = True
        self.status_label = QLabel("")
        self.status_label.setObjectName("mutedSmall")
        self.status_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        fl.addWidget(self.status_label)

        self._building = False
        for d in FLIGHT_DEFS:
            self._set_widget(d.key, self._initial(d.key))
        self._refresh_warn()

    def _name_label(self, d) -> QLabel:
        lab = QLabel(d.display)
        lab.setObjectName("rowName")
        lab.setToolTip(f"{d.label} [{d.unit}]" if d.unit else d.label)
        return lab

    def _spin(self, d) -> QDoubleSpinBox:
        spin = no_wheel(QDoubleSpinBox())
        spin.setRange(-1e9, 1e9)     # girdi sınırı YOK (kullanıcı isteği); d.minimum/maximum yalnızca varsayılan içindir
        spin.setDecimals(DECIMALS.get(d.key, 2))
        spin.setSingleStep(1.0 if d.kind == "slider" else 0.1)
        spin.setAlignment(Qt.AlignRight)
        if d.unit:
            spin.setSuffix(f" {d.unit}")
        spin.setObjectName("valueSpin")
        spin.setKeyboardTracking(False)
        return spin

    def _flight_row(self, d) -> QFrame:
        row = QHBoxLayout()
        row.setSpacing(4)
        row.setContentsMargins(0, 0, 0, 0)
        spin = self._spin(d)
        spin.setObjectName("flightSpin")
        spin.setMinimumWidth(100)
        spin.editingFinished.connect(lambda k=d.key: self._emit_one(k))
        warn = QLabel("")
        warn.setObjectName("warnDot")
        warn.setVisible(False)
        lab = self._name_label(d)
        lab.setStyleSheet("font-size: 13px;")   # DejaVu gibi geniş yazı tiplerinde de sığsın
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
        wrap.setFixedHeight(36)
        return wrap

    # ------------------------------------------------------------ değerler
    def _default_of(self, key: str) -> float:
        d = INPUT_BY_KEY[key]
        s = self._src.get(self.config.input_map.get(key, ""))
        if s is not None and s.initial is not None:
            return float(s.initial)
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
        return {d.key: self.value_of(d.key) for d in FLIGHT_DEFS}

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
        """CAN eşleşmesi: (mesaj, sinyal) ya da None (eşleşme yok / A2L eşleşmesi)."""
        s = self._src.get(self.config.input_map.get(key, ""))
        return (s.where, s.name) if (s is not None and not s.key.startswith("a2l:")) else None

    def mapped_a2l(self, key: str):
        """A2L eşleşmesi: değişken adı ya da None."""
        s = self._src.get(self.config.input_map.get(key, ""))
        return s.name if (s is not None and s.key.startswith("a2l:")) else None

    def is_bound(self, key: str) -> bool:
        return self.mapped(key) is not None or self.mapped_a2l(key) is not None

    def sendable_keys(self) -> list:
        return [d.key for d in FLIGHT_DEFS if d.enabled and self.is_bound(d.key)]

    # ------------------------------------------------------------ olaylar
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
            self.set_status("Bağlı giriş yok: ⚙ Eşleşmeler ile DBC sinyali / A2L değişkeni seçin.", False)
            return
        self._emit({k: self.value_of(k) for k in keys})

    def _reset(self):
        for d in FLIGHT_DEFS:
            self._set_widget(d.key, self._default_of(d.key))
            self.config.input_values.pop(d.key, None)
        self.config.save()
        self.set_status("Değerler varsayılana döndü (gönderilmedi).", True)

    # ------------------------------------------------------------ dışarıdan
    def set_allowed(self, allowed: bool):
        self._allowed = allowed
        for d in FLIGHT_DEFS:
            c = self._ctrl[d.key]
            on = allowed and d.enabled
            c["w"].setEnabled(on)
            if "slider" in c:
                c["slider"].setEnabled(on)
        self.send_all_button.setEnabled(allowed)
        self.reset_button.setEnabled(allowed)
        if not allowed:
            self.set_status("", True)     # kilit bilgisi Ana Sayfa'nın üstündeki rol bandında
        elif self.status_label.text().startswith("🔒"):
            self.set_status("", True)

    def set_sent(self, keys, ok: bool = True):
        """Gönderim sonucunu tek satırlık durumda gösterir."""
        keys = list(keys)
        if keys:
            self.set_status(f"✓ {len(keys)} değer gönderildi" if ok else "✕ Gönderilemedi", ok)

    def last_status(self) -> tuple:
        """Son gönderimin durum metni ve başarısı: ``(metin, ok)`` (Worksheets test girişi pencereleri okur)."""
        return self._status_text, self._status_ok

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

    def refresh_sources(self, dbc=None, a2l_summary=None):
        if dbc is not None:
            self._dbc = dbc
        if a2l_summary is not None:
            self._a2l_summary = a2l_summary
        ok = self._dbc if (self._dbc is not None and getattr(self._dbc, "is_loaded", False)) else None
        dbc_sources = list_sources(ok, None, dbc_only=True)
        a2l_sources = self._a2l_sources()
        self._sources = dbc_sources + a2l_sources
        self._src = {s.key: s for s in self._sources}
        changed = False
        for d in FLIGHT_DEFS:
            cur = self.config.input_map.get(d.key)
            if cur:
                continue
            # Önce DBC; bulunamazsa A2L (aynı adın iki kaynakta olması belirsizlik yaratmasın)
            hit = auto_match(d.aliases, d.label, dbc_sources) or auto_match(d.aliases, d.label, a2l_sources)
            if hit is not None:
                self.config.input_map[d.key] = hit.key
                changed = True
                if d.key not in self.config.input_values:
                    self._set_widget(d.key, self._default_of(d.key))
        if changed:
            self.config.save()
        self._refresh_warn()

    def _a2l_sources(self) -> list:
        """A2L ölçüm + karakteristik adları (CCP ile yazılabilecek değişkenler)."""
        summ = self._a2l_summary
        if summ is None:
            return []
        out, seen = [], set()
        for coll in (getattr(summ, "measurements", []), getattr(summ, "characteristics", [])):
            for me in coll:
                if me.name in seen:
                    continue
                seen.add(me.name)
                out.append(SourceSig(f"a2l:{me.name}", me.name, "A2L", getattr(me, "unit", "") or "",
                                     getattr(me, "minimum", None), getattr(me, "maximum", None), None, None, me))
        return out

    def sources(self) -> list:
        return list(self._sources)

    def _refresh_warn(self):
        missing = []
        show = bool(self._sources)  # DBC hiç yokken satır satır uyarı yok; tek banner
        for d in FLIGHT_DEFS:
            c = self._ctrl[d.key]
            bound = self.is_bound(d.key)
            c["warn"].setText("" if (bound or not d.enabled or not show) else "⚠")
            c["warn"].setVisible(bool(c["warn"].text()))
            c["warn"].setToolTip("DBC sinyali / A2L değişkeni bağlı değil — ⚙ Eşleşmeler")
            tip = (f"{self.config.input_map.get(d.key, '')}" if bound else
                   "DBC sinyali / A2L değişkeni bağlı değil — ⚙ Eşleşmeler")
            c["w"].setToolTip(tip)
            if d.enabled and not bound:
                missing.append(d.display)
        m = self.mapped("altitude")
        msg = self._dbc.get_message(m[0]) if (m and self._dbc is not None) else None
        ct = getattr(msg, "cycle_time", None) if msg is not None else None
        if m:
            self.flight_cycle.setText(f"CAN {ct} ms" if ct else "CAN periyodik")
        else:
            self.flight_cycle.setText("A2L (CCP)" if self.mapped_a2l("altitude") else "")
        if not self._sources:
            self._info_text = "DBC / A2L yüklenmedi."
        elif missing:
            self._info_text = f"⚠ {len(missing)} giriş DBC/A2L değişkenine bağlı değil"
        else:
            self._info_text = ""
        self._render_status()
