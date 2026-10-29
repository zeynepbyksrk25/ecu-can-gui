"""Performans sayfası: motor modelinin (ECU'ya gömülü algoritma) çıkışlarını
A–E renkli kartlarda gösterir. Salt okunur. Değerler DBC (CAN) ya da A2L
(CCP) kaynağından gelir; eşleme isimle otomatik denenir, olmayanlar elle
bağlanır (kutuya sağ tık)."""
import time
from collections import deque

import pyqtgraph as pg
from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QHBoxLayout, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QMenu, QPushButton, QVBoxLayout, QWidget,
)

from app.sim_interface import (
    INPUT_BY_KEY, PERF_BY_KEY, PERF_DEFS, SimConfig, auto_match, list_sources, threshold_level,
)
from app.ui.dashboard_tab import GaugeWidget
from app.ui.sim_widgets import ColorCard, DigitalBox, SignalPickerDialog, ThresholdDialog

POLL_MS = 300
UI_MS = 500
STALE_S = 3.0
HIST_MAX_S = 600

GRAPH_COLORS = ["#1B6FB5", "#C2410C", "#15803D", "#7C3AED", "#B45309", "#0E7490",
                "#BE185D", "#4D7C0F", "#475569"]


class PerfGauge(GaugeWidget):
    ZONES = [(0.0, 1.0, "#2F7FB8")]
    bind_requested = Signal(str)
    unbind_requested = Signal(str)
    range_requested = Signal(str)

    def __init__(self, key, label, unit, parent=None):
        super().__init__(label, 0.0, 100.0, unit, parent)
        self.key = key
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        m = QMenu(self)
        a1 = m.addAction("Sinyal bağla…")
        a2 = m.addAction("Aralığı ayarla…")
        a3 = m.addAction("Bağlantıyı kaldır")
        act = m.exec(self.mapToGlobal(pos))
        if act is a1:
            self.bind_requested.emit(self.key)
        elif act is a2:
            self.range_requested.emit(self.key)
        elif act is a3:
            self.unbind_requested.emit(self.key)


class _GraphBox(QFrame):
    def __init__(self, index: int, spec: dict, on_edit, on_norm, parent=None):
        super().__init__(parent)
        self.index = index
        self.spec = spec
        self.setObjectName("graphBox")
        self.setStyleSheet("QFrame#graphBox { background:#FFFFFF; border:1px solid #DDE5EC; border-radius:10px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 8)
        head = QHBoxLayout()
        self.title = QLabel(spec["title"])
        self.title.setStyleSheet("font-weight:700; color:#14202C;")
        self.norm = QCheckBox("Normalize")
        self.norm.setChecked(bool(spec.get("normalize")))
        self.norm.setToolTip("Her seri kendi min–max aralığına göre 0–1'e ölçeklenir "
                             "(farklı birimleri tek eksende karşılaştırmak için).")
        self.norm.toggled.connect(lambda v: on_norm(index, v))
        btn = QPushButton("Seç…")
        btn.setFixedHeight(24)
        btn.clicked.connect(lambda: on_edit(index))
        head.addWidget(self.title, 1)
        head.addWidget(self.norm)
        head.addWidget(btn)
        lay.addLayout(head)
        self.plot = pg.PlotWidget(background="#FFFFFF")
        self.plot.setMinimumHeight(190)
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.plot.addLegend(offset=(6, 6))
        self.plot.getAxis("bottom").setLabel("sn (şimdiye göre)")
        lay.addWidget(self.plot, 1)
        self.curves: dict[str, pg.PlotDataItem] = {}


class PerformanceTab(QWidget):
    poll_requested = Signal()

    def __init__(self, config: SimConfig | None = None):
        super().__init__()
        self.config = config or SimConfig()
        self._dbc = None
        self._a2l_db = None
        self._sources = []
        self._src = {}
        self._frames: dict[int, list] = {}
        self._state = {k: {"v": None, "t": 0.0, "hist": deque()} for k in PERF_BY_KEY}
        self._flight = {}
        self._can_ok = False
        self._ccp_ok = False
        self._lost = False
        self._paused = False
        self._boxes: dict[str, DigitalBox] = {}
        self._gauges: dict[str, PerfGauge] = {}
        self._flight_boxes: dict[str, DigitalBox] = {}
        self._graph_boxes: list[_GraphBox] = []
        self._build()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_MS)
        self._poll_timer.timeout.connect(self._on_poll)
        self._poll_timer.start()
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(UI_MS)
        self._ui_timer.timeout.connect(self._on_ui)
        self._ui_timer.start()

    # ------------------------------------------------------------ yapı
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel("Motor Performansı")
        title.setStyleSheet("font-size:18px; font-weight:800; color:#14202C;")
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#5B6B79;")
        self.pause_button = QPushButton("⏸  Grafikleri durdur")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._on_pause)
        from PySide6.QtWidgets import QButtonGroup
        self._win_group = QButtonGroup(self)
        self._win_group.setExclusive(True)
        self.window_box = QWidget()
        wl = QHBoxLayout(self.window_box)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        self._win_buttons = {}
        for label, sec in (("30 sn", 30), ("60 sn", 60), ("5 dk", 300)):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setFixedHeight(28)
            b.setStyleSheet("QPushButton { border:1px solid #C5D0DA; background:#FFFFFF; padding:0 14px; font-weight:600; }"
                            "QPushButton:checked { background:#0E6E8C; color:#FFFFFF; border-color:#0E6E8C; }")
            self._win_group.addButton(b)
            self._win_buttons[sec] = b
            wl.addWidget(b)
            b.clicked.connect(lambda _c, s=sec: self._on_window(s))
        self._win_buttons.get(self.config.window_s, self._win_buttons[60]).setChecked(True)
        top.addWidget(title)
        top.addSpacing(16)
        top.addWidget(self.status_label, 1)
        top.addWidget(QLabel("Pencere:"))
        top.addWidget(self.window_box)
        top.addWidget(self.pause_button)
        root.addLayout(top)

        self.banner = QLabel("")
        self.banner.setStyleSheet("background:#FDF1EF; color:#A8231A; font-weight:700; padding:6px 10px; border-radius:6px;")
        self.banner.setVisible(False)
        root.addWidget(self.banner)

        # A: uçuş koşulları (girişlerin geri okunuşu)
        card_a = ColorCard("A")
        sub = QLabel("Ana Sayfa'dan gönderilen değerin geri okunuşu")
        sub.setStyleSheet("color:#4A6A8A; font-size:12px; background:transparent;")
        card_a.outer.insertWidget(1, sub)
        for i, key in enumerate(("altitude", "ma", "p_total", "p_amb", "t_amb", "alfa", "beta")):
            d = INPUT_BY_KEY[key]
            b = DigitalBox("flight:" + key, d.label, d.unit)
            b.setContextMenuPolicy(Qt.NoContextMenu)
            b.bound_label.setText("")
            b.setToolTip("Ana Sayfa'dan gönderilen değerin geri okunuşu")
            self._flight_boxes[key] = b
            card_a.body.addWidget(b, 0, i)
        root.addWidget(card_a)

        cards = {c: ColorCard(c) for c in "BCDE"}
        for cid, card in cards.items():
            defs = [d for d in PERF_DEFS if d.card == cid]
            gdef = next((d for d in defs if d.kind == "gauge"), None)
            right = QVBoxLayout()
            right.setSpacing(6)
            for d in defs:
                if d.kind == "gauge":
                    continue
                b = DigitalBox(d.key, d.label, d.unit, d.hint)
                b.bind_requested.connect(self._bind)
                b.unbind_requested.connect(self._unbind)
                b.threshold_requested.connect(self._threshold)
                self._boxes[d.key] = b
                right.addWidget(b)
            if gdef is not None:
                g = PerfGauge(gdef.key, gdef.label, gdef.unit)
                g.bind_requested.connect(self._bind)
                g.unbind_requested.connect(self._unbind)
                g.range_requested.connect(self._set_range)
                self._gauges[gdef.key] = g
                card.body.addWidget(g, 0, 0)
            right.addStretch(1)
            card.body.addLayout(right, 0, 1)
            card.body.setColumnStretch(0, 1)
            card.body.setColumnStretch(1, 1)
        row1 = QHBoxLayout()
        row1.addWidget(cards["B"], 1)
        row1.addWidget(cards["C"], 1)
        row2 = QHBoxLayout()
        row2.addWidget(cards["D"], 1)
        row2.addWidget(cards["E"], 1)
        root.addLayout(row1)
        root.addLayout(row2)

        graphs = QHBoxLayout()
        for i, spec in enumerate(self.config.graphs[:3]):
            gb = _GraphBox(i, spec, self._edit_graph, self._set_norm)
            self._graph_boxes.append(gb)
            graphs.addWidget(gb, 1)
        root.addLayout(graphs)
        root.addStretch(1)
        self._update_bound_labels()

    # ------------------------------------------------------------ kaynaklar
    def refresh_sources(self, dbc=None, a2l_db=None):
        if dbc is not None:
            self._dbc = dbc
        if a2l_db is not None:
            self._a2l_db = a2l_db
        dbc_ok = self._dbc if (self._dbc is not None and getattr(self._dbc, "is_loaded", False)) else None
        summary = getattr(self._a2l_db, "summary", None) if self._a2l_db is not None else None
        self._sources = list_sources(dbc_ok, summary)
        self._src = {s.key: s for s in self._sources}
        changed = False
        for d in PERF_DEFS:
            cur = self.config.perf_map.get(d.key)
            if cur and cur in self._src:
                continue
            if cur and cur not in self._src:
                continue          # elle seçilmiş ama dosyada yok: kullanıcı karar versin
            hit = auto_match(d.aliases, d.label, self._sources)
            if hit is not None:
                self.config.perf_map[d.key] = hit.key
                changed = True
        if changed:
            self.config.save()
        self._rebuild_index()
        self._update_bound_labels()

    def _rebuild_index(self):
        self._frames = {}
        for key, skey in self.config.perf_map.items():
            s = self._src.get(skey)
            if s is not None and skey.startswith("dbc:") and s.frame_id is not None:
                self._frames.setdefault(s.frame_id, []).append((key, s.name))

    def _update_bound_labels(self):
        n = 0
        for key, b in list(self._boxes.items()) + list(self._gauges.items()):
            skey = self.config.perf_map.get(key)
            s = self._src.get(skey) if skey else None
            if key in self._boxes:
                b.set_bound(bool(s), s.name if s else "")
            if s:
                n += 1
            elif skey:
                self._boxes.get(key) and self._boxes[key].bound_label.setText("yok!")
        self.status_label.setText(f"{n}/{len(PERF_DEFS)} sinyal bağlı  ·  kutuya sağ tık: Sinyal bağla / Eşik")

    def _pick(self, key: str):
        d = PERF_BY_KEY[key]
        dlg = SignalPickerDialog(f"{d.label} için sinyal seç", self._sources,
                                 self.config.perf_map.get(key, ""), self)
        if dlg.exec() == QDialog.Accepted and dlg.selected_key():
            self.config.perf_map[key] = dlg.selected_key()
            self.config.save()
            self._rebuild_index()
            self._update_bound_labels()

    def _bind(self, key):
        self._pick(key)

    def _unbind(self, key):
        self.config.perf_map.pop(key, None)
        self._state[key]["v"] = None
        self.config.save()
        self._rebuild_index()
        self._update_bound_labels()

    def _threshold(self, key):
        d = PERF_BY_KEY[key]
        dlg = ThresholdDialog(f"{d.label} eşikleri", self.config.thresholds.get(key), self)
        if dlg.exec() == QDialog.Accepted:
            cfg = dlg.result_cfg()
            if cfg is None:
                self.config.thresholds.pop(key, None)
            else:
                self.config.thresholds[key] = cfg
            self.config.save()

    def _set_range(self, key):
        cur = self.config.ranges.get(key)
        txt, ok = QInputDialog.getText(self, "Gösterge aralığı", "min, max (boş = otomatik):",
                                       text=f"{cur[0]}, {cur[1]}" if cur else "")
        if not ok:
            return
        txt = txt.strip()
        if not txt:
            self.config.ranges.pop(key, None)
        else:
            try:
                a, b = [float(x.replace(",", ".")) for x in txt.replace(";", ",").split(",")[:2]]
                if b > a:
                    self.config.ranges[key] = [a, b]
            except ValueError:
                return
        self.config.save()

    # ------------------------------------------------------------ canlı veri
    def on_can_frame(self, frame_id: int, data: bytes):
        keys = self._frames.get(frame_id)
        if not keys or self._dbc is None:
            return
        msg = self._dbc.get_message_by_frame_id(frame_id)
        if msg is None:
            return
        try:
            values = msg.decode(bytes(data), decode_choices=False)
        except Exception:
            return
        for key, sig in keys:
            if sig in values:
                try:
                    self._set(key, float(values[sig]))
                except (TypeError, ValueError):
                    pass

    def _set(self, key: str, v: float):
        st = self._state[key]
        st["v"] = v
        st["t"] = time.monotonic()

    def ccp_poll_targets(self) -> list:
        out = []
        for key, skey in self.config.perf_map.items():
            s = self._src.get(skey)
            if key in self._state and s is not None and skey.startswith("a2l:") \
                    and s.info is not None and getattr(s.info, "address", None) is not None:
                out.append((key, s.info))
        return out

    def set_ccp_value(self, key: str, value: float):
        if key in self._state:
            self._set(key, value)

    def set_ccp_error(self, key: str, message: str):
        pass

    def set_connection_state(self, can: bool, ccp: bool, lost: bool = False):
        self._can_ok, self._ccp_ok, self._lost = can, ccp, lost
        if lost:
            self.banner.setText("Bağlantı koptu — değerler güncellenmiyor.")
        elif not can:
            self.banner.setText("CAN bağlı değil — değerler güncellenmiyor.")
        else:
            self.banner.setText("")
        self.banner.setVisible(bool(self.banner.text()))

    def set_flight(self, values: dict):
        self._flight = dict(values)
        for key, b in self._flight_boxes.items():
            b.set_value(values.get(key))

    # ------------------------------------------------------------ zamanlayıcılar
    def _on_poll(self):
        if self._ccp_ok and not self._lost and self.isVisible() and self.ccp_poll_targets():
            self.poll_requested.emit()

    def _range_for(self, key: str):
        if key in self.config.ranges:
            a, b = self.config.ranges[key]
            return a, b
        s = self._src.get(self.config.perf_map.get(key, ""))
        if s is not None and s.minimum is not None and s.maximum is not None and s.maximum > s.minimum:
            return float(s.minimum), float(s.maximum)
        hist = [v for _t, v in self._state[key]["hist"]]
        if not hist and self._state[key]["v"] is None:
            return 0.0, 100.0
        top = max([abs(x) for x in hist] + [abs(self._state[key]["v"] or 0.0), 1e-9])
        import math
        mag = 10 ** math.floor(math.log10(top * 1.25))
        hi = math.ceil(top * 1.25 / mag) * mag
        lo = min(0.0, min(hist)) if hist else 0.0
        return lo, hi

    def _on_ui(self):
        now = time.monotonic()
        live = self._can_ok and not self._lost
        for key, st in self._state.items():
            v = st["v"]
            stale = (not live) or v is None or (now - st["t"] > STALE_S)
            if v is not None and not self._paused:
                st["hist"].append((now, v))
            while st["hist"] and now - st["hist"][0][0] > HIST_MAX_S:
                st["hist"].popleft()
            trend = 0
            if v is not None and len(st["hist"]) > 3:
                ref = next((val for t, val in st["hist"] if now - t <= 2.0), st["hist"][0][1])
                if abs(v - ref) > 0.005 * (abs(ref) + 1e-9):
                    trend = 1 if v > ref else -1
            if key in self._boxes:
                lvl = threshold_level(self.config.thresholds.get(key), v)
                self._boxes[key].set_value(v, lvl, trend, stale)
                self._boxes[key].set_history([val for t, val in st["hist"] if now - t <= 30][-60:])
            elif key in self._gauges:
                g = self._gauges[key]
                lo, hi = self._range_for(key)
                g.set_range(lo, hi)
                g.set_value(v if not stale else None)
        if not self._paused:
            self._update_graphs(now)

    def _update_graphs(self, now: float):
        win = self.config.window_s
        for gi, gb in enumerate(self._graph_boxes):
            spec = self.config.graphs[gi]
            keys = [k for k in spec["keys"] if k in self._state]
            for k in list(gb.curves):
                if k not in keys:
                    gb.plot.removeItem(gb.curves.pop(k))
            for ci, k in enumerate(keys):
                pts = [(t - now, v) for t, v in self._state[k]["hist"] if now - t <= win]
                if k not in gb.curves:
                    color = GRAPH_COLORS[ci % len(GRAPH_COLORS)]
                    gb.curves[k] = gb.plot.plot([], [], pen=pg.mkPen(color, width=2), name=PERF_BY_KEY[k].label)
                if not pts:
                    gb.curves[k].setData([], [])
                    continue
                xs = [p[0] for p in pts]
                ys = [p[1] for p in pts]
                if spec.get("normalize"):
                    lo, hi = min(ys), max(ys)
                    span = (hi - lo) or 1.0
                    ys = [(y - lo) / span for y in ys]
                gb.curves[k].setData(xs, ys)
            gb.plot.setXRange(-win, 0, padding=0)
            gb.plot.getAxis("left").setLabel("normalize (0–1)" if spec.get("normalize") else "")

    def _on_pause(self, on: bool):
        self._paused = on
        self.pause_button.setText("▶  Grafikleri sürdür" if on else "⏸  Grafikleri durdur")

    def _on_window(self, sec: int):
        self.config.window_s = int(sec)
        self.config.save()

    def _set_norm(self, index: int, on: bool):
        self.config.graphs[index]["normalize"] = bool(on)
        self.config.save()

    def _edit_graph(self, index: int):
        spec = self.config.graphs[index]
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{spec['title']} — çizilecek sinyaller")
        dlg.resize(420, 520)
        lay = QVBoxLayout(dlg)
        from PySide6.QtWidgets import QLineEdit
        search = QLineEdit()
        search.setPlaceholderText("İsme göre ara...")
        lay.addWidget(search)
        allbox = QCheckBox("Tümünü seç / kaldır")
        lay.addWidget(allbox)
        lst = QListWidget()
        for d in PERF_DEFS:
            it = QListWidgetItem(f"{d.label}  [{d.unit}]" if d.unit else d.label)
            it.setData(Qt.UserRole, d.key)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if d.key in spec["keys"] else Qt.Unchecked)
            lst.addItem(it)
        lay.addWidget(lst, 1)
        count = QLabel("")
        lay.addWidget(count)

        def refresh_count(*_a):
            n = sum(1 for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked)
            count.setText(f"Seçili: {n} / {lst.count()}")

        def on_search(text):
            t = text.strip().lower()
            for i in range(lst.count()):
                lst.item(i).setHidden(bool(t) and t not in lst.item(i).text().lower())

        def on_all(on):
            for i in range(lst.count()):
                if not lst.item(i).isHidden():
                    lst.item(i).setCheckState(Qt.Checked if on else Qt.Unchecked)

        search.textChanged.connect(on_search)
        allbox.toggled.connect(on_all)
        lst.itemChanged.connect(refresh_count)
        refresh_count()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Tamam")
        bb.button(QDialogButtonBox.Cancel).setText("İptal")
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() == QDialog.Accepted:
            spec["keys"] = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                            if lst.item(i).checkState() == Qt.Checked]
            self.config.save()
