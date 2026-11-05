"""Ana Sayfa > Canlı Trendler: mühendislik amaçlı zaman grafiği.

Normalize (0–1) YOK: her sinyal kendi GERÇEK birimiyle çizilir; aynı birimdeki
sinyaller bir ekseni paylaşır, farklı birimler ayrı (renkli) Y eksenlerine gider.
Özellikler: zaman aralığı (60 sn / 5 dk / 10 dk / 1 sa), yakınlaştır/uzaklaştır,
fare ile kaydırma/yakınlaştırma (görünüm donar, "Canlı" ile geri dönülür),
A/B imleçleri (değer + Δ), iki sinyalin farkı (A−B) eğrisi, test başlangıç/bitiş
işaretleri ve CSV / MAT / MDF dışa aktarım.
"""

import csv
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QVBoxLayout, QWidget,
)

from app.ui.dash_widgets import (
    DK_AMBER, DK_CYAN, DK_GREEN, DK_INK, DK_LINE, DK_LINE2, DK_MUT, DK_ORANGE, DK_PURPLE,
    IconButton, icon_pixmap,
)

WINDOWS = [("60 sn", 60.0), ("5 dk", 300.0), ("10 dk", 600.0), ("1 sa", 3600.0)]
MAX_HISTORY_S = 3600.0
PALETTE = [DK_CYAN, DK_ORANGE, DK_PURPLE, DK_GREEN, "#f472b6", "#facc15", "#60a5fa", "#fb7185"]
PLOT_BG = "#0b1a2b"


class _RelAxis(pg.AxisItem):
    """Alt eksen: referans ana göre geçen süre (−45 s / −5 dk)."""

    def __init__(self, panel, **kw):
        super().__init__(**kw)
        self._panel = panel

    _STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]

    def tickValues(self, minVal, maxVal, size):  # noqa: N802
        """Ticks 'şimdiye' göre yuvarlak aralıklarla (−10, −20 sn / −1, −2 dk) yerleşir."""
        ref = self._panel.ref_time()
        span = max(maxVal - minVal, 1e-6)
        step = next((s for s in self._STEPS if span / s <= 8), self._STEPS[-1])
        k0 = int((ref - maxVal) // step)
        k1 = int((ref - minVal) // step) + 1
        vals = [ref - k * step for k in range(k0, k1 + 1) if minVal <= ref - k * step <= maxVal]
        return [(step, vals)]

    def tickStrings(self, values, scale, spacing):  # noqa: N802
        ref = self._panel.ref_time()
        win = self._panel.window_s()
        out = []
        for v in values:
            d = v - ref
            if abs(d) < 0.5:
                out.append("şimdi" if self._panel.is_live() else "0")
            elif win > 120:
                out.append(f"{d / 60:.0f} dk")
            else:
                out.append(f"{d:.0f} sn")
        return out


class _Series:
    def __init__(self, key, label, unit, color):
        self.key, self.label, self.unit, self.color = key, label, unit, color
        self.t: list = []
        self.v: list = []
        self.curve = None
        self.vb = None

    def append(self, t, v):
        self.t.append(t)
        self.v.append(v)
        cutoff = t - MAX_HISTORY_S
        if self.t[0] < cutoff:
            n = int(np.searchsorted(np.asarray(self.t), cutoff))
            del self.t[:n]
            del self.v[:n]

    def arrays(self):
        return np.asarray(self.t, dtype=float), np.asarray(self.v, dtype=float)


class TrendPanel(QFrame):
    test_started = Signal(float)      # epoch
    test_ended = Signal(float, float)  # epoch, süre (sn)
    pick_requested = Signal()          # sinyal seçim penceresini aç

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("trendCard")
        self._series: dict[str, _Series] = {}
        self._order: list[str] = []
        self._window = 60.0
        self._live = True
        self._frozen_ref = time.time()
        self._extra_vbs: list = []
        self._extra_axes: list = []
        self._events: list = []          # (t, etiket)
        self._event_items: list = []
        self._test_start: float | None = None
        self._dirty = True
        self._diff_pair: tuple | None = None
        self._applying_range = False

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 8, 14, 8)
        root.setSpacing(4)

        # ---- üst satır
        head = QHBoxLayout()
        head.setSpacing(4)
        title = QLabel("CANLI TRENDLER")
        title.setObjectName("cardTitle")
        self.test_label = QLabel("")
        self.test_label.setObjectName("chipGreen")
        self.test_label.setVisible(False)
        self.btn_test_start = QPushButton("Başlat")
        self.btn_test_start.setProperty("compact", True)
        self.btn_test_start.setProperty("tone", "go")
        self.btn_test_start.setToolTip("Test başlangıç işareti ekle ve test süresini başlat")
        self.btn_test_start.clicked.connect(self.start_test)
        self.btn_test_end = QPushButton("Bitir")
        self.btn_test_end.setProperty("compact", True)
        self.btn_test_end.setEnabled(False)
        self.btn_test_end.setToolTip("Test bitiş işareti ekle")
        self.btn_test_end.clicked.connect(self.end_test)
        for b, name in ((self.btn_test_start, "flag"), (self.btn_test_end, "flag")):
            b.setIcon(self._qicon(name, DK_MUT))
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.btn_test_start)
        head.addWidget(self.btn_test_end)

        self._win_buttons: list = []
        seg = QHBoxLayout()
        seg.setSpacing(0)
        for i, (text, secs) in enumerate(WINDOWS):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setProperty("seg", True)
            b.setChecked(i == 0)
            b.clicked.connect(lambda _c, s=secs: self.set_window(s))
            seg.addWidget(b)
            self._win_buttons.append((secs, b))
        head.addLayout(seg)

        self.btn_zoom_in = IconButton("zoom_in", 28)
        self.btn_zoom_in.setToolTip("Yakınlaştır (zaman penceresini yarıya indir)")
        self.btn_zoom_in.clicked.connect(lambda: self.zoom(0.5))
        self.btn_zoom_out = IconButton("zoom_out", 28)
        self.btn_zoom_out.setToolTip("Uzaklaştır (zaman penceresini iki katına çıkar)")
        self.btn_zoom_out.clicked.connect(lambda: self.zoom(2.0))
        self.btn_live = IconButton("fit", 28)
        self.btn_live.setToolTip("Canlı görünüme dön / pencereye sığdır")
        self.btn_live.clicked.connect(self.go_live)
        self.btn_cursor = IconButton("cursor", 28)
        self.btn_cursor.setCheckable(True)
        self.btn_cursor.setToolTip("A/B imleçleri: görünümü durdurur, iki zamandaki değerleri ve farkı gösterir")
        self.btn_cursor.toggled.connect(self._on_cursor_toggled)
        self.btn_pick = IconButton("sliders", 28)
        self.btn_pick.setToolTip("Grafikte çizilecek sinyalleri seç")
        self.btn_pick.clicked.connect(self.pick_requested.emit)
        self.btn_compare = IconButton("compare", 28)
        self.btn_compare.setToolTip("Karşılaştır: iki sinyalin farkını (A − B) ayrı bir eğri olarak çizer")
        self.btn_compare.clicked.connect(self._on_compare)
        self.btn_export = IconButton("download", 28)
        self.btn_export.setToolTip("Dışa aktar: CSV / MAT / MDF")
        menu = QMenu(self.btn_export)
        menu.addAction("CSV (.csv)", lambda: self.export("csv"))
        menu.addAction("MAT (.mat)", lambda: self.export("mat"))
        menu.addAction("MDF (.mf4)", lambda: self.export("mdf"))
        self.btn_export.setMenu(menu)
        self.btn_detach = IconButton("detach", 28)
        self.btn_detach.setToolTip("Trend grafiğini ayrı pencerede aç (ör. ikinci monitör)")
        self.btn_detach.clicked.connect(lambda: self.detacher.detach())
        from app.ui.detach import PanelDetacher
        self.detacher = PanelDetacher(self, "Trend", self.btn_detach)
        for w in (self.btn_pick, self.btn_zoom_in, self.btn_zoom_out, self.btn_live, self.btn_cursor,
                  self.btn_compare, self.btn_export, self.btn_detach):
            head.addWidget(w)
        root.addLayout(head)

        # ---- gösterge satırı (renkli etiketler) + imleç özeti
        self.legend_row = QHBoxLayout()
        self.legend_row.setContentsMargins(4, 0, 0, 0)
        self.legend_row.setSpacing(14)
        root.addLayout(self.legend_row)
        self.cursor_summary = QLabel("")
        self.cursor_summary.setObjectName("mutedSmall")
        self.legend_row.addStretch(1)
        self.legend_row.addWidget(self.test_label)
        self.legend_row.addWidget(self.cursor_summary)

        # ---- grafik
        self.plot = pg.PlotWidget(background=PLOT_BG, axisItems={"bottom": _RelAxis(self, orientation="bottom")})
        self.pi = self.plot.getPlotItem()
        self.pi.showGrid(x=True, y=True, alpha=0.18)
        self.pi.setMenuEnabled(False)
        self.pi.hideButtons()
        for ax in ("left", "bottom"):
            self.pi.getAxis(ax).setTextPen(pg.mkPen(DK_MUT))
            self.pi.getAxis(ax).setPen(pg.mkPen(DK_LINE2))
        self.vb = self.pi.vb
        self.vb.setMouseEnabled(x=True, y=False)
        self.vb.sigRangeChangedManually.connect(self._on_manual_range)
        self.vb.sigResized.connect(self._sync_geometry)
        self.plot.setMinimumHeight(110)
        root.addWidget(self.plot, 1)

        # imleç çizgileri
        self._cur_a = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#e8f0f8", width=1.4),
                                      label="A", labelOpts={"position": 0.06, "color": "#e8f0f8"})
        self._cur_b = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#8fa6bd", width=1.2, style=Qt.DashLine),
                                      label="B", labelOpts={"position": 0.06, "color": "#8fa6bd"})
        for ln in (self._cur_a, self._cur_b):
            ln.setZValue(50)
            ln.sigPositionChanged.connect(self._update_cursor_readout)
            self.vb.addItem(ln, ignoreBounds=True)
            ln.setVisible(False)

        self.readout = QLabel(self.plot)
        self.readout.setObjectName("trendReadout")
        self.readout.setTextFormat(Qt.RichText)
        self.readout.setVisible(False)
        self.readout.move(78, 8)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._rebuild()

    # ------------------------------------------------------------ yardımcılar
    @staticmethod
    def _qicon(name, color):
        from PySide6.QtGui import QIcon
        return QIcon(icon_pixmap(name, color, 16))

    def window_s(self) -> float:
        return self._window

    def is_live(self) -> bool:
        return self._live

    def ref_time(self) -> float:
        return time.time() if self._live else self._frozen_ref

    # ------------------------------------------------------------ sinyaller
    def set_series(self, specs: list):
        """specs: [{'key','label','unit'}]; mevcut geçmiş korunur."""
        new_order = [s["key"] for s in specs]
        for s in specs:
            ser = self._series.get(s["key"])
            if ser is None:
                ser = _Series(s["key"], s["label"], s.get("unit", ""), PALETTE[0])
                self._series[s["key"]] = ser
            ser.label, ser.unit = s["label"], s.get("unit", "")
        for i, key in enumerate(new_order):
            self._series[key].color = PALETTE[i % len(PALETTE)]
        derived = [k for k in self._order if k.startswith("d:") and k in self._series]
        self._order = new_order + [k for k in derived if k not in new_order]
        self._rebuild()

    def append(self, key: str, value, t: float | None = None):
        ser = self._series.get(key)
        if ser is None or not isinstance(value, (int, float)):
            return
        ser.append(time.time() if t is None else t, float(value))
        self._dirty = True

    def clear(self):
        for ser in self._series.values():
            ser.t.clear()
            ser.v.clear()
        self._dirty = True

    # ------------------------------------------------------------ çizim kurulumu
    def _remove_extra(self):
        for vb in self._extra_vbs:
            try:
                self.pi.scene().removeItem(vb)
            except Exception:
                pass
        for ax in self._extra_axes:
            try:
                self.pi.layout.removeItem(ax)
                ax.setParentItem(None)
                self.pi.scene().removeItem(ax)
            except Exception:
                pass
        self._extra_vbs, self._extra_axes = [], []
        self.pi.hideAxis("right")

    def _rebuild(self):
        # eski eğriler
        for ser in self._series.values():
            if ser.curve is not None:
                try:
                    ser.curve.getViewBox().removeItem(ser.curve)
                except Exception:
                    pass
                ser.curve = None
        self._remove_extra()
        # birim grupları (sıra korunur)
        groups: list = []
        for key in self._order:
            ser = self._series.get(key)
            if ser is None:
                continue
            for g in groups:
                if g["unit"] == ser.unit:
                    g["series"].append(ser)
                    break
            else:
                groups.append({"unit": ser.unit, "series": [ser]})
        left_axis = self.pi.getAxis("left")
        left_axis.setLabel("")
        for gi, g in enumerate(groups):
            first = g["series"][0]
            if gi == 0:
                vb, ax = self.vb, left_axis
            elif gi == 1:
                vb = pg.ViewBox()
                self.pi.showAxis("right")
                ax = self.pi.getAxis("right")
                self.pi.scene().addItem(vb)
                ax.linkToView(vb)
                vb.setXLink(self.vb)
                self._extra_vbs.append(vb)
            else:
                vb = pg.ViewBox()
                ax = pg.AxisItem("right")
                self.pi.layout.addItem(ax, 2, 1 + gi)
                self.pi.scene().addItem(vb)
                ax.linkToView(vb)
                vb.setXLink(self.vb)
                self._extra_vbs.append(vb)
                self._extra_axes.append(ax)
            vb.setMouseEnabled(x=True, y=False)
            vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            vb.setAutoVisible(y=True)
            ax.setTextPen(pg.mkPen(first.color))
            ax.setPen(pg.mkPen(first.color))
            ax.setLabel(f"{first.label if len(g['series']) == 1 else ''}"
                        f"{' ' if len(g['series']) == 1 and g['unit'] else ''}"
                        f"{'[' + g['unit'] + ']' if g['unit'] else ''}", color=first.color)
            ax.setStyle(tickTextOffset=4)
            g["vb"] = vb
            for ser in g["series"]:
                ser.curve = pg.PlotDataItem(pen=pg.mkPen(ser.color, width=2), name=ser.label)
                ser.curve.setClipToView(True)
                ser.curve.setDownsampling(auto=True, method="peak")
                vb.addItem(ser.curve)
                ser.vb = vb
        self._groups = groups
        self._sync_geometry()
        self._rebuild_legend()
        self._draw_events()
        self._dirty = True

    def _sync_geometry(self):
        for vb in self._extra_vbs:
            vb.setGeometry(self.vb.sceneBoundingRect())
            vb.linkedViewChanged(self.vb, vb.XAxis)

    def _rebuild_legend(self):
        while self.legend_row.count() > 3:      # son 3: stretch + test etiketi + imleç özeti
            it = self.legend_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        pos = 0
        for key in self._order:
            ser = self._series.get(key)
            if ser is None:
                continue
            u = f" [{ser.unit}]" if ser.unit else ""
            lab = QLabel(f'<span style="color:{ser.color}; font-size:14px;">●</span>&nbsp;{ser.label}{u}')
            lab.setTextFormat(Qt.RichText)
            lab.setObjectName("legendItem")
            self.legend_row.insertWidget(pos, lab)
            pos += 1

    # ------------------------------------------------------------ zaman penceresi
    def set_window(self, secs: float):
        self._window = max(5.0, min(MAX_HISTORY_S, secs))
        for s, b in self._win_buttons:
            b.setChecked(abs(s - self._window) < 1e-6)
        self.go_live()

    def zoom(self, factor: float):
        """Pencereyi büyütür/küçültür; canlıysa sağ kenar 'şimdi' kalır,
        değilse görünümün ortası sabit tutulur."""
        lo, hi = self.vb.viewRange()[0]
        if self._live:
            self._window = max(5.0, min(MAX_HISTORY_S, self._window * factor))
            for s, b in self._win_buttons:
                b.setChecked(abs(s - self._window) < 1e-6)
        else:
            mid = (lo + hi) / 2
            half = max(2.5, min(MAX_HISTORY_S / 2, (hi - lo) / 2 * factor))
            self._apply_x(mid - half, mid + half)
            self._window = half * 2
        self._dirty = True

    def go_live(self):
        self._live = True
        self._dirty = True
        self._tick()

    def _apply_x(self, lo, hi):
        self._applying_range = True
        try:
            self.vb.setXRange(lo, hi, padding=0)
        finally:
            self._applying_range = False

    def _on_manual_range(self, *_):
        if self._applying_range:
            return
        # kullanıcı fareyle kaydırdı/yakınlaştırdı -> canlı takibi bırak
        if self._live:
            self._live = False
            self._frozen_ref = time.time()
        lo, hi = self.vb.viewRange()[0]
        self._window = max(5.0, hi - lo)

    # ------------------------------------------------------------ periyodik çizim
    def _tick(self):
        now = time.time()
        if self._live:
            self._apply_x(now - self._window, now)
        if self._dirty or self._live:
            lo, hi = self.vb.viewRange()[0]
            margin = (hi - lo) * 0.05
            for ser in self._series.values():
                if ser.curve is None:
                    continue
                t, v = ser.arrays()
                if len(t):
                    i0 = int(np.searchsorted(t, lo - margin))
                    ser.curve.setData(t[max(0, i0 - 1):], v[max(0, i0 - 1):])
                else:
                    ser.curve.setData([], [])
            self._dirty = False
        if self._test_start is not None:
            el = int(now - self._test_start)
            self.test_label.setText(f"⚑ Test süresi {el // 60:02d}:{el % 60:02d}")
        if self.btn_cursor.isChecked():
            self._update_cursor_readout()

    # ------------------------------------------------------------ imleçler
    def _on_cursor_toggled(self, on: bool):
        for ln in (self._cur_a, self._cur_b):
            ln.setVisible(on)
        self.readout.setVisible(on)
        if on:
            hi = self.ref_time()
            if self._live:
                self._live = False
                self._frozen_ref = hi
            lo = hi - self._window
            self._cur_a.setPos(hi - (hi - lo) * 0.25)
            self._cur_b.setPos(hi - (hi - lo) * 0.65)
            self._update_cursor_readout()
        else:
            self.cursor_summary.setText("")

    def values_at(self, t: float) -> dict:
        out = {}
        for key in self._order:
            ser = self._series.get(key)
            if ser is None or not ser.t:
                continue
            ta, va = ser.arrays()
            if t < ta[0] or t > ta[-1]:
                continue
            out[key] = float(np.interp(t, ta, va))
        return out

    def _update_cursor_readout(self, *_):
        if not self.btn_cursor.isChecked():
            return
        ta, tb = float(self._cur_a.value()), float(self._cur_b.value())
        ref = self.ref_time()
        va, vb = self.values_at(ta), self.values_at(tb)
        rows = [f'<tr><td></td><td align="right" style="color:{DK_MUT}">A</td>'
                f'<td align="right" style="color:{DK_MUT}">B</td><td align="right" style="color:{DK_MUT}">Δ (A−B)</td></tr>']
        for key in self._order:
            ser = self._series.get(key)
            if ser is None:
                continue
            a, b = va.get(key), vb.get(key)
            f = lambda x: "—" if x is None else f"{x:.4g}"
            d = "—" if a is None or b is None else f"{a - b:+.4g}"
            rows.append(f'<tr><td style="color:{ser.color}">● {ser.label}</td>'
                        f'<td align="right">&nbsp;&nbsp;{f(a)}</td><td align="right">&nbsp;&nbsp;{f(b)}</td>'
                        f'<td align="right" style="color:{DK_MUT}">&nbsp;&nbsp;{d}</td></tr>')
        self.readout.setText(f'<table cellspacing="1" style="color:{DK_INK}">{"".join(rows)}</table>')
        self.readout.adjustSize()
        self.cursor_summary.setText(
            f"İmleç A: {ta - ref:.1f} sn  ·  B: {tb - ref:.1f} sn  ·  Δt {abs(ta - tb):.1f} sn")

    # ------------------------------------------------------------ iki sinyal farkı
    def _on_compare(self):
        names = {s.label: k for k, s in self._series.items() if not k.startswith("d:")}
        if len(names) < 2:
            QMessageBox.information(self.window(), "Karşılaştır", "Fark için en az iki sinyal seçili olmalı.")
            return
        labels = list(names)
        a, ok = QInputDialog.getItem(self.window(), "Karşılaştır", "Birinci sinyal (A):", labels, 0, False)
        if not ok:
            return
        b, ok = QInputDialog.getItem(self.window(), "Karşılaştır", "İkinci sinyal (B):", labels, min(1, len(labels) - 1), False)
        if not ok or a == b:
            return
        ka, kb = names[a], names[b]
        sa, sb = self._series[ka], self._series[kb]
        if sa.unit != sb.unit:
            QMessageBox.warning(self.window(), "Karşılaştır",
                                f"Birimler farklı ({sa.unit or '—'} / {sb.unit or '—'}); fark anlamlı olmaz.")
            return
        key = f"d:{ka}|{kb}"
        ser = _Series(key, f"{a} − {b}", sa.unit, "#ffffff")
        ta, va = sa.arrays()
        tb, vb = sb.arrays()
        if len(ta) and len(tb):
            lo, hi = max(ta[0], tb[0]), min(ta[-1], tb[-1])
            grid = ta[(ta >= lo) & (ta <= hi)]
            ser.t = list(grid)
            ser.v = list(np.interp(grid, ta, va) - np.interp(grid, tb, vb))
        self._series[key] = ser
        if key not in self._order:
            self._order.append(key)
        self._rebuild()

    # ------------------------------------------------------------ test işaretleri
    def start_test(self):
        now = time.time()
        self._test_start = now
        self.add_event("Test Başlangıcı", now, "#22c55e")
        self.btn_test_start.setEnabled(False)
        self.btn_test_end.setEnabled(True)
        self.test_label.setVisible(True)
        self.test_started.emit(now)

    def end_test(self):
        if self._test_start is None:
            return
        now = time.time()
        dur = now - self._test_start
        self.add_event("Test Bitişi", now, "#ef4444")
        self._test_start = None
        self.btn_test_start.setEnabled(True)
        self.btn_test_end.setEnabled(False)
        self.test_label.setText(f"⚑ Son test: {int(dur) // 60:02d}:{int(dur) % 60:02d}")
        self.test_ended.emit(now, dur)

    def add_event(self, label: str, t: float, color: str):
        self._events.append((t, label, color))
        self._draw_events()

    def _draw_events(self):
        for it in self._event_items:
            try:
                self.vb.removeItem(it)
            except Exception:
                pass
        self._event_items = []
        for t, label, color in self._events:
            stamp = time.strftime("%H:%M:%S", time.localtime(t))
            ln = pg.InfiniteLine(pos=t, angle=90, movable=False, pen=pg.mkPen(color, width=1.4, style=Qt.DashLine),
                                 label=f"⚑ {label} {stamp}",
                                 labelOpts={"position": 0.94, "color": color, "fill": (8, 18, 31, 200),
                                            "anchors": [(0, 0), (0, 0)]})
            ln.setZValue(40)
            self.vb.addItem(ln, ignoreBounds=True)
            self._event_items.append(ln)

    @property
    def events(self) -> list:
        return list(self._events)

    # ------------------------------------------------------------ dışa aktarım
    def _export_data(self):
        """{etiket: (t, v, birim)} + olaylar. Türetilmiş (fark) eğriler de dahil."""
        data = {}
        for key in self._order:
            ser = self._series.get(key)
            if ser is None or not ser.t:
                continue
            t, v = ser.arrays()
            data[ser.label] = (t, v, ser.unit)
        return data, list(self._events)

    def export(self, fmt: str, path: str | None = None):
        data, events = self._export_data()
        if not data:
            QMessageBox.information(self.window(), "Dışa aktar", "Dışa aktarılacak veri yok.")
            return None
        ext = {"csv": "csv", "mat": "mat", "mdf": "mf4"}[fmt]
        if path is None:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            path, _ = QFileDialog.getSaveFileName(self.window(), "Dışa aktar", f"trend_{stamp}.{ext}",
                                                  f"{fmt.upper()} (*.{ext})")
            if not path:
                return None
        try:
            if fmt == "csv":
                write_csv(path, data, events)
            elif fmt == "mat":
                write_mat(path, data, events)
            else:
                write_mdf(path, data, events)
        except ImportError as exc:
            QMessageBox.warning(self.window(), "Dışa aktar", f"Bu biçim için gerekli paket yok: {exc.name or exc}")
            return None
        except Exception as exc:
            QMessageBox.critical(self.window(), "Dışa aktar", f"Yazılamadı: {exc}")
            return None
        return path


# ---------------------------------------------------------------------------
# Dosya yazıcılar (arayüzden bağımsız, test edilebilir)
# ---------------------------------------------------------------------------
def write_csv(path: str, data: dict, events: list):
    """Geniş CSV: her satır bir zaman damgası; o anda örnek yoksa hücre boş.
    Son sütun 'Olay' test başlangıç/bitiş işaretlerini taşır."""
    names = list(data)
    rows: dict = {}
    for n in names:
        t, v, _u = data[n]
        for ti, vi in zip(t, v):
            rows.setdefault(round(float(ti), 3), {})[n] = float(vi)
    for et, label, _c in events:
        rows.setdefault(round(float(et), 3), {})["__olay__"] = label
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Zaman (epoch s)", "Zaman"] + [f"{n} [{data[n][2]}]" if data[n][2] else n for n in names] + ["Olay"])
        for t in sorted(rows):
            r = rows[t]
            w.writerow([f"{t:.3f}", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(t))]
                       + [("" if n not in r else repr(r[n])) for n in names] + [r.get("__olay__", "")])


def write_mat(path: str, data: dict, events: list):
    from scipy.io import savemat
    out = {}
    used = set()
    for n, (t, v, u) in data.items():
        name = "".join(c if c.isalnum() else "_" for c in n)
        if not name or not (name[0].isalpha()):
            name = "s_" + name
        base, k = name, 2
        while name in used:
            name, k = f"{base}_{k}", k + 1
        used.add(name)
        out[name] = {"time": np.asarray(t, float), "values": np.asarray(v, float), "unit": u}
    out["events_time"] = np.asarray([e[0] for e in events], float)
    out["events_label"] = np.asarray([e[1] for e in events], dtype=object)
    savemat(path, out)


def write_mdf(path: str, data: dict, events: list):
    from asammdf import MDF, Signal
    mdf = MDF(version="4.10")
    sigs = [Signal(samples=np.asarray(v, float), timestamps=np.asarray(t, float), name=n, unit=u)
            for n, (t, v, u) in data.items()]
    mdf.append(sigs)
    if events:
        mdf.append([Signal(samples=np.arange(1, len(events) + 1, dtype=float),
                           timestamps=np.asarray([e[0] for e in events], float),
                           name="Test_Olaylari", comment="; ".join(f"{i + 1}={e[1]}" for i, e in enumerate(events)))])
    mdf.save(path, overwrite=True)
