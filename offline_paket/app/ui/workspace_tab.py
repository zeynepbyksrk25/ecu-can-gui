"""Çalışma Alanı (Concerto / Data Inspector tarzı) sayfası.

  - Serbest yerleşim: grafik, gösterge, tablo ve kontrol pencereleri sürüklenip
    boyutlandırılır (QMdiArea); "Döşe" / "Kademeli" ile otomatik düzenlenir.
  - Yerleşimler isimle kaydedilir/yüklenir; son düzen otomatik hatırlanır.
  - Sinyal tarayıcı: A2L ölçümleri (CCP), DBC sinyalleri (CAN), göstergeler,
    girişler, matematik sinyalleri ve içe aktarılan kayıtlar — "İsme göre ara...".
  - Dondur: ekran sabitlenir, veri arka planda kaydedilmeye devam eder.
  - Matematik sinyalleri: ölçekle (a·x+b), A+B / A−B / A×B / A÷B, hareketli ortalama.

Gerçek CCP okuması / CAN gönderimi burada YAPILMAZ; MainWindow'a sinyal verilir
(read_requested, send_input) ve veri push() / on_can_frame() ile geri beslenir.
"""
from __future__ import annotations

import json
import os

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCompleter, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
    QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMdiArea, QMdiSubWindow,
    QMenu, QMessageBox, QPushButton, QSplitter, QStackedWidget, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.signal_hub import OP_LABELS, SignalHub, kind_of, label_of
from app.ui.workspace_panels import ControlPanel, GaugePanel, PlotPanel, TablePanel

ROLE_ID = Qt.UserRole + 1
PANEL_TYPES = {"plot": PlotPanel, "gauge": GaugePanel, "table": TablePanel, "control": ControlPanel}
DEFAULT_SIZES = {"plot": (720, 520), "gauge": (290, 300), "table": (460, 260), "control": (320, 360)}
SPANS = [("10 sn", 10.0), ("30 sn", 30.0), ("60 sn", 60.0), ("2 dk", 120.0),
         ("5 dk", 300.0), ("10 dk", 600.0), ("Tümü", None)]
GROUPS = [("a2l", "A2L ölçümleri"), ("dbc", "DBC sinyalleri"), ("gauge", "Göstergeler"),
          ("input", "Girişler"), ("math", "Matematik sinyalleri"), ("csv", "İçe aktarılan kayıtlar")]
LAST = "_son"


class WorkspaceLayoutStore:
    """{"layouts": {isim: durum}, "last": durum} — JSON, hatada sessizce boş döner."""

    def __init__(self, path: str):
        self.path = path

    def _read(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                data.setdefault("layouts", {})
                return data
        except (OSError, ValueError):
            pass
        return {"layouts": {}}

    def _write(self, data: dict):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
        except OSError:
            pass

    def names(self) -> list:
        return sorted(self._read()["layouts"])

    def get(self, name: str):
        return self._read()["layouts"].get(name)

    def save(self, name: str, state: dict):
        d = self._read()
        d["layouts"][name] = state
        self._write(d)

    def delete(self, name: str):
        d = self._read()
        d["layouts"].pop(name, None)
        self._write(d)

    def last(self):
        return self._read().get("last")

    def save_last(self, state: dict):
        d = self._read()
        d["last"] = state
        self._write(d)


def _apply_mdi_palette():
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication
    pal = QPalette()
    for grp in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
        pal.setColor(grp, QPalette.Highlight, QColor("#1b4a73"))
        pal.setColor(grp, QPalette.HighlightedText, QColor("#ffffff"))
        pal.setColor(grp, QPalette.Window, QColor("#16304d"))
        pal.setColor(grp, QPalette.Button, QColor("#16304d"))
        pal.setColor(grp, QPalette.WindowText, QColor("#cfe0f1"))
        pal.setColor(grp, QPalette.ButtonText, QColor("#cfe0f1"))
        pal.setColor(grp, QPalette.Text, QColor("#cfe0f1"))
        pal.setColor(grp, QPalette.Base, QColor("#0f2034"))
    QApplication.setPalette(pal, "QMdiSubWindow")


class _Sub(QMdiSubWindow):
    closed = Signal(object)

    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        from PySide6.QtGui import QIcon
        self.setWindowIcon(QIcon())

    def showEvent(self, ev):  # noqa: N802
        # başlık çubuğu rengi: stil sayfası paleti ezdiği için gösterimde uygula
        from PySide6.QtGui import QPalette
        pal = self.palette()
        for grp in (QPalette.Active, QPalette.Inactive):
            pal.setColor(grp, QPalette.Highlight, QColor("#1b4a73"))
            pal.setColor(grp, QPalette.HighlightedText, QColor("#ffffff"))
            pal.setColor(grp, QPalette.Window, QColor("#2a4a6b"))
            pal.setColor(grp, QPalette.WindowText, QColor("#ffffff"))
            pal.setColor(grp, QPalette.Text, QColor("#ffffff"))
        self.setPalette(pal)
        super().showEvent(ev)

    def closeEvent(self, ev):  # noqa: N802
        self.closed.emit(self)
        super().closeEvent(ev)


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
        self.error.setStyleSheet("color:#ff6b6b;")
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


class WorkspaceTab(QWidget):
    read_requested = Signal(list)       # CCP ile okunacak A2L ölçüm adları
    send_input = Signal(str, float)     # Kontrol paneli -> Simülasyon Girişleri

    def __init__(self, store: WorkspaceLayoutStore | None = None, hub: SignalHub | None = None):
        super().__init__()
        self.hub = hub or SignalHub()
        self.store = store
        self.frozen = False
        self._panels: list = []
        self._subs: dict = {}
        self._counter = {k: 0 for k in PANEL_TYPES}
        self._a2l_names: list[str] = []
        self._dbc = None
        self._dbc_map: dict = {}
        self._input_values: dict = {}
        self._input_defs = []
        self._tick_n = 0
        self._last_saved = None
        self._loading = False

        from app.sim_interface import INPUT_DEFS
        self._input_defs = INPUT_DEFS

        # ---------------- araç çubuğu
        self.layout_combo = QComboBox()
        self.layout_combo.setMinimumWidth(170)
        self.layout_combo.setToolTip("Kayıtlı yerleşimler — seçince yüklenir")
        self.layout_combo.activated.connect(self._on_layout_chosen)
        b_save = QPushButton("Yerleşimi kaydet")
        b_save.clicked.connect(self._on_save_layout)
        b_del = QPushButton("Sil")
        b_del.clicked.connect(self._on_delete_layout)
        self.freeze_btn = QPushButton("⏸  Dondur")
        self.freeze_btn.setCheckable(True)
        self.freeze_btn.setToolTip("Ekranı dondurur; veri arka planda kaydedilmeye devam eder. "
                                   "Dondurunca fareyle yakınlaştırıp kaydırabilirsiniz.")
        self.freeze_btn.toggled.connect(self._on_freeze)
        self.state_label = QLabel("")
        self.span_combo = QComboBox()
        for lab, _v in SPANS:
            self.span_combo.addItem(lab)
        self.span_combo.setCurrentIndex(1)
        self.span_combo.setToolTip("Canlı akışta görünen zaman penceresi")
        self.span_combo.currentIndexChanged.connect(lambda _i: self._mark_dirty())
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Yerleşim:"))
        row1.addWidget(self.layout_combo)
        row1.addWidget(b_save)
        row1.addWidget(b_del)
        row1.addSpacing(14)
        row1.addWidget(self.freeze_btn)
        row1.addWidget(self.state_label)
        row1.addSpacing(14)
        row1.addWidget(QLabel("Pencere:"))
        row1.addWidget(self.span_combo)
        row1.addStretch()

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Ekle:"))
        for kind, text in (("plot", "+ Grafik"), ("gauge", "+ Gösterge"),
                           ("table", "+ Tablo"), ("control", "+ Kontrol")):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, k=kind: self.add_panel(k))
            row2.addWidget(b)
        b_math = QPushButton("ƒ Matematik sinyali…")
        b_math.clicked.connect(self._on_new_math)
        row2.addSpacing(10)
        row2.addWidget(b_math)
        row2.addSpacing(10)
        b_tile = QPushButton("Döşe")
        b_tile.clicked.connect(lambda: self.mdi.tileSubWindows())
        b_casc = QPushButton("Kademeli")
        b_casc.clicked.connect(lambda: self.mdi.cascadeSubWindows())
        row2.addWidget(b_tile)
        row2.addWidget(b_casc)
        row2.addSpacing(10)
        b_clear = QPushButton("Kaydı temizle")
        b_clear.setToolTip("Toplanan canlı veriyi siler ve zamanı 0'a sıfırlar (tanımlar kalır).")
        b_clear.clicked.connect(self._on_clear)
        b_exp = QPushButton("CSV'ye aktar")
        b_exp.clicked.connect(self._on_export)
        b_imp = QPushButton("CSV aç")
        b_imp.setToolTip("Önceki bir kaydı içe aktarır; sinyaller listede 'İçe aktarılan kayıtlar' altında görünür.")
        b_imp.clicked.connect(self._on_import)
        for b in (b_clear, b_exp, b_imp):
            row2.addWidget(b)
        row2.addStretch()

        # ---------------- sinyal tarayıcı
        self.search = QLineEdit()
        self.search.setPlaceholderText("İsme göre ara...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemDoubleClicked.connect(self._on_dbl)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_tree_menu)
        self.browser_hint = QLabel("")
        self.browser_hint.setVisible(False)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 4, 0)
        title = QLabel("Sinyaller")
        title.setObjectName("cardTitle")
        ll.addWidget(title)
        ll.addWidget(self.search)
        ll.addWidget(self.tree, 1)
        ll.addWidget(self.browser_hint)

        _apply_mdi_palette()
        self.mdi = QMdiArea()
        self.mdi.setViewMode(QMdiArea.SubWindowView)
        self.mdi.setBackground(QColor("#08121f"))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.mdi)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        split.setSizes([270, 1000])
        split.setChildrenCollapsible(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        lay.setSpacing(6)
        lay.addLayout(row1)
        lay.addLayout(row2)
        lay.addWidget(split, 1)
        self.setMinimumHeight(560)

        self._refresh_layout_combo()
        self._rebuild_browser()
        self._update_state_label()

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.autosave = QTimer(self)
        self.autosave.setInterval(5000)
        self.autosave.timeout.connect(self._autosave)
        self.autosave.start()

        last = self.store.last() if self.store else None
        if last:
            self.apply_state(last)
        else:
            self.add_panel("plot")

    # ====================================================================
    # Dışarıdan besleme (MainWindow çağırır)
    # ====================================================================
    def push(self, sid: str, value):
        self.hub.push(sid, value)

    def set_a2l_measurements(self, measurements):
        self._a2l_names = [m.name for m in measurements]
        self._rebuild_browser()

    def set_dbc(self, dbc):
        self._dbc = dbc
        self._on_changed()
        self._rebuild_browser()

    def set_input_values(self, values: dict):
        self._input_values.update({k: float(v) for k, v in values.items() if v is not None})

    def on_can_frame(self, arb_id: int, data: bytes):
        entry = self._dbc_map.get(arb_id)
        if entry is None:
            return
        msg, sigs = entry
        try:
            decoded = msg.decode(bytes(data), decode_choices=False)
        except Exception:
            return
        name = msg.name
        for s in sigs:
            if s in decoded:
                self.hub.push(f"dbc:{name}.{s}", decoded[s])

    def shutdown(self):
        self._autosave(force=True)

    # ====================================================================
    # Zamanlayıcı
    # ====================================================================
    def _span(self):
        return SPANS[self.span_combo.currentIndex()][1]

    def _tick(self):
        self._tick_n += 1
        for sid in self.hub.active():
            if kind_of(sid) == "input":
                v = self._input_values.get(sid.split(":", 1)[1])
                if v is not None:
                    self.hub.push(sid, v)
        if self._tick_n % 2 == 0:
            names = sorted(s.split(":", 1)[1] for s in self.hub.sources_needed() if kind_of(s) == "a2l")
            if names:
                self.read_requested.emit(names)
        if self.isVisible():
            span = self._span()
            for p in self._panels:
                p.refresh(span, self.frozen)

    # ====================================================================
    # Paneller
    # ====================================================================
    def add_panel(self, kind: str, state: dict | None = None, geometry=None, title: str | None = None):
        cls = PANEL_TYPES[kind]
        if kind == "control":
            panel = cls(self.hub, self._input_defs, self.send_input.emit, lambda: dict(self._input_values))
        else:
            panel = cls(self.hub)
        self._counter[kind] += 1
        title = title or f"{cls.title} {self._counter[kind]}"
        sub = _Sub()
        sub.setWidget(panel)
        sub.setWindowTitle(title)
        sub.setAttribute(Qt.WA_DeleteOnClose, True)
        self.mdi.addSubWindow(sub)
        w, h = DEFAULT_SIZES[kind]
        n = len(self._panels)
        if geometry:
            sub.setGeometry(QRect(*[int(x) for x in geometry]))
        else:
            sub.setGeometry(QRect(20 + 28 * (n % 8), 20 + 28 * (n % 8), w, h))
        sub.show()
        self._panels.append(panel)
        self._subs[panel] = sub
        panel.changed.connect(lambda p=panel: self._on_panel_changed(p))
        sub.closed.connect(lambda s, p=panel: self._on_closed(p))
        if state:
            panel.from_state(state)
        if self.frozen:
            panel.set_frozen(True)
        panel.refresh(self._span(), False)
        self.mdi.setActiveSubWindow(sub)
        self._on_changed()
        return panel

    def _on_closed(self, panel):
        if panel in self._panels:
            self._panels.remove(panel)
        self._subs.pop(panel, None)
        self._on_changed()

    def clear_panels(self):
        for sub in list(self._subs.values()):
            sub.closed.disconnect()
            sub.close()
        self._panels.clear()
        self._subs.clear()
        self._counter = {k: 0 for k in PANEL_TYPES}

    def active_panel(self):
        sub = self.mdi.activeSubWindow()
        w = sub.widget() if sub is not None else None
        return w if w in self._panels else None

    def _target_panel(self):
        p = self.active_panel()
        if p is not None and p.kind != "control":
            return p
        for q in reversed(self._panels):
            if q.kind == "plot":
                return q
        return self.add_panel("plot")

    def _on_panel_changed(self, panel):
        # Donmuşken yeni eklenen sinyalin değeri gösterge/tabloda hemen görünsün
        # (yalnızca değişen panel yenilenir; diğerleri dondurulmuş kalır).
        if self.frozen and panel.kind in ("gauge", "table"):
            panel.refresh(self._span(), False)
        self._on_changed()

    def _on_changed(self):
        ids = []
        for p in self._panels:
            ids.extend(p.signals_ids)
        self.hub.set_active(ids)
        self._rebuild_dbc_map()
        self._mark_dirty()

    def _rebuild_dbc_map(self):
        m: dict = {}
        if self._dbc is not None and self._dbc.is_loaded:
            for sid in self.hub.active():
                if kind_of(sid) != "dbc":
                    continue
                msg_name, _, sig = sid.split(":", 1)[1].partition(".")
                msg = self._dbc.get_message(msg_name)
                if msg is None:
                    continue
                m.setdefault(msg.frame_id, (msg, set()))[1].add(sig)
        self._dbc_map = m

    # ====================================================================
    # Dondur
    # ====================================================================
    def _on_freeze(self, on: bool):
        self.frozen = bool(on)
        self.freeze_btn.setText("▶  Devam" if on else "⏸  Dondur")
        for p in self._panels:
            p.set_frozen(self.frozen)
        self._update_state_label()

    def _update_state_label(self):
        if self.frozen:
            self.state_label.setText("● DONDURULDU")
            self.state_label.setStyleSheet("color:#f0b04a; font-weight:700;")
        else:
            self.state_label.setText("● CANLI")
            self.state_label.setStyleSheet("color:#4ade80; font-weight:700;")

    # ====================================================================
    # Sinyal tarayıcı
    # ====================================================================
    def all_signal_ids(self) -> list:
        ids = [f"a2l:{n}" for n in self._a2l_names]
        if self._dbc is not None and self._dbc.is_loaded:
            for mn in self._dbc.message_names():
                ids += [f"dbc:{mn}.{s.name}" for s in self._dbc.signals_of(mn)]
        from app.dashboard_config import GAUGE_KEYS
        ids += [f"gauge:{k}" for k in GAUGE_KEYS]
        ids += [f"input:{d.key}" for d in self._input_defs if d.enabled]
        ids += list(self.hub.derived)
        ids += sorted(self.hub.static)
        return ids

    def _leaf(self, parent, text, sid):
        it = QTreeWidgetItem([text])
        it.setData(0, ROLE_ID, sid)
        it.setToolTip(0, sid)
        parent.addChild(it)
        return it

    def _rebuild_browser(self):
        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        roots = {}
        for kind, text in GROUPS:
            r = QTreeWidgetItem([text])
            self.tree.addTopLevelItem(r)
            roots[kind] = r
        for n in self._a2l_names:
            self._leaf(roots["a2l"], n, f"a2l:{n}")
        if self._dbc is not None and self._dbc.is_loaded:
            for mn in self._dbc.message_names():
                node = QTreeWidgetItem([mn])
                roots["dbc"].addChild(node)
                for s in self._dbc.signals_of(mn):
                    self._leaf(node, s.name, f"dbc:{mn}.{s.name}")
        from app.dashboard_config import GAUGE_KEYS
        for k in GAUGE_KEYS:
            self._leaf(roots["gauge"], k, f"gauge:{k}")
        for d in self._input_defs:
            if d.enabled:
                self._leaf(roots["input"], d.label + (f" [{d.unit}]" if d.unit else ""), f"input:{d.key}")
        for sid in self.hub.derived:
            self._leaf(roots["math"], label_of(sid), sid)
        for sid in sorted(self.hub.static):
            self._leaf(roots["csv"], label_of(sid), sid)
        for kind, r in roots.items():
            r.setText(0, f"{dict(GROUPS)[kind]} ({self._count_leaves(r)})")
        self.tree.setUpdatesEnabled(True)
        self._collapse_default()
        self._apply_filter(self.search.text())

    @staticmethod
    def _count_leaves(item) -> int:
        n = 0
        for i in range(item.childCount()):
            c = item.child(i)
            n += 1 if c.data(0, ROLE_ID) else WorkspaceTab._count_leaves(c)
        return n

    def _collapse_default(self):
        self.tree.collapseAll()
        for i in range(self.tree.topLevelItemCount()):
            r = self.tree.topLevelItem(i)
            if i >= 2:                        # gösterge, giriş, matematik, csv açık
                r.setExpanded(True)

    def _apply_filter(self, text: str):
        text = text.strip().lower()

        def visit(item) -> bool:
            sid = item.data(0, ROLE_ID)
            if sid:
                show = (not text) or text in sid.lower() or text in item.text(0).lower()
                item.setHidden(not show)
                return show
            any_ = False
            for i in range(item.childCount()):
                any_ = visit(item.child(i)) or any_
            item.setHidden(bool(text) and not any_)
            if text and any_:
                item.setExpanded(True)
            return any_

        for i in range(self.tree.topLevelItemCount()):
            visit(self.tree.topLevelItem(i))
        if not text:
            self._collapse_default()

    def _on_dbl(self, item, _col=0):
        sid = item.data(0, ROLE_ID)
        if not sid:
            return
        self._target_panel().add_signal(sid)

    def _on_tree_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None or not item.data(0, ROLE_ID):
            return
        sid = item.data(0, ROLE_ID)
        m = QMenu(self)
        a_add = m.addAction("Etkin panele ekle")
        a_new = m.addAction("Yeni grafik panelinde çiz")
        a_edit = a_del = a_rm = None
        if kind_of(sid) == "math":
            m.addSeparator()
            a_edit = m.addAction("Matematik tanımını düzenle…")
            a_del = m.addAction("Matematik sinyalini sil")
        elif kind_of(sid) == "csv":
            m.addSeparator()
            a_rm = m.addAction("Kayıttan kaldır")
        act = m.exec(self.tree.viewport().mapToGlobal(pos))
        if act is None:
            return
        if act is a_add:
            self._target_panel().add_signal(sid)
        elif act is a_new:
            self.add_panel("plot").add_signal(sid)
        elif act is a_edit:
            self._on_new_math(existing=sid)
        elif act is a_del:
            self._delete_math(sid)
        elif act is a_rm:
            for p in self._panels:
                p.remove_signal(sid)
            self.hub.remove_static(sid)
            self._rebuild_browser()

    # ====================================================================
    # Matematik sinyalleri
    # ====================================================================
    def _on_new_math(self, _checked=False, existing: str | None = None):
        ids = [s for s in self.all_signal_ids() if s != existing]
        ex = (existing, self.hub.derived[existing]) if existing else None
        if ex is None:
            # etkin panelde bir sinyal seçiliyse A olarak öner
            p = self.active_panel()
            ids = (p.signals_ids if p else []) + [s for s in ids if not p or s not in p.signals_ids]
        dlg = MathDialog(ids, ex, self)
        if dlg.exec() != QDialog.Accepted:
            return
        name, spec = dlg.result_spec()
        sid = f"math:{name}"
        if sid != existing and sid in self.hub.derived:
            QMessageBox.warning(self, "Matematik sinyali", f"'{name}' zaten var.")
            return
        if existing and sid != existing:            # yeniden adlandırma
            for p in self._panels:
                if existing in p.signals_ids:
                    p.signals_ids[p.signals_ids.index(existing)] = sid
                    if hasattr(p, "styles") and existing in p.styles:
                        p.styles[sid] = p.styles.pop(existing)
            self.hub.remove_derived(existing)
        self.hub.define_derived(name, spec)
        self._rebuild_browser()
        if existing is None:
            self._target_panel().add_signal(sid)
        for p in self._panels:
            p._signals_changed()
        self._on_changed()

    def _delete_math(self, sid):
        for p in self._panels:
            p.remove_signal(sid)
        self.hub.remove_derived(sid)
        self._rebuild_browser()
        self._on_changed()

    # ====================================================================
    # Yerleşim kaydet / yükle
    # ====================================================================
    def to_state(self) -> dict:
        panels = []
        for p in self._panels:
            sub = self._subs.get(p)
            if sub is None:
                continue
            g = sub.geometry()
            panels.append({"kind": p.kind, "title": sub.windowTitle(),
                           "geometry": [g.x(), g.y(), g.width(), g.height()],
                           "state": p.to_state()})
        return {"version": 1, "span": self.span_combo.currentIndex(),
                "derived": self.hub.derived, "panels": panels}

    def apply_state(self, state: dict):
        self._loading = True
        try:
            self.clear_panels()
            for sid in list(self.hub.derived):
                self.hub.remove_derived(sid)
            self.hub.set_active([])
            for sid, spec in (state.get("derived") or {}).items():
                self.hub.derived[sid] = dict(spec)
            self.span_combo.setCurrentIndex(int(state.get("span", 1)))
            for pd in state.get("panels", []):
                if pd.get("kind") in PANEL_TYPES:
                    self.add_panel(pd["kind"], pd.get("state"), pd.get("geometry"), pd.get("title"))
            if not state.get("panels"):
                self.add_panel("plot")
        finally:
            self._loading = False
        for sid in list(self.hub.derived):
            self.hub.recompute(sid)
        self._rebuild_browser()
        self._on_changed()

    def _refresh_layout_combo(self, select: str | None = None):
        self.layout_combo.blockSignals(True)
        self.layout_combo.clear()
        names = self.store.names() if self.store else []
        self.layout_combo.addItem("— kayıtlı yerleşim seç —")
        self.layout_combo.addItems([n for n in names if n != LAST])
        if select:
            i = self.layout_combo.findText(select)
            self.layout_combo.setCurrentIndex(max(i, 0))
        self.layout_combo.blockSignals(False)

    def _on_save_layout(self):
        if self.store is None:
            return
        cur = self.layout_combo.currentText()
        default = "" if cur.startswith("—") else cur
        name, ok = QInputDialog.getText(self, "Yerleşimi kaydet", "Yerleşim ismi:", text=default)
        name = name.strip()
        if not ok or not name or name == LAST:
            return
        self.store.save(name, self.to_state())
        self._refresh_layout_combo(select=name)

    def _on_layout_chosen(self, index: int):
        if self.store is None or index <= 0:
            return
        state = self.store.get(self.layout_combo.currentText())
        if state:
            self.apply_state(state)

    def _on_delete_layout(self):
        if self.store is None or self.layout_combo.currentIndex() <= 0:
            return
        name = self.layout_combo.currentText()
        if QMessageBox.question(self, "Yerleşimi sil", f"'{name}' silinsin mi?") == QMessageBox.Yes:
            self.store.delete(name)
            self._refresh_layout_combo()

    def _mark_dirty(self):
        pass        # otomatik kayıt zamanlayıcıyla; durum karşılaştırılarak yazılır

    def _autosave(self, force: bool = False):
        if self.store is None or self._loading:
            return
        try:
            blob = json.dumps(self.to_state(), sort_keys=True, ensure_ascii=False)
        except (TypeError, ValueError):
            return
        if force or blob != self._last_saved:
            self.store.save_last(json.loads(blob))
            self._last_saved = blob

    # ====================================================================
    # Kayıt: temizle / CSV
    # ====================================================================
    def _on_clear(self):
        self.hub.clear_live()
        for p in self._panels:
            p.refresh(self._span(), False)

    def _on_export(self):
        ids = [s for s in self.hub.all_ids_with_data() if s not in self.hub.static]
        if not ids:
            QMessageBox.information(self, "CSV'ye aktar", "Henüz kaydedilmiş veri yok.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Kaydı CSV'ye aktar", "kayit.csv", "CSV (*.csv)")
        if not path:
            return
        try:
            n = self.hub.export_csv(path, ids)
        except OSError as exc:
            QMessageBox.critical(self, "CSV'ye aktar", str(exc))
            return
        QMessageBox.information(self, "CSV'ye aktar", f"{n} sinyal yazıldı:\n{path}")

    def _on_import(self):
        path, _ = QFileDialog.getOpenFileName(self, "CSV kaydı aç", "", "CSV (*.csv *.txt)")
        if not path:
            return
        tag = os.path.splitext(os.path.basename(path))[0]
        try:
            added = self.hub.import_csv(path, tag)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(self, "CSV aç", str(exc))
            return
        self._rebuild_browser()
        panel = self._target_panel()
        for sid in added[:12]:
            panel.add_signal(sid)
