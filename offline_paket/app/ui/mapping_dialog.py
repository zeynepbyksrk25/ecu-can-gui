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
    QComboBox, QCompleter, QDialog, QFrame, QGridLayout, QHBoxLayout,
    QLabel, QPushButton, QScrollArea, QTabWidget, QVBoxLayout, QWidget,
)

from app import theme
from app.dashboard_config import (
    ACTUATOR_LABELS, CONTROL_KEYS, EYLEYICI_KEYS, MODE_KEYS, MOTOR_COMMAND_KEYS, MOTOR_COMMAND_LABELS, SENSOR_KEYS,
    SENSOR_LABELS, SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, MotorCommand, SignalMap,
)
from app.sim_interface import FLIGHT_DEFS, auto_match
from app.ui.dark_theme import dark_qss
from app.ui.dash_widgets import DK_CYAN, IconLabel


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
        self.source.setFixedWidth(68)
        self.source.currentIndexChanged.connect(self._reload)
        self.name = QComboBox()
        self.name.setEditable(True)
        self.name.setInsertPolicy(QComboBox.NoInsert)
        self.name.setMinimumWidth(110)
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


def _card(title: str, icon: str) -> tuple:
    """(kart, ızgara, başlık satırı): Ana Sayfa kartlarıyla aynı görünüm."""
    card = QFrame()
    card.setObjectName("card")
    v = QVBoxLayout(card)
    v.setContentsMargins(14, 8, 14, 10)
    v.setSpacing(6)
    head = QHBoxLayout()
    head.setSpacing(8)
    head.addWidget(IconLabel(icon, DK_CYAN, 18))
    t = QLabel(title.upper())
    t.setObjectName("cardTitle")
    head.addWidget(t)
    head.addStretch(1)
    v.addLayout(head)
    grid = QGridLayout()
    grid.setHorizontalSpacing(12)
    grid.setVerticalSpacing(4)
    v.addLayout(grid)
    v.addStretch(1)
    return card, grid, head


def _col_head(text: str) -> QLabel:
    lab = QLabel(text.upper())
    lab.setObjectName("colHead")
    return lab


def _row_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("rowName")
    return lab


class MappingDialog(QDialog):
    """Koyu temalı, 2 sekmeli Eşleşmeler penceresi.

    * **Sinyaller**: Sensörler (Değer / Anahtar / Arıza) tam genişlikte; altında yan yana
      Eyleyiciler ve Motor Kontrol (ikisi de Değer / Anahtar, CAN ya da A2L); en altta Motor Komutları
      (Komut + Değer + isteğe bağlı Anahtar).
    * **Uçuş Koşulları**: uçaktan gelen girişlerin kaynağı (CAN: DBC sinyali ya da A2L: CCP değişkeni).
    """

    def __init__(self, config: DashboardConfig, sim_panel, dbc, a2l_summary, parent=None):
        super().__init__(parent)
        self.setObjectName("mappingDialog")
        self.setWindowTitle("Eşleşmeler — CAN (DBC) / A2L")
        self.setStyleSheet(theme.paint("QDialog#mappingDialog { background: @@BG@@; }"))
        from PySide6.QtGui import QGuiApplication
        screen = QGuiApplication.primaryScreen()
        avail_h = screen.availableGeometry().height() if screen is not None else 800
        self.resize(1180, min(720, int(avail_h * 0.92)))      # ekrana sığmazsa içerik kaydırılır
        self.setMinimumSize(1000, 520)
        self._cfg = config
        self._sim = sim_panel
        self._dbc_names = dbc_signal_names(dbc)
        self._a2l = a2l_names(a2l_summary)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        body.setObjectName("mapBody")
        body.setStyleSheet(dark_qss("mapBody"))
        outer.addWidget(body)
        root = QVBoxLayout(body)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)

        warn = ""
        if not self._dbc_names:
            warn += f"   <span style='color:{theme.WARN_INK}'>⚠ DBC yüklü değil.</span>"
        if not self._a2l:
            warn += f"   <span style='color:{theme.WARN_INK}'>⚠ A2L yüklü değil.</span>"
        info = QLabel(
            "Sensör, Motor Kontrol ve Motor Komutları için yalnızca <b>Değer</b> (komutlarda <b>Komut</b>) seçilir; "
            "<b>Anahtar (_sw)</b> yalnızca <b>Eyleyicilerde</b> vardır (anahtar 1 iken değer değiştirilebilir, 0 iken "
            "değiştirilemez). Motor komutları basılınca eşlenen sinyale doğrudan 1 yazar. "
            "CAN için ad <b>MESAJ.SİNYAL</b> biçimindedir; kutunun solundaki kutudan CAN/A2L seçin." + warn)
        info.setObjectName("mutedSmall")
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        root.addWidget(info)

        self.sensor_ed: dict = {}
        self.actuator_ed: dict = {}
        self.control_ed: dict = {}
        self.motor_ed: dict = {}
        self.input_ed: dict = {}

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_signals_tab(), "Sinyaller")
        self.tabs.addTab(self._build_inputs_tab(), "Uçuş Koşulları")
        root.addWidget(self.tabs, 1)

        bar = QHBoxLayout()
        bar.setSpacing(8)
        auto = QPushButton("Eyleyicilerin _sw'sini isimden otomatik bul (boş olanlar)")
        auto.setProperty("compact", True)
        auto.clicked.connect(self._auto_sw)
        bar.addWidget(auto)
        bar.addStretch(1)
        cancel = QPushButton("Vazgeç")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Kaydet")
        save.setProperty("tone", "go")
        save.setDefault(True)
        save.clicked.connect(self.accept)
        bar.addWidget(cancel)
        bar.addWidget(save)
        root.addLayout(bar)

    # ------------------------------------------------------------ sekmeler
    def _editor(self, binding: Binding, allow_a2l: bool = True) -> BindingEditor:
        ed = BindingEditor(self._dbc_names, self._a2l if allow_a2l else [], allow_a2l=allow_a2l)
        ed.set_binding(binding)
        return ed

    def _build_signals_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)

        # ---- Sensörler (tam genişlik)
        card, grid, _h = _card("Sensörler", "gauge")
        for c, t in enumerate(("", "Değer", "Arıza biti (isteğe bağlı, ≠0 = arıza)")):
            grid.addWidget(_col_head(t), 0, c)
        for r, key in enumerate(SENSOR_KEYS, start=1):
            smap = self._cfg.sensors.get(key, SignalMap())
            grid.addWidget(_row_label(SENSOR_LABELS[key]), r, 0)
            ed = {"value": self._editor(smap.value), "fault": self._editor(smap.fault)}
            for c, name in enumerate(("value", "fault"), start=1):
                grid.addWidget(ed[name], r, c)
            if key in MODE_KEYS:                     # Mod satırlarında arıza biti yok
                ed["fault"].setVisible(False)
            self.sensor_ed[key] = ed
        grid.setColumnMinimumWidth(0, 150)
        for c in (1, 2):
            grid.setColumnStretch(c, 1)
        v.addWidget(card)

        # ---- Eyleyiciler | Motor Komutları (yan yana)
        row = QHBoxLayout()
        row.setSpacing(10)
        card, grid, _h = _card("Eyleyiciler", "actuator")
        for c, t in enumerate(("", "Değer", "Anahtar (_sw)")):
            grid.addWidget(_col_head(t), 0, c)
        for r, key in enumerate(EYLEYICI_KEYS, start=1):
            smap = self._cfg.actuators.get(key, SignalMap())
            grid.addWidget(_row_label(ACTUATOR_LABELS[key]), r, 0)
            ed = {"value": self._editor(smap.value), "sw": self._editor(smap.sw)}
            grid.addWidget(ed["value"], r, 1)
            grid.addWidget(ed["sw"], r, 2)
            self.actuator_ed[key] = ed
        grid.setColumnMinimumWidth(0, 140)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(2, 1)
        row.addWidget(card, 1)

        # Motor Kontrol: CAN ya da A2L DEĞER eşlemesi. Switch (_sw) YOKTUR (yalnızca Eyleyicilerde var).
        card, grid, _h = _card("Motor Kontrol", "sliders")
        for c, t in enumerate(("", "Değer")):
            grid.addWidget(_col_head(t), 0, c)
        for r, key in enumerate(CONTROL_KEYS, start=1):
            smap = self._cfg.actuators.get(key, SignalMap())
            grid.addWidget(_row_label(ACTUATOR_LABELS[key]), r, 0)
            ed = {"value": self._editor(smap.value)}
            grid.addWidget(ed["value"], r, 1)
            self.control_ed[key] = ed
        grid.setColumnMinimumWidth(0, 140)
        grid.setColumnStretch(1, 1)
        row.addWidget(card, 1)
        v.addLayout(row)

        # Motor Komutları (Başlat / Durdur / Acil Durdurma): yalnızca komut sinyali/değişkeni. Değer ve Switch YOK:
        # düğmeye basınca eşlenen sinyale doğrudan 1 yazılır.
        card, grid, _h = _card("Motor Komutları", "play")
        for c, t in enumerate(("", "Komut (CAN ya da A2L) — basınca doğrudan çalışır")):
            grid.addWidget(_col_head(t), 0, c)
        for r, key in enumerate(MOTOR_COMMAND_KEYS, start=1):
            cmd: MotorCommand = getattr(self._cfg, key)
            grid.addWidget(_row_label(MOTOR_COMMAND_LABELS[key]), r, 0)
            be = self._editor(cmd.binding)
            grid.addWidget(be, r, 1)
            self.motor_ed[key] = be
        grid.setColumnMinimumWidth(0, 140)
        grid.setColumnStretch(1, 2)
        v.addWidget(card)
        v.addStretch(1)
        return _scroll(page)

    def _build_inputs_tab(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 8, 0, 0)
        v.setSpacing(10)
        sources = {s.key: s for s in self._sim.sources()}

        top = QHBoxLayout()
        lab = QLabel("Girişler CAN hattından (DBC sinyali) ya da CCP ile A2L değişkenine gönderilir.")
        lab.setObjectName("mutedSmall")
        auto = QPushButton("İsme göre otomatik eşle (boş olanlar)")
        auto.setProperty("compact", True)
        auto.clicked.connect(self._auto_inputs)
        top.addWidget(lab)
        top.addStretch(1)
        top.addWidget(auto)
        v.addLayout(top)

        row = QHBoxLayout()
        row.setSpacing(10)
        for title, icon, group in (("Uçuş Koşulları", "plane", "aircraft"),):
            card, grid, _h = _card(title, icon)
            grid.setVerticalSpacing(12)           # az satırlı sekme daha ferah dursun
            grid.addWidget(_col_head(""), 0, 0)
            grid.addWidget(_col_head("DBC sinyali / A2L değişkeni"), 0, 1)
            r = 1
            for d in FLIGHT_DEFS:
                if d.group != group:
                    continue
                grid.addWidget(_row_label(d.display + (f"  [{d.unit}]" if d.unit else "")), r, 0)
                be = BindingEditor(self._dbc_names, self._a2l)
                cur = self._sim.config.input_map.get(d.key, "")
                src = sources.get(cur)
                if cur.startswith("a2l:"):
                    be.set_binding(Binding(SOURCE_A2L, a2l_name=cur[4:]))
                elif src is not None:
                    be.set_binding(Binding(SOURCE_CAN, src.where, src.name))
                elif cur.startswith("dbc:") and "." in cur:
                    m, sg = cur[4:].split(".", 1)
                    be.set_binding(Binding(SOURCE_CAN, m, sg))
                grid.addWidget(be, r, 1)
                self.input_ed[d.key] = be
                r += 1
            grid.setColumnMinimumWidth(0, 150)
            grid.setColumnStretch(1, 1)
            row.addWidget(card, 1)
        v.addLayout(row)
        v.addStretch(1)
        return _scroll(page)

    # ------------------------------------------------------------ otomatik
    def _auto_sw(self):
        """Değeri girilmiş ama anahtarı boş olanlar için aynı kaynakta ``<ad>_sw`` bulur. YALNIZCA Eyleyicilerde
        switch vardır (sensör, Motor Kontrol ve Motor Komutları'nda yoktur). Yalnızca ANAHTAR aranır."""
        for store in (self.actuator_ed.values(),):                   # switch YALNIZCA Eyleyicilerde
            for ed in store:
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
        for d in FLIGHT_DEFS:
            be = self.input_ed[d.key]
            if be.text():
                continue
            dbc_src = [s for s in sources if not s.key.startswith("a2l:")]
            a2l_src = [s for s in sources if s.key.startswith("a2l:")]
            hit = auto_match(d.aliases, d.label, dbc_src)
            if hit is not None:
                be.set_binding(Binding(SOURCE_CAN, hit.where, hit.name))
                continue
            hit = auto_match(d.aliases, d.label, a2l_src)
            if hit is not None:
                be.set_binding(Binding(SOURCE_A2L, a2l_name=hit.name))

    # ------------------------------------------------------------ sonuç
    def result_config(self) -> DashboardConfig:
        cfg = DashboardConfig()
        cfg.graph_signals = list(self._cfg.graph_signals)
        for key, ed in self.sensor_ed.items():
            cfg.sensors[key] = SignalMap(value=ed["value"].binding(), fault=ed["fault"].binding())
        for key, ed in self.actuator_ed.items():
            cfg.actuators[key] = SignalMap(value=ed["value"].binding(), sw=ed["sw"].binding())
        for key, ed in self.control_ed.items():
            cfg.actuators[key] = SignalMap(value=ed["value"].binding())
        for key, be in self.motor_ed.items():
            setattr(cfg, key, MotorCommand(binding=be.binding()))
        return cfg

    def accept(self):
        # uçuş koşulları eşleşmeleri SimConfig'te tutulur (Motor Kontrol artık DashboardConfig'te)
        new_map = {}
        for key, be in self.input_ed.items():
            b = be.binding()
            if b.is_set:
                new_map[key] = f"a2l:{b.a2l_name}" if b.source == SOURCE_A2L else f"dbc:{b.message}.{b.signal}"
        self._sim.config.input_map = new_map
        self._sim.config.save()
        self._sim.refresh_sources()
        super().accept()
