"""Ana Sayfa > Canlı Trendler: mühendislik amaçlı zaman grafiği.

Normalize (0–1) YOK: her sinyal kendi GERÇEK birimiyle çizilir; aynı birimdeki
sinyaller bir ekseni paylaşır, farklı birimler ayrı (renkli) Y eksenlerine gider.
Özellikler: zaman aralığı (60 sn / 5 dk / 10 dk / 1 sa), yakınlaştır/uzaklaştır,
fare ile kaydırma/yakınlaştırma (görünüm donar, "Canlı" ile geri dönülür),
A/B imleçleri (değer + Δ), iki sinyalin farkı (A−B) eğrisi, test başlangıç/bitiş
işaretleri ve CSV / MAT / MDF dışa aktarım.
"""

import logging
import csv
import math
import time

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QMenu, QMessageBox,
    QPushButton, QSizePolicy, QSplitter, QStackedLayout, QVBoxLayout, QWidget,
)

from app import theme
from app.trend_model import (
    DEFAULT_MAX_GAP_S, SignalView, TrendLayout, apply_view_transform, cursor_rows, cut_at, range_stats, sample_at,
)
from app.ui import trend_signal_table as sigtab
from app.ui.dash_widgets import (
    DK_CYAN, DK_GREEN, DK_INK, DK_LINE2, DK_MUT, DK_ORANGE, DK_PURPLE, IconButton, format_value, icon_pixmap,
)

log = logging.getLogger(__name__)

WINDOWS = [("60 sn", 60.0), ("5 dk", 300.0), ("10 dk", 600.0), ("1 sa", 3600.0)]
MAX_HISTORY_S = 3600.0
MAX_GAP_S = DEFAULT_MAX_GAP_S       # imleçte iki örnek arası bundan uzunsa aradaki değer UYDURULMAZ (veri yok)
PALETTE = [DK_CYAN, DK_ORANGE, DK_PURPLE, DK_GREEN, "#D6336C", "#B58900", theme.BLUE, theme.DANGER]
PLOT_BG = theme.paint("@@SURFACE_SUBTLE@@")


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
        # Görünüm durumu (veriyi DEĞİŞTİRMEZ): bkz. app/trend_model.py
        self.visible = True
        self.frozen_at: float | None = None   # freeze anı; veri alımı sürer, yalnızca görüntü donar
        self.offset = 0.0
        self.scale = 1.0
        self.group = ""
        self.source = ""
        self.own_strip = False

    def append(self, t, v):
        self.t.append(t)
        self.v.append(v)
        cutoff = t - MAX_HISTORY_S
        if self.t[0] < cutoff:
            n = int(np.searchsorted(np.asarray(self.t), cutoff))
            del self.t[:n]
            del self.v[:n]

    def arrays(self):
        """(t, v) numpy dizileri. Büyük (kayıtlı) serilerde her tikte listeden yeniden dönüştürmemek için önbelleklenir;
        önbellek uzunluk + son örnek değişince geçersiz olur (canlı seride her append'de)."""
        n = len(self.t)
        key = (n, self.t[-1] if n else None, self.v[-1] if n else None)
        c = getattr(self, "_arr_cache", None)
        if c is not None and c[0] == key:
            return c[1], c[2]
        t, v = np.asarray(self.t, dtype=float), np.asarray(self.v, dtype=float)
        self._arr_cache = (key, t, v)
        return t, v

    def view_arrays(self):
        """Görüntülenen (freeze uygulanmış) HAM veri; ofset/ölçek uygulanmamıştır."""
        t, v = self.arrays()
        return cut_at(t, v, self.frozen_at)


class TrendPanel(QFrame):
    test_started = Signal(float)      # epoch
    test_ended = Signal(float, float)  # epoch, süre (sn)
    pick_requested = Signal()          # sinyal seçim penceresini aç

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("trendCard")
        self.setProperty("accent", "purple")
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
        self._strip_mode = True           # varsayılan: her birim kendi şeridinde (tek grafikte çok eksen okunmuyordu)
        self._strips: list = []           # şerit modunda PlotItem'lar (yukarıdan aşağıya)
        self._strip_lines: list = []      # her şeritte (A çizgisi, B çizgisi)
        self._strip_titles: dict = {}
        self._strip_texts: list = []      # şerit içi "ad + o anki değer" yazıları
        self._cursor_vals: tuple | None = None   # (A değerleri, B değerleri): imleç açıkken şerit yazılarında
        self._color_override: dict = {}   # key -> kullanıcının seçtiği renk (oturum boyunca korunur)
        self._static = False              # True: kayıtlı oturum analizi (canlı veri gelmez)
        self._y_free = False              # True: dikey kaydırma/yakınlaştırma serbest (otomatik ölçek kapalı)
        self.layout_path: str | None = None   # verilirse kullanıcı değişiklikleri buraya otomatik kaydedilir
        self._layout_dirty = False

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
        self.btn_test_start = QPushButton("İşaretle")
        self.btn_test_start.setProperty("compact", True)
        self.btn_test_start.setProperty("tone", "go")
        self.btn_test_start.setToolTip("Grafiğe başlangıç işareti koyar ve süreyi sayar. Veri KAYDI başlatmaz "
                                      "(kayıt için Tanılama ve Oturum sayfası)")
        self.btn_test_start.clicked.connect(self.start_test)
        self.btn_test_end = QPushButton("İşareti bitir")
        self.btn_test_end.setProperty("compact", True)
        self.btn_test_end.setEnabled(False)
        self.btn_test_end.setToolTip("Grafiğe bitiş işareti koyar (veri kaydını durdurmaz)")
        self.btn_test_end.clicked.connect(self.end_test)
        for b, name in ((self.btn_test_start, "flag"), (self.btn_test_end, "flag")):
            b.setIcon(self._qicon(name, DK_MUT))
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.btn_test_start)
        head.addWidget(self.btn_test_end)

        self.btn_strips = IconButton("trend", 28)       # yalnız simge: araç satırının asgari genişliği artmasın
        self.btn_strips.setCheckable(True)
        self.btn_strips.setChecked(True)
        self.btn_strips.setToolTip("Şerit modu: her birim (rpm, °C, bar...) kendi şeridinde, kendi ölçeğinde ve "
                                   "ortak zaman çizgisinde görünür; yanında o anki değer yazar. Kapalıysa tüm "
                                   "sinyaller tek grafikte, çok eksenli çizilir.")
        self.btn_strips.toggled.connect(self._set_strip_mode)
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
        head.addSpacing(6)
        head.addWidget(self.btn_strips)        # üst satırda boşluk var; araç satırını genişletmesin

        self.btn_zoom_in = IconButton("zoom_in", 28)
        self.btn_zoom_in.setToolTip("Yakınlaştır (zaman penceresini yarıya indir)")
        self.btn_zoom_in.clicked.connect(lambda: self.zoom(0.5))
        self.btn_zoom_out = IconButton("zoom_out", 28)
        self.btn_zoom_out.setToolTip("Uzaklaştır (zaman penceresini iki katına çıkar)")
        self.btn_zoom_out.clicked.connect(lambda: self.zoom(2.0))
        self.btn_live = self._tool_button("fit", "Canlı")
        self.btn_live.setToolTip("Canlı görünüme dön / pencereye sığdır")
        self.btn_live.clicked.connect(self.go_live)
        self.btn_cursor = self._tool_button("cursor", "A/B İmleç")
        self.btn_cursor.setCheckable(True)
        self.btn_cursor.setToolTip("A/B imleçleri: görünümü durdurur, iki zamandaki değerleri ve farkı gösterir")
        self.btn_cursor.toggled.connect(self._on_cursor_toggled)
        self.btn_table = self._tool_button("sliders", "Sinyal Tablosu")
        self.btn_table.setCheckable(True)
        self.btn_table.setChecked(True)
        self.btn_table.setToolTip("Sinyal / renk / değer tablosunu göster-gizle (gizleyince grafik alanı genişler)")
        self.btn_table.toggled.connect(self._on_table_toggled)
        self.btn_freeze = self._tool_button("fit", "Dondur")
        self.btn_freeze.setCheckable(True)
        self.btn_freeze.setToolTip("TÜM grafikleri dondurur: görüntü donar, veri alımı arka planda SÜRER. "
                                   "Tek sinyali dondurmak için tablodaki 'Dondur' kutusu.")
        self.btn_freeze.toggled.connect(self.freeze_all)
        self.btn_yfree = self._tool_button("zoom_in", "Dikey Serbest")
        self.btn_yfree.setCheckable(True)
        self.btn_yfree.setToolTip("Dikey kaydırma ve yakınlaştırma (otomatik ölçek kapanır). Fare tekerleği: yakınlaştır; "
                                  "sürükle: kaydır. Veri değişmez.")
        self.btn_yfree.toggled.connect(self._set_y_free)
        self.btn_range = self._tool_button("fit", "A–B Aralığı")
        self.btn_range.setToolTip("Görünümü A–B imleçleri arasına yakınlaştırır (imleçler açıkken)")
        self.btn_range.clicked.connect(self.zoom_to_cursors)
        self.btn_layout = self._tool_button("download", "Yerleşim")
        self.btn_layout.setToolTip("Sinyal sırası, renk, görünürlük, ofset, şerit modu ve pencereyi kaydet / yükle")
        lmenu = QMenu(self.btn_layout)
        lmenu.addAction("Yerleşimi kaydet…", self._save_layout_dialog)
        lmenu.addAction("Yerleşimi yükle…", self._load_layout_dialog)
        self.btn_layout.setMenu(lmenu)
        self.btn_pick = self._tool_button("sliders", "Sinyaller")
        self.btn_pick.setToolTip("Grafikte çizilecek sinyalleri seç")
        self.btn_pick.clicked.connect(self.pick_requested.emit)
        self.btn_compare = self._tool_button("compare", "Karşılaştır")
        self.btn_compare.setToolTip("Karşılaştır: iki sinyalin farkını (A − B) ayrı bir eğri olarak çizer")
        self.btn_compare.clicked.connect(self._on_compare)
        self.btn_export = self._tool_button("download", "Dışa aktar")
        self.btn_export.setToolTip("Dışa aktar: CSV / MAT / MDF")
        menu = QMenu(self.btn_export)
        menu.addAction("CSV (.csv)", lambda: self.export("csv"))
        menu.addAction("MAT (.mat)", lambda: self.export("mat"))
        menu.addAction("MDF (.mf4)", lambda: self.export("mdf"))
        self.btn_export.setMenu(menu)
        self.btn_detach = self._tool_button("detach", "Ayır")
        self.btn_detach.setToolTip("Trend grafiğini ayrı pencerede aç (ör. ikinci monitör)")
        self.btn_detach.clicked.connect(lambda: self.detacher.detach())
        from app.ui.detach import PanelDetacher
        self.detacher = PanelDetacher(self, "Trend", self.btn_detach)
        # İkinci satır: araç düğmeleri (tek satıra sığmayınca metinler iç içe giriyordu)
        tools = QHBoxLayout()
        tools.setSpacing(4)
        tools.addStretch(1)
        for w in (self.btn_pick, self.btn_zoom_in, self.btn_zoom_out, self.btn_live, self.btn_cursor,
                  self.btn_compare, self.btn_export, self.btn_detach):
            tools.addWidget(w)
        # Üçüncü satır: analiz araçları (tek satıra sığmayınca panelin asgari genişliği şişiyordu)
        tools2 = QHBoxLayout()
        tools2.setSpacing(4)
        tools2.addStretch(1)
        for w in (self.btn_table, self.btn_freeze, self.btn_yfree, self.btn_range, self.btn_layout):
            tools2.addWidget(w)
        root.addLayout(head)
        root.addLayout(tools)
        root.addLayout(tools2)

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
        self.strips = pg.GraphicsLayoutWidget()
        self.strips.setBackground(PLOT_BG)
        self.strips.setMinimumHeight(110)
        host = QWidget()
        self._host_layout = QStackedLayout(host)
        self._host_layout.setContentsMargins(0, 0, 0, 0)
        self._host_layout.addWidget(self.strips)       # 0: şerit modu
        self._host_layout.addWidget(self.plot)         # 1: tek grafik (çok eksenli)
        self.signal_table = sigtab.SignalTable()
        self.signal_table.setMinimumWidth(180)
        self.signal_table.order_changed.connect(self._on_table_order)
        self.signal_table.visibility_changed.connect(self._on_table_visibility)
        self.signal_table.freeze_changed.connect(self._on_table_freeze)
        self.signal_table.color_changed.connect(self._on_table_color)
        self.signal_table.offset_changed.connect(self._on_table_offset)
        self.signal_table.scale_requested.connect(self._ask_scale)
        self.signal_table.own_strip_changed.connect(lambda k, _on: self._toggle_own_strip(k))
        self.signal_table.group_changed.connect(self._on_table_group)
        self.signal_table.remove_requested.connect(self._on_table_remove)
        self.body_split = QSplitter(Qt.Horizontal)
        self.body_split.setChildrenCollapsible(True)
        self.body_split.addWidget(host)
        self.body_split.addWidget(self.signal_table)
        self.body_split.setStretchFactor(0, 4)
        self.body_split.setStretchFactor(1, 1)
        self.body_split.setSizes([700, 300])
        root.addWidget(self.body_split, 1)

        # imleç çizgileri
        self._cur_a = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(theme.INK, width=1.4),
                                      label="A", labelOpts={"position": 0.06, "color": theme.INK})
        self._cur_b = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen(theme.MUTED, width=1.2, style=Qt.DashLine),
                                      label="B", labelOpts={"position": 0.06, "color": theme.MUTED})
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

    def _tool_button(self, icon_name: str, text: str) -> QPushButton:
        """Simge + kısa etiketli araç çubuğu düğmesi (yalnızca simge yerine okunur etiket)."""
        b = QPushButton(text)
        b.setProperty("compact", True)
        b.setIcon(self._qicon(icon_name, DK_MUT))
        b.setCursor(Qt.PointingHandCursor)
        b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        return b

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
            if s.get("source") is not None:
                ser.source = s["source"]
        for i, key in enumerate(new_order):
            self._series[key].color = self._color_override.get(key) or PALETTE[i % len(PALETTE)]
        derived = [k for k in self._order if k.startswith("d:") and k in self._series]
        self._order = new_order + [k for k in derived if k not in new_order]
        self._rebuild()

    def append(self, key: str, value, t: float | None = None):
        ser = self._series.get(key)
        if ser is None or not isinstance(value, (int, float)) or not math.isfinite(value):
            return                                  # NaN / ±inf grafiğe ve dışa aktarıma taşınmaz
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
                log.debug("ek eksen görünümü kaldırılamadı", exc_info=True)
        for ax in self._extra_axes:
            try:
                self.pi.layout.removeItem(ax)
                ax.setParentItem(None)
                self.pi.scene().removeItem(ax)
            except Exception:
                log.debug("ek eksen kaldırılamadı", exc_info=True)
        self._extra_vbs, self._extra_axes = [], []
        self.pi.hideAxis("right")

    def _unit_groups(self) -> list:
        """Birim grupları (sıra korunur): aynı birimdeki sinyaller aynı eksen / şerit."""
        groups: list = []
        for key in self._order:
            ser = self._series.get(key)
            if ser is None:
                continue
            for g in groups:
                if g["unit"] == ser.unit and not ser.own_strip and not g.get("own"):
                    g["series"].append(ser)
                    break
            else:
                groups.append({"unit": ser.unit, "series": [ser], "own": ser.own_strip})
        return groups

    def _xvb(self):
        """Zaman eksenini yöneten ViewBox: şerit modunda ilk şerit, değilse tek grafik."""
        return self._strips[0].vb if self._strip_mode and self._strips else self.vb

    def _event_targets(self) -> list:
        return [p.vb for p in self._strips] if self._strip_mode and self._strips else [self.vb]

    def _rebuild(self):
        # eski eğriler
        for ser in self._series.values():
            if ser.curve is not None:
                try:
                    ser.curve.getViewBox().removeItem(ser.curve)
                except Exception:
                    log.debug("eğri kaldırılamadı", exc_info=True)
                ser.curve = None
        self._remove_extra()
        for it in self._event_items:                      # olay çizgileri hedef ViewBox'lara göre yeniden çizilir
            try:
                it[0].removeItem(it[1])
            except Exception:
                log.debug("olay işareti kaldırılamadı", exc_info=True)
        self._event_items = []
        self._host_layout.setCurrentIndex(0 if self._strip_mode else 1)
        self.readout.setParent(self.strips if self._strip_mode else self.plot)
        self.readout.move(78, 8)
        self.readout.setVisible(self.btn_cursor.isChecked() and not self._strip_mode)
        if self._strip_mode:
            self._rebuild_strips()
        else:
            self._strips, self._strip_lines, self._strip_titles, self._strip_texts = [], [], {}, []
            self.strips.clear()
            self._rebuild_overlay()
        self._rebuild_legend()
        self._draw_events()
        self._sync_table()
        self._apply_y_free()
        self._dirty = True

    def _rebuild_strips(self):
        """Her birim grubu kendi şeridinde (kendi Y ekseni); hepsi ortak zaman çizgisini paylaşır."""
        self.strips.clear()
        self._strips, self._strip_lines, self._strip_titles, self._strip_texts = [], [], {}, []
        groups = self._unit_groups()
        n = max(len(groups), 1)
        cursors_on = self.btn_cursor.isChecked()
        for gi in range(n):
            g = groups[gi] if gi < len(groups) else None
            last = gi == n - 1
            axes = {"bottom": _RelAxis(self, orientation="bottom")} if last else {}
            plot = self.strips.addPlot(row=gi, col=0, axisItems=axes)
            plot.showGrid(x=True, y=True, alpha=0.18)
            plot.setMenuEnabled(False)
            plot.hideButtons()
            if not last:
                plot.hideAxis("bottom")
            for ax in ("left", "bottom"):
                if ax == "bottom" and not last:
                    continue
                plot.getAxis(ax).setTextPen(pg.mkPen(DK_MUT))
                plot.getAxis(ax).setPen(pg.mkPen(DK_LINE2))
            left = plot.getAxis("left")
            left.setWidth(66)                              # şeritlerin plot alanları hizalı kalsın
            vb = plot.vb
            vb.setMouseEnabled(x=True, y=False)
            vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=True)
            vb.setAutoVisible(y=True)
            if self._strips:
                vb.setXLink(self._strips[0].vb)
            vb.sigRangeChangedManually.connect(self._on_manual_range)
            if g is not None:
                first = g["series"][0]
                left.setLabel(f"[{g['unit']}]" if g["unit"] else "",
                              color=first.color if len(g["series"]) == 1 else DK_MUT)
                for ser in g["series"]:
                    ser.curve = pg.PlotDataItem(pen=pg.mkPen(ser.color, width=2), name=ser.label)
                    ser.curve.setClipToView(True)
                    ser.curve.setDownsampling(auto=True, method="peak")
                    vb.addItem(ser.curve)
                    ser.vb = vb
                g["vb"] = vb
                g["plot"] = plot
            lines = []
            for which, cur in (("a", self._cur_a), ("b", self._cur_b)):
                ln = pg.InfiniteLine(angle=90, movable=True, pos=cur.value(), pen=cur.pen,
                                     label=which.upper(), labelOpts={"position": 0.06, "color": cur.pen.color()})
                ln.setZValue(50)
                ln.sigPositionChanged.connect(lambda l, w=which: self._on_strip_line_moved(w, l))
                vb.addItem(ln, ignoreBounds=True)
                ln.setVisible(cursors_on)
                lines.append(ln)
            self._strip_lines.append(tuple(lines))
            # ad + o anki değer: şeridin SOL ÜST köşesine (yer ayırmadan, grafiğin üstüne) yazılır
            txt = pg.TextItem(html="", anchor=(0, 0))
            txt.setParentItem(vb)
            txt.setPos(8, 2)
            txt.setZValue(60)
            self._strip_texts.append(txt)
            self._strips.append(plot)
        self._groups = groups
        self._strip_titles = {}
        self._update_strip_titles()

    def _rebuild_overlay(self):
        groups = self._unit_groups()
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
            if ax is not left_axis:
                ax.setWidth(62)       # her sağ eksen kendi sütununda: başlık + etiketler çakışmaz
            g["vb"] = vb
            for ser in g["series"]:
                ser.curve = pg.PlotDataItem(pen=pg.mkPen(ser.color, width=2), name=ser.label)
                ser.curve.setClipToView(True)
                ser.curve.setDownsampling(auto=True, method="peak")
                vb.addItem(ser.curve)
                ser.vb = vb
        self._groups = groups
        self._sync_geometry()


    def _set_strip_mode(self, on: bool):
        if bool(on) == self._strip_mode:
            return
        lo, hi = self._xvb().viewRange()[0]
        self._strip_mode = bool(on)
        self._rebuild()
        self._apply_x(lo, hi)

    def _update_strip_titles(self):
        """Her şeridin üstünde sinyal adı + O ANKİ değer (yalnızca metin değişince yazılır)."""
        if not self._strip_mode:
            return
        for gi, g in enumerate(self._groups):
            if gi >= len(self._strips):
                break
            parts = []
            for ser in g["series"]:
                u = f" {ser.unit}" if ser.unit else ""
                if self._cursor_vals is not None and self.btn_cursor.isChecked():
                    a, b = self._cursor_vals[0].get(ser.key), self._cursor_vals[1].get(ser.key)
                    fa = "—" if a is None else format_value(a)
                    fb = "—" if b is None else format_value(b)
                    d = "—" if a is None or b is None else f"{'+' if a - b >= 0 else '−'}{format_value(abs(a - b))}"
                    parts.append(f'<span style="color:{ser.color}">●</span> {ser.label}&nbsp; A <b style="color:{DK_INK}">{fa}</b>'
                                 f'&nbsp; B <b style="color:{DK_INK}">{fb}</b>&nbsp; Δ <b style="color:{DK_INK}">{d}</b>{u}')
                else:
                    vv = ser.view_arrays()[1]
                    cur = format_value(float(vv[-1])) if len(vv) else "—"
                    parts.append(f'<span style="color:{ser.color}">●</span> {ser.label} '
                                 f'<b style="color:{DK_INK}">{cur}</b>{u}')
            text = "&nbsp;&nbsp;&nbsp;".join(parts)
            if self._strip_titles.get(gi) != text and gi < len(self._strip_texts):
                self._strip_titles[gi] = text
                self._strip_texts[gi].setHtml(f'<span style="font-size:10pt; color:{DK_MUT}">{text}</span>')

    def _sync_geometry(self):
        for vb in self._extra_vbs:
            vb.setGeometry(self.vb.sceneBoundingRect())
            vb.linkedViewChanged(self.vb, vb.XAxis)

    def _rebuild_legend(self):
        while self.legend_row.count() > 3:      # son 3: stretch + test etiketi + imleç özeti
            it = self.legend_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)       # deleteLater gecikirse eski etiket ekranda asılı kalmasın
                w.deleteLater()
        if self._strip_mode:
            return                      # şerit modunda her şeridin içinde ad + değer yazar; ayrıca gösterge satırı yok
        pos = 0
        for key in self._order:
            ser = self._series.get(key)
            if ser is None:
                continue
            u = f" [{ser.unit}]" if ser.unit else ""
            lab = QLabel(f'<span style="color:{ser.color}; font-size:14px;">●</span>&nbsp;{ser.label}{u}')
            lab.setTextFormat(Qt.RichText)
            lab.setObjectName("legendItem")
            lab.setMinimumWidth(0)      # uzun gösterge paneli genişletmesin (asgari genişliği şişirmesin)
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
        lo, hi = self._xvb().viewRange()[0]
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
            self._xvb().setXRange(lo, hi, padding=0)
        finally:
            self._applying_range = False

    def _on_manual_range(self, *_):
        if self._applying_range:
            return
        # kullanıcı fareyle kaydırdı/yakınlaştırdı -> canlı takibi bırak
        if self._live:
            self._live = False
            self._frozen_ref = time.time()
        lo, hi = self._xvb().viewRange()[0]
        self._window = max(5.0, hi - lo)

    # ------------------------------------------------------------ periyodik çizim
    def _tick(self):
        now = time.time()
        if self._live:
            self._apply_x(now - self._window, now)
        if self._dirty or self._live:
            if self._dirty:
                self._recompute_diffs()
            lo, hi = self._xvb().viewRange()[0]
            margin = (hi - lo) * 0.05
            for ser in self._series.values():
                if ser.curve is None:
                    continue
                ser.curve.setVisible(ser.visible)
                t, v = ser.view_arrays()
                if len(t) and ser.visible:
                    i0 = int(np.searchsorted(t, lo - margin))
                    seg_t, seg_v = t[max(0, i0 - 1):], v[max(0, i0 - 1):]
                    if ser.offset or ser.scale != 1.0:
                        seg_v = apply_view_transform(seg_v, ser.offset, ser.scale)   # yalnızca görünüm; veri aynı
                    ser.curve.setData(seg_t, seg_v)
                else:
                    ser.curve.setData([], [])
            self._dirty = False
            self._update_strip_titles()
            self._update_table_values()
        if self._test_start is not None:
            el = int(now - self._test_start)
            self.test_label.setText(f"⚑ Test süresi {el // 60:02d}:{el % 60:02d}")
        if self.btn_cursor.isChecked():
            self._update_cursor_readout()
        self._autosave_layout()

    # ------------------------------------------------------------ imleçler
    def _on_cursor_toggled(self, on: bool):
        for ln in (self._cur_a, self._cur_b):
            ln.setVisible(on)
        for pair in self._strip_lines:
            for ln in pair:
                ln.setVisible(on)
        self.readout.setVisible(on and not self._strip_mode and not self.signal_table.isVisibleTo(self))
        self.signal_table.set_cursor_columns(on)
        self._cursor_vals = None
        self._strip_titles = {}
        self._update_strip_titles()
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

    def _on_strip_line_moved(self, which: str, ln):
        """Bir şeritteki A/B çizgisi sürüklendi: asıl imleç değerini günceller, diğer şeritler eşlenir."""
        (self._cur_a if which == "a" else self._cur_b).setPos(ln.value())

    def _sync_strip_lines(self):
        for a, b in self._strip_lines:
            for ln, cur in ((a, self._cur_a), (b, self._cur_b)):
                if abs(ln.value() - cur.value()) > 1e-9:
                    ln.blockSignals(True)
                    ln.setPos(cur.value())
                    ln.blockSignals(False)

    def values_at(self, t: float) -> dict:
        out = {}
        for key in self._order:
            ser = self._series.get(key)
            if ser is None or not ser.t:
                continue
            ta, va = ser.view_arrays()
            if not len(ta):
                continue
            val, _why = sample_at(ta, va, t, MAX_GAP_S)    # boşluk / kapsam dışı: değer uydurulmaz (veri yok)
            if val is not None:
                out[key] = val
        return out

    def _update_cursor_readout(self, *_):
        if not self.btn_cursor.isChecked():
            return
        self._sync_strip_lines()
        ta, tb = float(self._cur_a.value()), float(self._cur_b.value())
        ref = self.ref_time()
        va, vb = self.values_at(ta), self.values_at(tb)
        self._fill_cursor_table(ta, tb)
        if self._strip_mode:
            self._cursor_vals = (va, vb)
            self._update_strip_titles()
            self.cursor_summary.setText(
                f"İmleç A: {ta - ref:.1f} sn  ·  B: {tb - ref:.1f} sn  ·  Δt {abs(ta - tb):.1f} sn")
            return
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

    # ------------------------------------------------------------ sinyal tablosu / freeze / görünüm durumu
    def _table_rows(self) -> list:
        rows = []
        for key in self._order:
            ser = self._series.get(key)
            if ser is None:
                continue
            rows.append({"key": key, "label": ser.label, "unit": ser.unit, "color": ser.color, "visible": ser.visible,
                         "frozen": ser.frozen_at is not None, "source": ser.source, "offset": ser.offset,
                         "group": ser.group, "own_strip": ser.own_strip})
        return rows

    def _sync_table(self):
        self.signal_table.sync(self._table_rows())
        self.signal_table.set_cursor_columns(self.btn_cursor.isChecked())

    def _update_table_values(self):
        """Tablodaki anlık değer (imleç kapalıyken) ve imleç sütunları; yalnızca metin değişince yazılır."""
        if self.btn_cursor.isChecked():
            return                                    # imleç açıkken değerleri _update_cursor_readout yazar
        for key in self._order:
            ser = self._series.get(key)
            if ser is None:
                continue
            vv = ser.view_arrays()[1]
            self.signal_table.set_value(key, sigtab.C_VALUE, format_value(float(vv[-1])) if len(vv) else "—")

    def _on_table_toggled(self, on: bool):
        self.signal_table.setVisible(on)
        self._mark_layout_dirty()

    def _on_table_order(self, keys: list):
        rest = [k for k in self._order if k not in keys]
        self._order = [k for k in keys if k in self._series] + rest
        self._rebuild()
        self._mark_layout_dirty()

    def _on_table_visibility(self, key: str, vis: bool):
        ser = self._series.get(key)
        if ser is not None:
            ser.visible = vis
            self._dirty = True
            self._mark_layout_dirty()

    def _on_table_freeze(self, key: str, on: bool):
        ser = self._series.get(key)
        if ser is not None:
            ser.frozen_at = time.time() if on else None
            self._dirty = True

    def load_static(self, specs: list, events: list | None = None):
        """Kayıtlı oturum analizi: ``specs`` = [{'key','label','unit','source','t' (epoch dizisi),'v'}]. Canlı akış kapalı,
        görünüm tüm kayıt aralığına ayarlanır; imleç/şerit/ofset/istatistik araçları canlı trendle AYNIDIR.
        Bellekteki canlı geçmiş (MAX_HISTORY_S) ile diske kayıtlı veri ayrıdır: burada kırpma uygulanmaz."""
        self.clear()
        self._events = []
        self.set_series([{k: sp[k] for k in ("key", "label", "unit", "source") if k in sp} for sp in specs])
        t_lo, t_hi = math.inf, -math.inf
        for sp in specs:
            ser = self._series[sp["key"]]
            t, v = np.asarray(sp["t"], float), np.asarray(sp["v"], float)
            ser.t, ser.v = t.tolist(), v.tolist()
            if len(t):
                t_lo, t_hi = min(t_lo, float(t[0])), max(t_hi, float(t[-1]))
        for t, label, color in (events or []):
            self._events.append((t, label, color))
        self._live = False
        self._static = True
        if math.isfinite(t_lo):
            self._frozen_ref = t_hi
            self._window = max(5.0, t_hi - t_lo)
            self._apply_x(t_lo - 0.02 * (t_hi - t_lo), t_hi + 0.02 * (t_hi - t_lo))
        self._draw_events()
        self._dirty = True
        self._tick()

    def freeze_all(self, on: bool):
        """Tüm sinyallerin GÖRÜNTÜSÜNÜ dondurur; veri alımı (append) sürer. Kalkınca canlı veriye dönülür."""
        now = time.time()
        for ser in self._series.values():
            ser.frozen_at = now if on else None
        if self.btn_freeze.isChecked() != bool(on):
            self.btn_freeze.blockSignals(True)
            self.btn_freeze.setChecked(bool(on))
            self.btn_freeze.blockSignals(False)
        if on:
            self._live = False                         # donmuş görünüm kaydırılabilir/yakınlaştırılabilir
            self._frozen_ref = now
        else:
            self.go_live()
        self._sync_table()
        self._dirty = True

    def is_frozen(self, key: str | None = None) -> bool:
        if key is not None:
            ser = self._series.get(key)
            return ser is not None and ser.frozen_at is not None
        return any(s.frozen_at is not None for s in self._series.values())

    def _on_table_color(self, key: str, color: str):
        ser = self._series.get(key)
        if ser is not None:
            ser.color = color
            self._color_override[key] = color
            self._rebuild()
            self._mark_layout_dirty()

    def _on_table_offset(self, key: str, offset: float):
        ser = self._series.get(key)
        if ser is not None:
            ser.offset = float(offset)
            self._dirty = True
            self._sync_table()
            self._mark_layout_dirty()

    def _ask_scale(self, key: str):
        ser = self._series.get(key)
        if ser is None:
            return
        val, ok = QInputDialog.getDouble(self.window(), "Dikey ölçek", "Eğriyi dikeyde çarp (yalnızca görünüm; veri değişmez):",
                                         ser.scale, -1e6, 1e6, 6)
        if ok and val != 0:
            self.set_signal_scale(key, val)

    def set_signal_scale(self, key: str, scale: float):
        ser = self._series.get(key)
        if ser is not None and math.isfinite(scale) and scale != 0:
            ser.scale = float(scale)
            self._dirty = True
            self._mark_layout_dirty()

    def set_signal_offset(self, key: str, offset: float):
        if math.isfinite(offset):
            self._on_table_offset(key, offset)

    def _toggle_own_strip(self, key: str):
        ser = self._series.get(key)
        if ser is not None:
            ser.own_strip = not ser.own_strip
            self._rebuild()
            self._mark_layout_dirty()

    def _on_table_group(self, key: str, group: str):
        ser = self._series.get(key)
        if ser is not None:
            ser.group = group
            self._mark_layout_dirty()

    def _on_table_remove(self, key: str):
        if key in self._series and key in self._order:
            self._order.remove(key)
            self._series[key].visible = False
            self._rebuild()

    def _set_y_free(self, on: bool):
        self._y_free = bool(on)
        self._apply_y_free()

    def _apply_y_free(self):
        """Dikey serbest mod: fare ile dikey kaydırma/yakınlaştırma açılır, otomatik ölçek kapanır; kapalıyken
        her grafik bağımsız otomatik ölçeklenir."""
        vbs = [p.vb for p in self._strips] if self._strip_mode and self._strips else [self.vb]
        for vb in vbs:
            vb.setMouseEnabled(x=True, y=self._y_free)
            vb.enableAutoRange(axis=pg.ViewBox.YAxis, enable=not self._y_free)
            if not self._y_free:
                vb.setAutoVisible(y=True)

    def zoom_to_cursors(self):
        """A–B imleçleri arasına yakınlaştır (aralık seçme)."""
        if not self.btn_cursor.isChecked():
            self.btn_cursor.setChecked(True)
            return
        ta, tb = sorted((float(self._cur_a.value()), float(self._cur_b.value())))
        if tb - ta < 1e-6:
            return
        self._live = False
        self._frozen_ref = self.ref_time() if self._live else self._frozen_ref
        self._apply_x(ta, tb)
        self._window = tb - ta
        self._dirty = True

    # ---- yerleşim (layout) -----------------------------------------------------------------
    def current_layout(self) -> TrendLayout:
        lay = TrendLayout(order=list(self._order), strip_mode=self._strip_mode, window_s=self._window,
                          table_visible=self.btn_table.isChecked())
        for key in self._order:
            ser = self._series.get(key)
            if ser is None or key.startswith("d:"):
                continue
            lay.views[key] = SignalView(key, ser.color, ser.visible, offset=ser.offset, scale=ser.scale,
                                        group=ser.group)
        lay.order = [k for k in lay.order if k in lay.views]
        return lay

    def apply_layout(self, lay: TrendLayout):
        """Yerleşimi uygular. Yüklü olmayan sinyaller yok sayılır; sıra yalnızca mevcut sinyallere uygulanır."""
        for key, sv in lay.views.items():
            if sv.color:
                self._color_override[key] = sv.color
            ser = self._series.get(key)
            if ser is not None:
                ser.visible, ser.offset, ser.scale, ser.group = sv.visible, sv.offset, sv.scale, sv.group
                if sv.color:
                    ser.color = sv.color
        known = [k for k in lay.order if k in self._series and k in self._order]
        self._order = known + [k for k in self._order if k not in known]
        self._window = max(5.0, min(MAX_HISTORY_S, lay.window_s))
        for secs, b in self._win_buttons:
            b.setChecked(abs(secs - self._window) < 1e-6)
        self.btn_table.setChecked(lay.table_visible)
        if bool(lay.strip_mode) != self._strip_mode:
            self.btn_strips.setChecked(bool(lay.strip_mode))      # toggled -> _set_strip_mode -> _rebuild
        else:
            self._rebuild()

    def save_layout(self, path: str) -> bool:
        import json
        from app.persist import atomic_write_json
        return atomic_write_json(path, json.loads(self.current_layout().to_json()))

    def load_layout(self, path: str) -> bool:
        try:
            with open(path, encoding="utf-8") as f:
                lay = TrendLayout.from_json(f.read())
        except (OSError, ValueError) as exc:
            log.warning("Trend yerleşimi yüklenemedi: %s", exc)
            return False
        self.apply_layout(lay)
        return True

    def _mark_layout_dirty(self):
        if self.layout_path:
            self._layout_dirty = True

    def _autosave_layout(self):
        if self._layout_dirty and self.layout_path:
            self._layout_dirty = False
            self.save_layout(self.layout_path)

    def _save_layout_dialog(self):
        path, _ = QFileDialog.getSaveFileName(self.window(), "Trend yerleşimini kaydet", "trend_yerlesim.json",
                                              "JSON (*.json)")
        if path and not self.save_layout(path):
            QMessageBox.critical(self.window(), "Yerleşim", "Dosya yazılamadı.")

    def _load_layout_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self.window(), "Trend yerleşimini yükle", "", "JSON (*.json)")
        if path and not self.load_layout(path):
            QMessageBox.warning(self.window(), "Yerleşim", "Yerleşim dosyası okunamadı veya geçersiz.")

    def _fill_cursor_table(self, ta: float, tb: float):
        """Main (A) ve Difference (B) imleç değerleri: gerçek zaman damgalarına göre; boşlukta 'veri yok'.
        ΔY = B − A, ΔY/Δt işaretli; min/max/ort. A–B aralığı için."""
        data = {k: s.view_arrays() for k, s in self._series.items() if k in self._order}
        for row in cursor_rows(data, [k for k in self._order if k in data], ta, tb, MAX_GAP_S):
            t, v = data[row.key]
            st = range_stats(t, v, ta, tb)
            tab = self.signal_table
            tab.set_value(row.key, sigtab.C_VALUE, sigtab.NO_DATA if row.a is None else sigtab.fmt(row.a))
            tab.set_value(row.key, sigtab.C_B, sigtab.NO_DATA if row.b is None else sigtab.fmt(row.b))
            tab.set_value(row.key, sigtab.C_DY, "—" if row.dy is None else f"{row.dy:+.5g}")
            rate = row.dydt(ta, tb)
            tab.set_value(row.key, sigtab.C_DYDT, "—" if rate is None else f"{rate:+.5g}")
            tab.set_value(row.key, sigtab.C_MIN, sigtab.fmt(st["min"]))
            tab.set_value(row.key, sigtab.C_MAX, sigtab.fmt(st["max"]))
            tab.set_value(row.key, sigtab.C_MEAN, sigtab.fmt(st["mean"]))

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
        ser = _Series(key, f"{a} − {b}", sa.unit, theme.SURFACE)
        ser.t, ser.v = self._diff_data(ka, kb)
        self._series[key] = ser
        if key not in self._order:
            self._order.append(key)
        self._rebuild()

    def _diff_data(self, ka: str, kb: str) -> tuple:
        """A − B: iki sinyalin ortak zaman aralığında, A'nın örnek anlarında hesaplanır."""
        sa, sb = self._series.get(ka), self._series.get(kb)
        if sa is None or sb is None:
            return [], []
        ta, va = sa.arrays()
        tb, vb = sb.arrays()
        if not (len(ta) and len(tb)):
            return [], []
        lo, hi = max(ta[0], tb[0]), min(ta[-1], tb[-1])
        grid = ta[(ta >= lo) & (ta <= hi)]
        return list(grid), list(np.interp(grid, ta, va) - np.interp(grid, tb, vb))

    def _recompute_diffs(self):
        """Fark (A−B) eğrileri canlıdır: kaynak sinyallere yeni örnek gelince yeniden hesaplanır."""
        for key in [k for k in self._order if k.startswith("d:")]:
            ser = self._series.get(key)
            if ser is None or "|" not in key:
                continue
            ka, kb = key[2:].split("|", 1)
            ser.t, ser.v = self._diff_data(ka, kb)

    # ------------------------------------------------------------ test işaretleri
    def start_test(self):
        now = time.time()
        self._test_start = now
        self.add_event("Test Başlangıcı", now, theme.OK)
        self.btn_test_start.setEnabled(False)
        self.btn_test_end.setEnabled(True)
        self.test_label.setVisible(True)
        self.test_started.emit(now)

    def end_test(self):
        if self._test_start is None:
            return
        now = time.time()
        dur = now - self._test_start
        self.add_event("Test Bitişi", now, theme.DANGER)
        self._test_start = None
        self.btn_test_start.setEnabled(True)
        self.btn_test_end.setEnabled(False)
        self.test_label.setText(f"⚑ Son test: {int(dur) // 60:02d}:{int(dur) % 60:02d}")
        self.test_ended.emit(now, dur)

    def add_event(self, label: str, t: float, color: str):
        self._events.append((t, label, color))
        self._draw_events()

    def _draw_events(self):
        for vb, it in self._event_items:
            try:
                vb.removeItem(it)
            except Exception:
                log.debug("olay işareti kaldırılamadı", exc_info=True)
        self._event_items = []
        for t, label, color in self._events:
            stamp = time.strftime("%H:%M:%S", time.localtime(t))
            for n, vb in enumerate(self._event_targets()):
                ln = pg.InfiniteLine(pos=t, angle=90, movable=False,
                                     pen=pg.mkPen(color, width=1.4, style=Qt.DashLine),
                                     label=f"⚑ {label} {stamp}" if n == 0 else "",
                                     labelOpts={"position": 0.94, "color": color, "fill": (8, 18, 31, 200),
                                                "anchors": [(0, 0), (0, 0)]})
                ln.setZValue(40)
                vb.addItem(ln, ignoreBounds=True)
                self._event_items.append((vb, ln))

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

    def snapshot(self):
        """PDF raporu için (veri, olaylar) kopyası; sonradan değişmez."""
        data, events = self._export_data()
        return {k: (t.copy(), v.copy(), u) for k, (t, v, u) in data.items()}, events

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
    for sg in sigs:                       # her sinyal kendi zaman damgalarıyla ayrı grupta (ortak zaman varsayılmaz)
        mdf.append(sg)
    if events:
        mdf.append([Signal(samples=np.arange(1, len(events) + 1, dtype=float),
                           timestamps=np.asarray([e[0] for e in events], float),
                           name="Test_Olaylari", comment="; ".join(f"{i + 1}={e[1]}" for i, e in enumerate(events)))])
    mdf.save(path, overwrite=True)
