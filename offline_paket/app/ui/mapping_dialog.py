"""⚙ Eşleşmeler penceresi: girişler, sensörler, eyleyiciler ve motor komutları için
sinyal/değişken eşleşmeleri.

Sensörler ve eyleyiciler için her satırda üç/iki ayrı eşleşme vardır:
  * Değer      — örn. ``clbc_Fuel_pump_dc_perc``
  * Anahtar    — örn. ``clbc_Fuel_pump_dc_perc_sw`` (1 iken değer değiştirilebilir)
  * Arıza (yalnız sensör, isteğe bağlı) — ≠0 ise sensör arızalı
Her eşleşmenin kaynağı bağımsız olarak CAN (DBC mesaj.sinyal) ya da A2L (değişken adı)
seçilir.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QDialog, QDialogButtonBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from app.dashboard_config import (
    ACTUATOR_KEYS, ACTUATOR_LABELS, MOTOR_COMMAND_KEYS, MOTOR_COMMAND_LABELS, SENSOR_KEYS,
    SENSOR_LABELS, SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, MotorCommand, SignalMap,
)
from app.sim_interface import INPUT_DEFS, auto_match


def a2l_names(summary) -> list:
    if summary is None:
        return []
    names = [m.name for m in summary.measurements] + [c.name for c in summary.characteristics]
    return sorted(dict.fromkeys(names), key=str.lower)


def dbc_signal_names(dbc) -> list:
    """['MESAJ.SİNYAL', ...] — yüklü DBC'den."""
    cdb = getattr(dbc, "_db", None) if dbc is not None else None
    if cdb is None:
        return []
    return [f"{m.name}.{s.name}" for m in cdb.messages for s in m.signals]


def split_can(text: str) -> tuple:
    text = (text or "").strip()
    if "." in text:
        msg, sig = text.split(".", 1)
        return msg.strip(), sig.strip()
    return "", text


def find_companion(name: str, source: str, pool: list, suffix: str = "_sw") -> str | None:
    """``X`` için aynı kaynakta ``X_sw`` değişkenini (büyük/küçük harf duyarsız) bulur."""
    want = (name + suffix).lower()
    for n in pool:
        base = n.split(".", 1)[1] if source == SOURCE_CAN and "." in n else n
        if (n if source == SOURCE_A2L else base).lower() == want or n.lower() == want:
            return n
    # CAN: aynı MESAJ içinde olması şart değil; yalnız sinyal adına bak
    if source == SOURCE_CAN:
        for n in pool:
            if n.split(".", 1)[-1].lower() == (name.split(".", 1)[-1] + suffix).lower():
                return n
    return None


class BindingEditor(QWidget):
    """Kaynak seçici (CAN/A2L) + sinyal/değişken seçici (aranabilir, serbest metin)."""

    def __init__(self, dbc_names: list, a2l: list, allow_a2l: bool = True, parent=None):
        super().__init__(parent)
        self._dbc_names, self._a2l = dbc_names, a2l
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.source = QComboBox()
        self.source.addItem("CAN", SOURCE_CAN)
        if allow_a2l:
            self.source.addItem("A2L", SOURCE_A2L)
        self.source.setFixedWidth(62)
        self.source.currentIndexChanged.connect(self._reload)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setInsertPolicy(QComboBox.NoInsert)
        self.name.setMinimumWidth(190)
        lay.addWidget(self.source)
        lay.addWidget(self.name, 1)
        self._reload()

    def _pool(self) -> list:
        return self._a2l if self.source.currentData() == SOURCE_A2L else self._dbc_names

    def _reload(self, *_):
        cur = self.name.currentText()
        self.name.blockSignals(True)
        self.name.clear()
        self.name.addItem("")
        self.name.addItems(self._pool())
        comp = QCompleter(self._pool(), self.name)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.name.setCompleter(comp)
        self.name.setCurrentText(cur)
        self.name.blockSignals(False)
        self.name.lineEdit().setPlaceholderText(
            "değişken adı" if self.source.currentData() == SOURCE_A2L else "MESAJ.SİNYAL")

    def set_binding(self, b: Binding):
        i = self.source.findData(b.source)
        self.source.blockSignals(True)
        self.source.setCurrentIndex(max(i, 0))
        self.source.blockSignals(False)
        self._reload()
        self.name.setCurrentText(b.text)

    def binding(self) -> Binding:
        text = self.name.currentText().strip()
        if self.source.currentData() == SOURCE_A2L:
            return Binding(SOURCE_A2L, a2l_name=text)
        msg, sig = split_can(text)
        return Binding(SOURCE_CAN, msg, sig)

    def text(self) -> str:
        return self.name.currentText().strip()

    def source_kind(self) -> str:
        return self.source.currentData()


def _scroll(widget: QWidget) -> QScrollArea:
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QScrollArea.NoFrame)
    sc.setWidget(widget)
    return sc


class MappingDialog(QDialog):
    def __init__(self, config: DashboardConfig, sim_panel, dbc, a2l_summary, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Eşleşmeler — CAN (DBC) / A2L")
        self.resize(1180, 720)
        self._cfg = config
        self._sim = sim_panel
        self._dbc_names = dbc_signal_names(dbc)
        self._a2l = a2l_names(a2l_summary)

        root = QVBoxLayout(self)
        info = QLabel(
            "Her sensör ve eyleyici için <b>Değer</b> ve <b>Anahtar (_sw)</b> eşleşmesi ayrı ayrı "
            "CAN (DBC) ya da A2L olarak seçilir. Anahtar 1 iken değer arayüzden değiştirilebilir, "
            "0 iken değiştirilemez."
            + ("" if self._dbc_names else "  <span style='color:#B9790F'>DBC yüklü değil.</span>")
            + ("" if self._a2l else "  <span style='color:#B9790F'>A2L yüklü değil.</span>"))
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        root.addWidget(info)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.sensor_ed: dict = {}
        self.actuator_ed: dict = {}
        self.motor_ed: dict = {}
        self.input_ed: dict = {}
        self.tabs.addTab(self._build_signalmap_tab(
            SENSOR_KEYS, SENSOR_LABELS, self.sensor_ed, with_fault=True), "Sensörler")
        self.tabs.addTab(self._build_signalmap_tab(
            ACTUATOR_KEYS, ACTUATOR_LABELS, self.actuator_ed, with_fault=False), "Eyleyiciler")
        self.tabs.addTab(self._build_motor_tab(), "Motor Komutları")
        self.tabs.addTab(self._build_inputs_tab(), "Girişler (Uçuş / Motor Kontrol)")

        btns = QHBoxLayout()
        auto = QPushButton("_sw'yi isimden otomatik bul (boş olanlar)")
        auto.clicked.connect(self._auto_sw)
        btns.addWidget(auto)
        btns.addStretch(1)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Kaydet")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        btns.addWidget(bb)
        root.addLayout(btns)

    # ------------------------------------------------------------ sekmeler
    def _head(self, grid: QGridLayout, texts: list):
        for c, t in enumerate(texts):
            lab = QLabel(f"<b>{t}</b>")
            lab.setTextFormat(Qt.RichText)
            grid.addWidget(lab, 0, c)

    def _build_signalmap_tab(self, keys, labels, store: dict, with_fault: bool) -> QWidget:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        heads = ["", "Değer", "Anahtar (_sw)"] + (["Arıza (isteğe bağlı, ≠0 = arıza)"] if with_fault else [])
        self._head(grid, heads)
        src = self._cfg.sensors if with_fault else self._cfg.actuators
        for r, key in enumerate(keys, start=1):
            smap: SignalMap = src.get(key, SignalMap())
            grid.addWidget(QLabel(labels[key]), r, 0)
            ed = {"value": BindingEditor(self._dbc_names, self._a2l),
                  "sw": BindingEditor(self._dbc_names, self._a2l)}
            ed["value"].set_binding(smap.value)
            ed["sw"].set_binding(smap.sw)
            grid.addWidget(ed["value"], r, 1)
            grid.addWidget(ed["sw"], r, 2)
            if with_fault:
                ed["fault"] = BindingEditor(self._dbc_names, self._a2l)
                ed["fault"].set_binding(smap.fault)
                grid.addWidget(ed["fault"], r, 3)
            store[key] = ed
        for c in range(1, len(heads)):
            grid.setColumnStretch(c, 1)
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.addLayout(grid)
        v.addStretch(1)
        return _scroll(holder)

    def _build_motor_tab(self) -> QWidget:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        self._head(grid, ["", "Komut (CAN veya A2L)", "Gönderilecek değer"])
        for r, key in enumerate(MOTOR_COMMAND_KEYS, start=1):
            cmd: MotorCommand = getattr(self._cfg, key)
            grid.addWidget(QLabel(MOTOR_COMMAND_LABELS[key]), r, 0)
            be = BindingEditor(self._dbc_names, self._a2l)
            be.set_binding(cmd.binding)
            val = QDoubleSpinBox()
            val.setRange(-1e9, 1e9)
            val.setDecimals(3)
            val.setValue(cmd.value)
            val.setFixedWidth(110)
            grid.addWidget(be, r, 1)
            grid.addWidget(val, r, 2)
            self.motor_ed[key] = (be, val)
        grid.setColumnStretch(1, 1)
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.addLayout(grid)
        v.addStretch(1)
        return _scroll(holder)

    def _build_inputs_tab(self) -> QWidget:
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(6)
        self._head(grid, ["", "DBC sinyali (CAN hattından gönderilir)", ""])
        sources = {s.key: s for s in self._sim.sources()}
        auto_btn = QPushButton("İsme göre otomatik eşle (boş olanlar)")
        auto_btn.clicked.connect(self._auto_inputs)
        grid.addWidget(auto_btn, 0, 2)
        for r, d in enumerate(INPUT_DEFS, start=1):
            grid.addWidget(QLabel(d.display + (f"  [{d.unit}]" if d.unit else "")), r, 0)
            be = BindingEditor(self._dbc_names, [], allow_a2l=False)
            cur = self._sim.config.input_map.get(d.key, "")
            s = sources.get(cur)
            if s is not None:
                be.set_binding(Binding(SOURCE_CAN, s.where, s.name))
            elif cur.startswith("dbc:") and "." in cur:
                m, sg = cur[4:].split(".", 1)
                be.set_binding(Binding(SOURCE_CAN, m, sg))
            grid.addWidget(be, r, 1)
            self.input_ed[d.key] = be
        grid.setColumnStretch(1, 1)
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.addLayout(grid)
        v.addStretch(1)
        return _scroll(holder)

    # ------------------------------------------------------------ otomatik
    def _auto_sw(self):
        """Değeri girilmiş ama anahtarı boş olanlar için aynı kaynakta ``<ad>_sw`` bulur."""
        for store in (self.sensor_ed, self.actuator_ed):
            for ed in store.values():
                if ed["sw"].text() or not ed["value"].text():
                    continue
                kind = ed["value"].source_kind()
                pool = self._a2l if kind == SOURCE_A2L else self._dbc_names
                hit = find_companion(ed["value"].text(), kind, pool)
                if hit is not None:
                    b = Binding(SOURCE_A2L, a2l_name=hit) if kind == SOURCE_A2L else Binding(SOURCE_CAN, *split_can(hit))
                    ed["sw"].set_binding(b)

    def _auto_inputs(self):
        sources = self._sim.sources()
        for d in INPUT_DEFS:
            be = self.input_ed[d.key]
            if be.text():
                continue
            hit = auto_match(d.aliases, d.label, sources)
            if hit is not None:
                be.set_binding(Binding(SOURCE_CAN, hit.where, hit.name))

    # ------------------------------------------------------------ sonuç
    def result_config(self) -> DashboardConfig:
        cfg = DashboardConfig()
        cfg.graph_signals = list(self._cfg.graph_signals)
        for key, ed in self.sensor_ed.items():
            cfg.sensors[key] = SignalMap(value=ed["value"].binding(), sw=ed["sw"].binding(),
                                         fault=ed["fault"].binding())
        for key, ed in self.actuator_ed.items():
            cfg.actuators[key] = SignalMap(value=ed["value"].binding(), sw=ed["sw"].binding())
        for key, (be, val) in self.motor_ed.items():
            setattr(cfg, key, MotorCommand(binding=be.binding(), value=float(val.value())))
        return cfg

    def accept(self):
        # giriş (uçuş / motor kontrol) eşleşmeleri SimConfig'te tutulur
        new_map = {}
        for key, be in self.input_ed.items():
            b = be.binding()
            if b.is_set:
                new_map[key] = f"dbc:{b.message}.{b.signal}"
        self._sim.config.input_map = new_map
        self._sim.config.save()
        self._sim.refresh_sources()
        super().accept()
