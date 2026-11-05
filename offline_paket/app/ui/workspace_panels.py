"""Çalışma Alanı bileşenleri (her biri serbestçe taşınan/boyutlandırılan bir pencere):

  PlotPanel   — "Data Inspector" tarzı grafik: üst üste / ayrı ayrı çizim, sinyal
                başına renk-kalınlık, fare ile anlık değerler, A/B imleçleri
                (Δ, ortalama, min, maks), dondurunca yakınlaştırma.
  GaugePanel  — tek sinyallik ibreli gösterge.
  TablePanel  — sinyallerin anlık değer / ortalama / min / maks tablosu.
  ControlPanel— Simülasyon Girişleri'ni (Throttle vb.) buradan göndermek için.

Hepsi ortak SignalHub'tan okur; kendi başına veri toplamaz.
"""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QDoubleSpinBox, QGridLayout, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMenu, QPushButton, QSizePolicy, QSplitter,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.signal_hub import label_of

PALETTE = ["#0E6E8C", "#ff6b6b", "#4ade80", "#b48cff", "#f0b04a",
           "#2dd4bf", "#ff6b9d", "#a3e635", "#5aa9ff", "#ff9a52",
           "#cfd8e3", "#e879f9"]


def fmt(v) -> str:
    if v is None:
        return "—"
    return f"{v:.5g}"


def value_at(t: np.ndarray, v: np.ndarray, x: float):
    """x anındaki değer (sample & hold); veri aralığı dışındaysa None."""
    if t.size == 0 or x < t[0] or x > t[-1] + 1e-9:
        return None
    i = int(np.searchsorted(t, x, side="right")) - 1
    return float(v[max(i, 0)])


class PanelBase(QWidget):
    changed = Signal()          # sinyal listesi / ayar değişti (yerleşim kirlendi)
    kind = ""
    title = ""

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.signals_ids: list[str] = []

    def add_signal(self, sid: str) -> bool:
        if sid in self.signals_ids:
            return False
        self.signals_ids.append(sid)
        self._signals_changed()
        return True

    def remove_signal(self, sid: str):
        if sid in self.signals_ids:
            self.signals_ids.remove(sid)
            self._signals_changed()

    def _signals_changed(self):
        self.changed.emit()

    def refresh(self, span: float | None, frozen: bool):  # noqa: ARG002
        pass

    def set_frozen(self, frozen: bool):  # noqa: ARG002
        pass

    def to_state(self) -> dict:
        return {"signals": list(self.signals_ids)}

    def from_state(self, state: dict):
        self.signals_ids = list(state.get("signals", []))
        self._signals_changed()


# ============================================================ Grafik
class _Glw(pg.GraphicsLayoutWidget):
    def __init__(self, on_leave):
        super().__init__()
        self._on_leave = on_leave

    def leaveEvent(self, ev):  # noqa: N802
        self._on_leave()
        super().leaveEvent(ev)


COL_VIS, COL_COLOR, COL_WIDTH, COL_NAME, COL_VAL, COL_A, COL_B, COL_D, COL_AVG, COL_MIN, COL_MAX, COL_DEL = range(12)
HEADERS = ["", "Renk", "Kalınlık", "İsim", "Değer", "A", "B", "Δ (B−A)", "Ort", "Min", "Maks", ""]


class PlotPanel(PanelBase):
    kind = "plot"
    title = "Grafik"

    def __init__(self, hub):
        super().__init__(hub)
        self.styles: dict[str, dict] = {}
        self._cache: dict[str, tuple] = {}
        self._curves: dict[str, pg.PlotDataItem] = {}
        self._plots: list = []
        self._regions: list = []
        self._vlines: list = []
        self._hover_x: float | None = None
        self._frozen = False
        self._building = False
        self._span: float | None = 30.0

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Üst üste", "Ayrı ayrı"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode)
        self.cursor_check = QCheckBox("İmleçler (A / B)")
        self.cursor_check.setToolTip("İki dikey imleç: aralıktaki Δ, ortalama, min ve maks değerleri tabloda görünür.")
        self.cursor_check.toggled.connect(self._on_cursors)
        self.norm_check = QCheckBox("Normalize (0–1)")
        self.norm_check.setToolTip("Üst üste modda her sinyal kendi aralığında 0–1'e ölçeklenir (yalnızca görünüm).")
        self.norm_check.toggled.connect(lambda _v: self._redraw(full=True))
        top = QHBoxLayout()
        top.addWidget(QLabel("Çizim:"))
        top.addWidget(self.mode_combo)
        top.addSpacing(10)
        top.addWidget(self.cursor_check)
        top.addWidget(self.norm_check)
        top.addStretch()
        self.hint = QLabel("")
        self.hint.setVisible(False)
        top.addWidget(self.hint)

        self.glw = _Glw(self._on_leave)
        self.glw.setBackground("#F7F9FB")
        self.glw.setMinimumHeight(140)
        self._proxy = pg.SignalProxy(self.glw.scene().sigMouseMoved, rateLimit=30, slot=self._on_mouse)

        self.table = QTableWidget(0, len(HEADERS))
        self.table.setHorizontalHeaderLabels(HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        self.table.setMinimumHeight(110)

        split = QSplitter(Qt.Vertical)
        split.addWidget(self.glw)
        split.addWidget(self.table)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setChildrenCollapsible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        self._set_cursor_columns(False)
        self._rebuild()

    # ---------------------------------------------------------- sinyaller / stil
    def add_signal(self, sid: str) -> bool:
        if sid in self.signals_ids:
            return False
        used = {s["color"] for s in self.styles.values()}
        color = next((c for c in PALETTE if c not in used), PALETTE[len(self.styles) % len(PALETTE)])
        self.styles.setdefault(sid, {"color": color, "width": 2.0, "visible": True})
        return super().add_signal(sid)

    def _signals_changed(self):
        self._rebuild()
        self.changed.emit()

    def set_span(self, span):
        self._span = span

    # ---------------------------------------------------------- kurulum
    def _on_mode(self, _i):
        self._rebuild()
        self.changed.emit()

    @property
    def stacked(self) -> bool:
        return self.mode_combo.currentIndex() == 1

    def _rebuild(self):
        """Grafik alanını ve tabloyu sinyal listesine göre baştan kurar."""
        self._building = True
        cursors = self.cursor_check.isChecked()
        old_rng = self._regions[0].getRegion() if self._regions else None
        self.glw.clear()
        self._plots, self._regions, self._vlines, self._curves = [], [], [], {}
        ids = [s for s in self.signals_ids]
        n = max(len(ids), 1)
        count = n if (self.stacked and ids) else 1
        for i in range(count):
            p = self.glw.addPlot(row=i, col=0)
            p.showGrid(x=True, y=True, alpha=0.2)
            p.setClipToView(True)
            p.setDownsampling(auto=True, mode="peak")
            p.getAxis("left").setWidth(58)
            for ax in ("left", "bottom"):
                p.getAxis(ax).setPen("#B7C4D0")
                p.getAxis(ax).setTextPen("#51616F")
            if i == 0:
                first = p
            else:
                p.setXLink(first)
            if i < count - 1:
                p.hideAxis("bottom")
            else:
                p.setLabel("bottom", "Zaman (s)")
            p.getViewBox().setMouseEnabled(x=self._frozen, y=True)
            vline = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#9AA8B5", width=1, style=Qt.DashLine))
            vline.setVisible(False)
            p.addItem(vline, ignoreBounds=True)
            self._vlines.append(vline)
            self._plots.append(p)
        if not self.stacked and self._plots and ids:
            self._plots[0].addLegend(offset=(8, 6), labelTextColor="#121A22",
                                     brush=pg.mkBrush(10, 22, 38, 220), pen=pg.mkPen("#D6DEE6"))
        for i, sid in enumerate(ids):
            st = self.styles[sid]
            target = self._plots[i if self.stacked else 0]
            curve = target.plot([], [], pen=pg.mkPen(st["color"], width=st["width"]),
                                name=label_of(sid))
            curve.setVisible(st["visible"])
            self._curves[sid] = curve
            if self.stacked:
                target.setLabel("left", label_of(sid))
        # imleçler
        if cursors and self._plots:
            self._make_regions(old_rng)
        self._rebuild_table()
        self._building = False
        self.hint.setVisible(not ids)
        self._redraw(full=True)

    def _make_regions(self, rng=None):
        vr = self._plots[0].getViewBox().viewRange()[0]
        if rng is None:
            span = vr[1] - vr[0]
            rng = (vr[0] + 0.55 * span, vr[0] + 0.85 * span)
        for p in self._plots:
            r = pg.LinearRegionItem(values=rng, brush=pg.mkBrush(53, 198, 244, 40),
                                    pen=pg.mkPen("#0E6E8C", width=1.5))
            r.setZValue(10)
            r.sigRegionChanged.connect(self._on_region)
            p.addItem(r, ignoreBounds=True)
            self._regions.append(r)

    def _on_cursors(self, on: bool):
        self._set_cursor_columns(on)
        if on:
            self._make_regions(getattr(self, "_saved_rng", None))
            self._saved_rng = None
        else:
            for p, r in zip(self._plots, self._regions):
                p.removeItem(r)
            self._regions = []
        self._update_stats()
        self.changed.emit()

    def _set_cursor_columns(self, on: bool):
        for c in (COL_A, COL_B, COL_D):
            self.table.setColumnHidden(c, not on)

    def _on_region(self, region):
        rng = region.getRegion()
        for r in self._regions:
            if r is not region:
                r.blockSignals(True)
                r.setRegion(rng)
                r.blockSignals(False)
        self._update_stats()

    # ---------------------------------------------------------- tablo
    def _rebuild_table(self):
        t = self.table
        t.setRowCount(0)
        for r, sid in enumerate(self.signals_ids):
            st = self.styles[sid]
            t.insertRow(r)
            cb = QCheckBox()
            cb.setChecked(st["visible"])
            cb.toggled.connect(lambda v, s=sid: self._set_visible(s, v))
            t.setCellWidget(r, COL_VIS, self._center(cb))
            btn = QPushButton()
            btn.setFixedSize(34, 18)
            btn.setStyleSheet(f"background:{st['color']}; border:1px solid #B7C4D0; border-radius:3px;")
            btn.setToolTip("Rengi değiştir")
            btn.clicked.connect(lambda _c=False, s=sid, b=btn: self._pick_color(s, b))
            t.setCellWidget(r, COL_COLOR, self._center(btn))
            sp = QDoubleSpinBox()
            sp.setRange(0.5, 8.0)
            sp.setSingleStep(0.5)
            sp.setDecimals(1)
            sp.setValue(st["width"])
            sp.setFixedWidth(74)
            sp.valueChanged.connect(lambda v, s=sid: self._set_width(s, v))
            t.setCellWidget(r, COL_WIDTH, self._center(sp))
            name = QTableWidgetItem(label_of(sid))
            name.setToolTip(sid)
            t.setItem(r, COL_NAME, name)
            for c in (COL_VAL, COL_A, COL_B, COL_D, COL_AVG, COL_MIN, COL_MAX):
                it = QTableWidgetItem("—")
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, it)
            x = QPushButton("✕")
            x.setFixedSize(22, 18)
            x.setToolTip("Sinyali bu panelden çıkar")
            x.clicked.connect(lambda _c=False, s=sid: self.remove_signal(s))
            t.setCellWidget(r, COL_DEL, self._center(x))
            t.setRowHeight(r, 30)

    @staticmethod
    def _center(w) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(2, 0, 2, 0)
        lay.setAlignment(Qt.AlignCenter)
        lay.addWidget(w)
        return box

    def _set_visible(self, sid, v):
        self.styles[sid]["visible"] = bool(v)
        if sid in self._curves:
            self._curves[sid].setVisible(bool(v))
        self.changed.emit()

    def _set_width(self, sid, w):
        self.styles[sid]["width"] = float(w)
        self._apply_pen(sid)
        self.changed.emit()

    def _pick_color(self, sid, btn):
        c = QColorDialog.getColor(QColor(self.styles[sid]["color"]), self, "Çizgi rengi")
        if not c.isValid():
            return
        self.styles[sid]["color"] = c.name()
        btn.setStyleSheet(f"background:{c.name()}; border:1px solid #B7C4D0; border-radius:3px;")
        self._apply_pen(sid)
        self.changed.emit()

    def _apply_pen(self, sid):
        cv = self._curves.get(sid)
        if cv is not None:
            st = self.styles[sid]
            cv.setPen(pg.mkPen(st["color"], width=st["width"]))
        # lejant/etiket rengi için yeniden kur
        if not self.stacked and self._plots and self._plots[0].legend is not None:
            self._plots[0].legend.clear()
            for s, c in self._curves.items():
                self._plots[0].legend.addItem(c, label_of(s))

    # ---------------------------------------------------------- veri / çizim
    def refresh(self, span, frozen):
        self._span = span
        if frozen:
            return
        self._redraw(full=False)

    def set_frozen(self, frozen: bool):
        self._frozen = frozen
        for p in self._plots:
            p.getViewBox().setMouseEnabled(x=frozen, y=True)
        if frozen:
            self._redraw(full=True)         # tüm geçmiş: dondurunca uzaklaştırılabilsin
        else:
            for p in self._plots:
                p.getViewBox().enableAutoRange(axis="y", enable=True)
            self._redraw(full=False)

    def _redraw(self, full: bool):
        if self._building or not self._plots:
            return
        now = self.hub.now()
        tmin = None if (full or self._span is None) else now - self._span - 1.0
        norm = self.norm_check.isChecked() and not self.stacked
        for sid, curve in self._curves.items():
            t, v = self.hub.get(sid, tmin)
            self._cache[sid] = (t, v)
            if norm and v.size:
                lo, hi = float(np.min(v)), float(np.max(v))
                v = (v - lo) / ((hi - lo) or 1.0)
            curve.setData(t, v)
        if not self._frozen:
            for p in self._plots[:1]:
                if self._span is None:
                    p.getViewBox().enableAutoRange(axis="x", enable=True)
                else:
                    p.setXRange(now - self._span, now, padding=0)
        self._update_values()
        self._update_stats()

    def _range(self):
        if self._regions:
            a, b = self._regions[0].getRegion()
            return min(a, b), max(a, b), True
        vr = self._plots[0].getViewBox().viewRange()[0] if self._plots else (0, 1)
        return vr[0], vr[1], False

    def _update_values(self):
        for r, sid in enumerate(self.signals_ids):
            t, v = self._cache.get(sid, (np.empty(0), np.empty(0)))
            if self._hover_x is not None:
                val = value_at(t, v, self._hover_x)
            else:
                val = float(v[-1]) if v.size else None
            it = self.table.item(r, COL_VAL)
            if it is not None:
                it.setText(fmt(val))

    def _update_stats(self):
        a, b, cursors = self._range()
        for r, sid in enumerate(self.signals_ids):
            t, v = self._cache.get(sid, (np.empty(0), np.empty(0)))
            sel = (t >= a) & (t <= b) if t.size else np.zeros(0, bool)
            vs = v[sel] if t.size else v
            vals = {COL_AVG: float(vs.mean()) if vs.size else None,
                    COL_MIN: float(vs.min()) if vs.size else None,
                    COL_MAX: float(vs.max()) if vs.size else None}
            if cursors:
                va, vb = value_at(t, v, a), value_at(t, v, b)
                vals[COL_A], vals[COL_B] = va, vb
                vals[COL_D] = (vb - va) if (va is not None and vb is not None) else None
            for c, val in vals.items():
                it = self.table.item(r, c)
                if it is not None:
                    it.setText(fmt(val))

    # ---------------------------------------------------------- fare
    def _on_mouse(self, evt):
        pos = evt[0]
        for p in self._plots:
            if p.sceneBoundingRect().contains(pos):
                x = p.getViewBox().mapSceneToView(pos).x()
                self._hover_x = x
                for vl in self._vlines:
                    vl.setPos(x)
                    vl.setVisible(True)
                self._update_values()
                return
        self._on_leave()

    def _on_leave(self):
        if self._hover_x is None:
            return
        self._hover_x = None
        for vl in self._vlines:
            vl.setVisible(False)
        self._update_values()

    # ---------------------------------------------------------- durum
    def to_state(self) -> dict:
        st = {"signals": list(self.signals_ids), "styles": self.styles,
              "mode": self.mode_combo.currentIndex(), "normalize": self.norm_check.isChecked(),
              "cursors": self.cursor_check.isChecked()}
        if self._regions:
            st["cursor_range"] = list(self._regions[0].getRegion())
        return st

    def from_state(self, state: dict):
        raw_styles = state.get("styles", {})
        self.styles = {str(k): dict(v) for k, v in (raw_styles.items() if isinstance(raw_styles, dict) else [])
                       if isinstance(v, dict)}
        sigs = state.get("signals", [])
        self.signals_ids = [str(x) for x in sigs] if isinstance(sigs, list) else []
        for i, sid in enumerate(self.signals_ids):
            # eksik anahtarlar (color/width/visible) varsayılanla tamamlanır
            base = {"color": PALETTE[i % len(PALETTE)], "width": 2.0, "visible": True}
            base.update({k: v for k, v in self.styles.get(sid, {}).items() if k in base and v is not None})
            self.styles[sid] = base
        self.mode_combo.blockSignals(True)
        try:
            self.mode_combo.setCurrentIndex(max(0, min(int(state.get("mode", 0)), self.mode_combo.count() - 1)))
        except (TypeError, ValueError):
            self.mode_combo.setCurrentIndex(0)
        self.mode_combo.blockSignals(False)
        self.norm_check.blockSignals(True)
        self.norm_check.setChecked(bool(state.get("normalize", False)))
        self.norm_check.blockSignals(False)
        self._saved_rng = tuple(state["cursor_range"]) if state.get("cursor_range") else None
        self.cursor_check.blockSignals(True)
        self.cursor_check.setChecked(False)
        self.cursor_check.blockSignals(False)
        self._set_cursor_columns(False)
        self._rebuild()
        if state.get("cursors"):
            self.cursor_check.setChecked(True)       # _on_cursors kayıtlı aralığı kullanır
        self.changed.emit()


# ============================================================ Gösterge
class GaugePanel(PanelBase):
    kind = "gauge"
    title = "Gösterge"

    def __init__(self, hub):
        super().__init__(hub)
        from app.ui.dashboard_tab import GaugeWidget
        from app.ui.dash_widgets import DarkGauge
        self.gauge = DarkGauge("—", 0.0, 100.0, "")
        self.gauge.setMaximumHeight(16777215)
        self.name_label = QLabel("")
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet("color:#51616F; font-size:11px;")
        self.min_spin, self.max_spin = QDoubleSpinBox(), QDoubleSpinBox()
        for s, v in ((self.min_spin, 0.0), (self.max_spin, 100.0)):
            s.setRange(-1e9, 1e9)
            s.setDecimals(3)
            s.setValue(v)
            s.setFixedWidth(78)
            s.setButtonSymbols(QDoubleSpinBox.NoButtons)
            s.valueChanged.connect(self._on_range)
        self.unit_edit = QLineEdit()
        self.unit_edit.setPlaceholderText("birim")
        self.unit_edit.setFixedWidth(52)
        self.unit_edit.textChanged.connect(self._on_range)
        row = QHBoxLayout()
        row.addWidget(QLabel("Min"))
        row.addWidget(self.min_spin)
        row.addWidget(QLabel("Maks"))
        row.addWidget(self.max_spin)
        row.addWidget(self.unit_edit)
        row.addStretch()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.addWidget(self.gauge, 1)
        lay.addWidget(self.name_label)
        lay.addLayout(row)

    def add_signal(self, sid: str) -> bool:
        self.signals_ids = [sid]            # tek sinyal: yenisi eskisinin yerine geçer
        self._signals_changed()
        return True

    def _signals_changed(self):
        sid = self.signals_ids[0] if self.signals_ids else None
        self.gauge._label = label_of(sid) if sid else "—"
        self.name_label.setText(sid or "")
        self.gauge.update()
        self.changed.emit()

    def _on_range(self, *_):
        lo, hi = self.min_spin.value(), self.max_spin.value()
        if hi <= lo:
            hi = lo + 1.0
        self.gauge.set_range(lo, hi)
        self.gauge._unit = self.unit_edit.text()
        self.gauge.update()
        self.changed.emit()

    def refresh(self, span, frozen):
        if frozen or not self.signals_ids:
            return
        self.gauge.set_value(self.hub.last(self.signals_ids[0]))

    def to_state(self):
        return {"signals": list(self.signals_ids), "min": self.min_spin.value(),
                "max": self.max_spin.value(), "unit": self.unit_edit.text()}

    def from_state(self, state):
        self.min_spin.blockSignals(True)
        self.max_spin.blockSignals(True)
        self.unit_edit.blockSignals(True)
        self.min_spin.setValue(float(state.get("min", 0.0)))
        self.max_spin.setValue(float(state.get("max", 100.0)))
        self.unit_edit.setText(state.get("unit", ""))
        self.min_spin.blockSignals(False)
        self.max_spin.blockSignals(False)
        self.unit_edit.blockSignals(False)
        self._on_range()
        self.signals_ids = list(state.get("signals", []))[:1]
        self._signals_changed()


# ============================================================ Tablo
class TablePanel(PanelBase):
    kind = "table"
    title = "Tablo"
    HEAD = ["İsim", "Değer", "Ort", "Min", "Maks"]

    def __init__(self, hub):
        super().__init__(hub)
        self.table = QTableWidget(0, len(self.HEAD))
        self.table.setHorizontalHeaderLabels(self.HEAD)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.hint = QLabel("")
        self.hint.setVisible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.table, 1)
        lay.addWidget(self.hint)

    def _signals_changed(self):
        self.table.setRowCount(len(self.signals_ids))
        for r, sid in enumerate(self.signals_ids):
            for c in range(len(self.HEAD)):
                it = QTableWidgetItem(label_of(sid) if c == 0 else "—")
                if c == 0:
                    it.setToolTip(sid)
                else:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        self.changed.emit()

    def _menu(self, pos):
        r = self.table.rowAt(pos.y())
        if r < 0 or r >= len(self.signals_ids):
            return
        m = QMenu(self)
        act = m.addAction("Sinyali çıkar")
        if m.exec(self.table.viewport().mapToGlobal(pos)) is act:
            self.remove_signal(self.signals_ids[r])

    def refresh(self, span, frozen):
        if frozen:
            return
        tmin = None if span is None else self.hub.now() - span
        for r, sid in enumerate(self.signals_ids):
            t, v = self.hub.get(sid, tmin)
            vals = [float(v[-1]) if v.size else None,
                    float(v.mean()) if v.size else None,
                    float(v.min()) if v.size else None,
                    float(v.max()) if v.size else None]
            for c, val in enumerate(vals, start=1):
                it = self.table.item(r, c)
                if it is not None:
                    it.setText(fmt(val))


# ============================================================ Kontrol
class ControlPanel(PanelBase):
    """Simülasyon Girişleri'ni (Start, Spark, Throttle, Altitude ...) gönderir.
    Gönderim rolü/eşleme kontrolleri Ana Sayfa'daki panelle AYNIDIR."""
    kind = "control"
    title = "Kontrol"

    def __init__(self, hub, input_defs, send_cb, values_cb):
        super().__init__(hub)
        self._send = send_cb
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        row = 0
        self._widgets = {}
        cur = values_cb() if values_cb else {}
        for d in input_defs:
            if not d.enabled:
                continue
            grid.addWidget(QLabel(f"{d.label}" + (f" [{d.unit}]" if d.unit else "")), row, 0)
            if d.kind == "switch":
                w = QCheckBox("Açık")
                w.setChecked(bool(cur.get(d.key, 0)))
                w.toggled.connect(lambda v, k=d.key: self._send(k, 1.0 if v else 0.0))
            else:
                w = QDoubleSpinBox()
                w.setRange(d.minimum, d.maximum)
                w.setDecimals(3 if d.kind == "const" else 1)
                w.setSingleStep(0.5 if d.kind == "slider" else 0.01)
                w.setValue(float(cur.get(d.key, d.minimum)))
                w.editingFinished.connect(lambda k=d.key, ww=w: self._send(k, ww.value()))
            grid.addWidget(w, row, 1)
            self._widgets[d.key] = w
            row += 1
        note = QLabel("")
        note.setVisible(False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(grid)
        lay.addWidget(note)
        lay.addStretch()

    def add_signal(self, sid):      # kontrol panelinde sinyal kavramı yok
        return False

    def to_state(self):
        return {}

    def from_state(self, state):
        pass
