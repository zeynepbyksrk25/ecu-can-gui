"""Ana Sayfa'daki "Simülasyon Girişleri" paneli: kullanıcı ve uçak girişleri
(anahtarlar, sürgüler, sabit değer kutuları). Gönderimi MainWindow yapar;
bu widget yalnızca `values_changed({anahtar: değer})` sinyali yayar."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame, QGridLayout,
    QHBoxLayout, QLabel, QPushButton, QScrollArea, QSlider, QVBoxLayout, QWidget,
)

from app.ui.noscroll import no_wheel
from app.sim_interface import INPUT_BY_KEY, INPUT_DEFS, SimConfig, auto_match, list_sources

GROUP_TITLES = {"control": "Kontrol (Kullanıcı)", "aircraft": "Uçak", "const": "Sabit değerler (şimdilik)"}
GROUP_LETTERS = {"control": "A", "aircraft": "B", "const": "C"}


class _MappingDialog(QDialog):
    def __init__(self, sources, current: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Giriş sinyallerini bağla (DBC)")
        self.resize(560, 520)
        self._sources = sources
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Her giriş için DBC'deki sinyali seçin (uçak mesajı sinyalleri). "
                             "Seçimler kaydedilir."))
        form = QFormLayout()
        self.combos: dict[str, QComboBox] = {}
        for d in INPUT_DEFS:
            cb = QComboBox()
            cb.addItem("— bağlı değil —", "")
            for s in sources:
                cb.addItem(f"{s.where}.{s.name}" + (f"  [{s.unit}]" if s.unit else ""), s.key)
            i = cb.findData(current.get(d.key, ""))
            cb.setCurrentIndex(i if i >= 0 else 0)
            self.combos[d.key] = cb
            form.addRow(f"{d.label}" + (f" [{d.unit}]" if d.unit else "") + ":", cb)
        holder = QWidget()
        holder.setLayout(form)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(holder)
        lay.addWidget(sc, 1)
        auto = QPushButton("İsme göre otomatik eşle (boş olanları)")
        auto.clicked.connect(self._auto)
        lay.addWidget(auto)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def _auto(self):
        for d in INPUT_DEFS:
            cb = self.combos[d.key]
            if cb.currentData():
                continue
            hit = auto_match(d.aliases, d.label, self._sources)
            if hit is not None:
                cb.setCurrentIndex(cb.findData(hit.key))

    def mapping(self) -> dict:
        return {k: cb.currentData() for k, cb in self.combos.items() if cb.currentData()}


_FALLBACK_DEFAULTS = {"ma": 0.0, "p_total": 1.013, "p_amb": 1.013, "t_amb": 15.0}


class SimInputsPanel(QFrame):
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
        self.setObjectName("simInputs")
        self.setStyleSheet("QFrame#simInputs { background:#FFFFFF; border:1px solid #EDF1F5; border-radius:10px; }")
        self._build()

    # ------------------------------------------------------------ yapı
    def _build(self):
        from app.ui.dashboard_tab import ToggleSwitch
        self._building = True
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(4)
        head = QHBoxLayout()
        t = QLabel("SİMÜLASYON GİRİŞLERİ")
        t.setStyleSheet("font-weight:800; color:#14202C; font-size:14px;")
        self.bind_button = QPushButton("⚙ Bağla")
        self.bind_button.setFixedHeight(24)
        self.bind_button.clicked.connect(self._open_mapping)
        head.addWidget(t, 1)
        head.addWidget(self.bind_button)
        root.addLayout(head)
        self.info_label = QLabel("")
        self.info_label.setStyleSheet("color:#A8231A; font-size:12px;")
        self.info_label.setWordWrap(True)
        root.addWidget(self.info_label)

        current_group = None
        switch_row = None
        self._group_titles: dict[str, QLabel] = {}
        for d in INPUT_DEFS:
            if d.group != current_group:
                current_group = d.group
                gh = QHBoxLayout()
                badge = QLabel(GROUP_LETTERS[d.group])
                badge.setFixedSize(20, 20)
                badge.setAlignment(Qt.AlignCenter)
                badge.setStyleSheet("background:#0E6E8C; color:#FFFFFF; border-radius:10px; font-weight:800; font-size:12px;")
                gl = QLabel(GROUP_TITLES[d.group])
                gl.setStyleSheet("color:#14202C; font-weight:700; font-size:13px;")
                gh.addWidget(badge)
                gh.addWidget(gl, 1)
                self._group_titles[d.group] = gl
                gw = QFrame()
                gw.setLayout(gh)
                gw.setStyleSheet("QFrame { border-bottom:1px solid #E3EAF1; margin-top:2px; }")
                root.addWidget(gw)
                if d.kind == "switch":
                    switch_row = QHBoxLayout()
                    root.addLayout(switch_row)
                elif d.kind == "const":
                    const_grid = QGridLayout()
                    const_grid.setHorizontalSpacing(10)
                    const_grid.setVerticalSpacing(4)
                    root.addLayout(const_grid)
                    const_i = 0
            if d.kind == "switch":
                cell = QVBoxLayout()
                cell.setAlignment(Qt.AlignHCenter)
                sw = ToggleSwitch()
                sw.toggled.connect(lambda checked, k=d.key: self._on_switch(k, checked))
                lbl = QLabel(d.label)
                lbl.setAlignment(Qt.AlignHCenter)
                lbl.setStyleSheet("font-weight:700; font-size:12px;")
                warn = QLabel("")
                warn.setAlignment(Qt.AlignHCenter)
                warn.setStyleSheet("color:#B9790F; font-size:11px;")
                onoff = QLabel("Off")
                onoff.setAlignment(Qt.AlignHCenter)
                onoff.setStyleSheet("color:#5B6B79; font-size:12px; font-weight:700;")
                sent = QLabel("")
                sent.setAlignment(Qt.AlignHCenter)
                sent.setStyleSheet("color:#8A99A8; font-size:11px;")
                sw.toggled.connect(lambda c, o=onoff: (o.setText("On" if c else "Off"),
                                                       o.setStyleSheet("color:%s; font-size:12px; font-weight:700;" %
                                                                       ("#1B8A4C" if c else "#5B6B79"))))
                cell.addWidget(onoff)
                cell.addWidget(sw, 0, Qt.AlignHCenter)
                cell.addWidget(lbl)
                sent.setVisible(False)
                cell.addWidget(sent)
                switch_row.addLayout(cell, 1)
                self._ctrl[d.key] = {"kind": "switch", "w": sw, "warn": warn, "label": lbl,
                                     "onoff": onoff, "sent": sent}
                continue
            entry = self._make_numeric(d)
            if d.note:                      # Alfa / Beta: tek satır, pasif
                if not getattr(self, "_note_row_done", False):
                    self._note_row_done = True
                    nl = QLabel("Alfa / Beta  —  şimdilik kullanılmıyor")
                    nl.setStyleSheet("color:#8A99A8; font-size:12px; font-style:italic; padding:2px 0;")
                    root.addWidget(nl)
                entry["w"].setParent(self)
                entry["w"].setVisible(False)
                if "slider" in entry:
                    entry["slider"].setParent(self)
                    entry["slider"].setVisible(False)
                self._ctrl[d.key] = entry
                continue
            if d.kind == "const":
                cell = QVBoxLayout()
                cell.setSpacing(1)
                cell.addWidget(entry["label"])
                cell.addWidget(entry["w"])
                const_grid.addLayout(cell, const_i // 2, const_i % 2)
                const_i += 1
            else:
                box = QVBoxLayout()
                box.setSpacing(1)
                row = QHBoxLayout()
                row.addWidget(entry["label"], 1)
                row.addWidget(entry["warn"])
                row.addWidget(entry["w"])
                box.addLayout(row)
                box.addWidget(entry["slider"])
                box.addLayout(self._scale_row(d.minimum, d.maximum))
                root.addLayout(box)
            self._ctrl[d.key] = entry

        btns = QHBoxLayout()
        self.send_all_button = QPushButton("Hepsini gönder")
        self.send_all_button.setProperty("primary", True)
        self.send_all_button.clicked.connect(self._send_all)
        self.reset_button = QPushButton("Varsayılana dön")
        self.reset_button.clicked.connect(self._reset)
        btns.addWidget(self.send_all_button)
        btns.addWidget(self.reset_button)
        root.addLayout(btns)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size:12px; color:#5B6B79;")
        root.addWidget(self.status_label)
        self._building = False
        for d in INPUT_DEFS:
            self._set_widget(d.key, self._initial(d.key))
        self._refresh_warn()

    def _make_numeric(self, d):
        txt = f"{d.label} [{d.unit}]" if d.unit else d.label
        if d.kind == "const":
            unit = f"{d.unit} · " if d.unit else ""
            txt = (f"{d.label}<br><span style='color:#6A7C8B; font-weight:500; font-size:10px;'>"
                   f"{unit}{d.minimum:g} – {d.maximum:g}</span>")
        name = QLabel(txt)
        name.setTextFormat(Qt.RichText)
        name.setWordWrap(True)
        name.setToolTip(f"{d.label} [{d.unit}]" if d.unit else d.label)
        name.setStyleSheet("font-weight:600; font-size:11px;")
        warn = QLabel("")
        warn.setStyleSheet("color:#B9790F; font-size:11px;")
        spin = no_wheel(QDoubleSpinBox())
        spin.setRange(d.minimum, d.maximum)
        spin.setDecimals(3 if d.kind == "const" else 1)
        spin.setSingleStep(0.1 if d.kind == "const" else 1.0)
        spin.setFixedWidth(88 if d.kind != "const" else 110)
        entry = {"kind": d.kind, "w": spin, "warn": warn, "label": name}
        if d.kind == "slider":
            sl = no_wheel(QSlider(Qt.Horizontal))
            sl.setRange(int(d.minimum * 10), int(d.maximum * 10))
            sl.sliderReleased.connect(lambda k=d.key: self._emit_one(k))
            sl.valueChanged.connect(lambda v, k=d.key: self._slider_moved(k, v))
            spin.editingFinished.connect(lambda k=d.key: self._spin_done(k))
            entry["slider"] = sl
        else:
            spin.editingFinished.connect(lambda k=d.key: self._emit_one(k))
        if not d.enabled:
            spin.setEnabled(False)
            if "slider" in entry:
                entry["slider"].setEnabled(False)
        return entry

    @staticmethod
    def _scale_row(minimum: float, maximum: float, n: int = 6):
        row = QHBoxLayout()
        row.setContentsMargins(4, 0, 4, 0)
        step = (maximum - minimum) / n
        for i in range(n + 1):
            lab = QLabel(f"{minimum + i * step:g}")
            lab.setStyleSheet("color:#6A7C8B; font-size:11px;")
            lab.setAlignment(Qt.AlignLeft if i == 0 else Qt.AlignRight if i == n else Qt.AlignHCenter)
            row.addWidget(lab, 1)
        return row

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
            c = self._ctrl.get(k, {})
            if "sent" in c:
                c["sent"].setVisible(True)
                c["sent"].setText("gönderiliyor…")
                c["sent"].setStyleSheet("color:#8A99A8; font-size:11px;")
        self.config.save()
        self.values_changed.emit(vals)

    def _send_all(self):
        keys = self.sendable_keys()
        if not keys:
            self.set_status("Bağlı giriş yok: ⚙ Bağla ile DBC sinyallerini seçin.", False)
            return
        self._emit({k: self.value_of(k) for k in keys})

    def _reset(self):
        for d in INPUT_DEFS:
            self._set_widget(d.key, self._default_of(d.key))
            self.config.input_values.pop(d.key, None)
        self.config.save()
        self.set_status("Değerler varsayılana döndü (gönderilmedi; göndermek için 'Hepsini gönder').", True)

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
        """Anahtarların altındaki 'Gönderildi' işaretini günceller."""
        for k in keys:
            c = self._ctrl.get(k, {})
            if "sent" in c:
                c["sent"].setVisible(True)
                c["sent"].setText("✓ Gönderildi" if ok else "✕ Gönderilemedi")
                c["sent"].setStyleSheet(f"color:{'#1B8A4C' if ok else '#A8231A'}; font-size:11px; font-weight:600;")

    def set_status(self, text: str, ok: bool):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"font-size:12px; color:{'#1B8A4C' if ok else '#A8231A'};")

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

    def _refresh_warn(self):
        missing = []
        for d in INPUT_DEFS:
            c = self._ctrl[d.key]
            bound = self.mapped(d.key) is not None
            show = bool(self._sources)  # DBC hiç yokken satır satır uyarı yok; tek banner
            c["warn"].setText("" if (bound or not d.enabled or not show) else "⚠ bağlı değil")
            if d.kind != "switch" and d.enabled:
                c["label"].setStyleSheet("font-weight:600; font-size:12px;" +
                                         ("" if (bound or not show) else " color:#B9790F;"))
            tip = (f"{self.config.input_map.get(d.key, '')}" if bound else
                   "DBC sinyali bağlı değil — ⚙ Bağla")
            c["w"].setToolTip(tip)
            if d.enabled and not bound:
                missing.append(d.label)
        cyc = ""
        m = self.mapped("altitude")
        msg = self._dbc.get_message(m[0]) if (m and self._dbc is not None) else None
        ct = getattr(msg, "cycle_time", None) if msg is not None else None
        cyc = f"   ·   CAN {ct} ms periyodik" if ct else ("   ·   CAN periyodik" if m else "")
        self._group_titles["aircraft"].setText(GROUP_TITLES["aircraft"] + cyc)
        if not self._sources:
            self.info_label.setText("DBC yüklenmedi (CAN Monitor → DBC).")
        elif missing:
            self.info_label.setText(f"{len(missing)} giriş DBC sinyaline bağlı değil: ⚙ Bağla")
        else:
            self.info_label.setText("")
        self.info_label.setVisible(bool(self.info_label.text()))

    def _open_mapping(self):
        dlg = _MappingDialog(self._sources, self.config.input_map, self)
        if dlg.exec() == QDialog.Accepted:
            self.config.input_map = dlg.mapping()
            self.config.save()
            self._refresh_warn()
