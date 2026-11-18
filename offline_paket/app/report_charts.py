"""PDF test raporu için Canlı Trendler grafikleri (reportlab.graphics; Qt'siz, başsız çalışır).

Girdi, ``TrendPanel.snapshot()`` çıktısıdır: ``({etiket: (t_epoch, değer, birim)}, [(t_epoch, etiket, renk)])``.
Aynı birimdeki sinyaller tek grafikte toplanır (TrendPanel'deki gibi, normalize YOK); farklı birimler ayrı grafik olur.
"""
from __future__ import annotations

import numpy as np
from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors

from app.report import FONT_BOLD, FONT_REGULAR, register_fonts

MAX_POINTS = 2000          # grafik başına çizgi başına nokta sınırı (PDF boyutu için)
MAX_LINES = 6              # bir grafikte en fazla çizgi
CHART_W, CHART_H = 480, 200
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b"]


def decimate(t: np.ndarray, v: np.ndarray, limit: int = MAX_POINTS):
    """Çok noktalı diziyi, her dilimin min/maks değerini koruyarak ~limit noktaya indirir."""
    n = len(t)
    if n <= limit:
        return t, v
    bins = max(limit // 2, 1)
    edges = np.linspace(0, n, bins + 1, dtype=int)
    idx: list[int] = []
    for a, b in zip(edges[:-1], edges[1:]):
        if b <= a:
            continue
        seg = v[a:b]
        i_min, i_max = a + int(np.argmin(seg)), a + int(np.argmax(seg))
        idx.extend(sorted({i_min, i_max}))
    sel = np.asarray(idx, dtype=int)
    return t[sel], v[sel]


def _time_unit(span: float) -> tuple[float, str]:
    return (60.0, "dk") if span > 180 else (1.0, "sn")


def _chart(title: str, unit: str, lines: list, events: list, t0: float, t1: float) -> Drawing:
    register_fonts()
    span = max(t1 - t0, 1e-6)
    div, tu = _time_unit(span)
    d = Drawing(CHART_W, CHART_H + 36)
    d.add(String(0, CHART_H + 24, f"{title}" + (f"  [{unit}]" if unit else ""), fontName=FONT_BOLD,
                 fontSize=9))
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 40, 24, CHART_W - 60, CHART_H - 10
    lp.data = [[((float(t) - t0) / div, float(v)) for t, v in zip(ts, vs)] for _lab, ts, vs in lines]
    for i in range(len(lines)):
        lp.lines[i].strokeColor = colors.HexColor(PALETTE[i % len(PALETTE)])
        lp.lines[i].strokeWidth = 0.8
        lp.lines[i].symbol = None
    lp.xValueAxis.valueMin, lp.xValueAxis.valueMax = 0, span / div
    lp.xValueAxis.labels.fontSize = lp.yValueAxis.labels.fontSize = 7
    lp.xValueAxis.labels.fontName = lp.yValueAxis.labels.fontName = FONT_REGULAR
    lp.xValueAxis.visibleGrid = lp.yValueAxis.visibleGrid = True
    lp.xValueAxis.gridStrokeColor = lp.yValueAxis.gridStrokeColor = colors.lightgrey
    d.add(lp)
    d.add(String(lp.x + lp.width / 2, 8, f"Oturum başından geçen süre ({tu})", fontName=FONT_REGULAR, fontSize=7, textAnchor="middle"))
    for t, label, color in events:                          # test başlangıç/bitiş işaretleri
        if not (t0 <= t <= t1):
            continue
        x = lp.x + (t - t0) / span * lp.width
        ln = Line(x, lp.y, x, lp.y + lp.height, strokeColor=colors.HexColor(color) if str(color).startswith("#")
                  else colors.red, strokeWidth=0.8, strokeDashArray=[3, 2])
        d.add(ln)
        d.add(String(x + 2, lp.y + lp.height - 8, str(label), fontName=FONT_REGULAR, fontSize=6))
    lx = 40                                                  # gösterge
    for i, (lab, _t, _v) in enumerate(lines):
        d.add(Line(lx, CHART_H + 12, lx + 10, CHART_H + 12, strokeColor=colors.HexColor(PALETTE[i % len(PALETTE)]),
                   strokeWidth=1.5))
        d.add(String(lx + 13, CHART_H + 9, str(lab)[:28], fontName=FONT_REGULAR, fontSize=7))
        lx += 13 + 6 * min(len(str(lab)), 28) + 14
    return d


def build_trend_charts(data: dict, events: list, t0: float, t1: float) -> list:
    """Oturum aralığındaki (t0..t1, epoch) trend verisinden grafik listesi döner; veri yoksa boş liste."""
    if not data or t1 <= t0:
        return []
    by_unit: dict[str, list] = {}
    for label, (t, v, unit) in data.items():
        t = np.asarray(t, dtype=float)
        v = np.asarray(v, dtype=float)
        m = (t >= t0) & (t <= t1)
        if not m.any():
            continue
        ts, vs = decimate(t[m], v[m])
        by_unit.setdefault(unit or "", []).append((label, ts, vs))
    charts = []
    for unit, items in by_unit.items():
        for i in range(0, len(items), MAX_LINES):
            part = items[i:i + MAX_LINES]
            title = "Trend" if len(items) <= MAX_LINES else f"Trend ({i // MAX_LINES + 1})"
            charts.append(_chart(title, unit, part, events, t0, t1))
    return charts
