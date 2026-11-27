"""Trend analizi için saf mantık (Qt yok): imleç değerleri, fark (ΔY, ΔY/Δt), aralık istatistiği, freeze ve
sinyal görünüm durumu, yerleşim (layout) serileştirme.

Veri doğruluğu ilkeleri (docs/GOREV.md 3.3, 8): değerler sinyalin GERÇEK zaman damgalarına göre hesaplanır; iki
örnek arası ``max_gap``'ten uzunsa veya zaman sinyalin kapsamı dışındaysa değer UYDURULMAZ → ``None`` ("veri yok").
Ofset/ölçek yalnızca ekran dönüşümüdür; orijinal veri değişmez.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

DEFAULT_MAX_GAP_S = 5.0
LAYOUT_VERSION = 1

OK, OUTSIDE, GAP, EMPTY = "ok", "outside", "gap", "empty"


def sample_at(t, v, at: float, max_gap: float = DEFAULT_MAX_GAP_S) -> tuple[float | None, str]:
    """(değer | None, neden). ``t`` artan zaman dizisi. Örnek üzerinde tam değer; iki örnek arasında doğrusal
    ara değer, ama yalnızca aralık ``max_gap``'ten kısaysa."""
    t = np.asarray(t, dtype=float)
    v = np.asarray(v, dtype=float)
    if t.size == 0:
        return None, EMPTY
    if not math.isfinite(at) or at < t[0] or at > t[-1]:
        return None, OUTSIDE
    j = int(np.searchsorted(t, at))
    if j < t.size and t[j] == at:
        val = float(v[j])
        return (val, OK) if math.isfinite(val) else (None, GAP)
    if j == 0:
        return None, OUTSIDE
    t0, t1, v0, v1 = t[j - 1], t[j], v[j - 1], v[j]
    if t1 - t0 > max_gap:
        return None, GAP
    if not (math.isfinite(v0) and math.isfinite(v1)):
        return None, GAP
    return float(v0 + (v1 - v0) * (at - t0) / (t1 - t0)), OK


@dataclass
class CursorRow:
    key: str
    a: float | None
    b: float | None
    a_reason: str = OK
    b_reason: str = OK

    @property
    def dy(self) -> float | None:
        return None if self.a is None or self.b is None else self.b - self.a

    def dydt(self, ta: float, tb: float) -> float | None:
        dt = tb - ta
        if self.dy is None or abs(dt) < 1e-12:
            return None
        return self.dy / dt


def cursor_rows(series: dict, keys: list, ta: float, tb: float,
                max_gap: float = DEFAULT_MAX_GAP_S) -> list[CursorRow]:
    """``series``: key -> (t, v) dizileri. Fark ΔY = B − A, ΔY/Δt = ΔY / (tB − tA) (işaretli)."""
    rows = []
    for k in keys:
        if k not in series:
            continue
        t, v = series[k]
        a, ra = sample_at(t, v, ta, max_gap)
        b, rb = sample_at(t, v, tb, max_gap)
        rows.append(CursorRow(k, a, b, ra, rb))
    return rows


def range_stats(t, v, lo: float, hi: float) -> dict:
    """[lo, hi] aralığında örnek sayısı, min, max, ortalama (NaN/Inf hariç). Boşsa değerler None."""
    t = np.asarray(t, dtype=float)
    v = np.asarray(v, dtype=float)
    if lo > hi:
        lo, hi = hi, lo
    if t.size == 0:
        return {"count": 0, "min": None, "max": None, "mean": None}
    i0, i1 = int(np.searchsorted(t, lo, "left")), int(np.searchsorted(t, hi, "right"))
    seg = v[i0:i1]
    seg = seg[np.isfinite(seg)]
    if seg.size == 0:
        return {"count": 0, "min": None, "max": None, "mean": None}
    return {"count": int(seg.size), "min": float(seg.min()), "max": float(seg.max()), "mean": float(seg.mean())}


def apply_view_transform(v, offset: float = 0.0, scale: float = 1.0):
    """Ekran dönüşümü: ``v * scale + offset``. Girdiyi DEĞİŞTİRMEZ (yeni dizi döner)."""
    return np.asarray(v, dtype=float) * float(scale) + float(offset)


def cut_at(t, v, until: float | None):
    """Freeze: ``until`` anından sonraki örnekleri görüntüden çıkarır (veri alımı sürer; görünüm donar)."""
    t = np.asarray(t, dtype=float)
    v = np.asarray(v, dtype=float)
    if until is None:
        return t, v
    n = int(np.searchsorted(t, until, "right"))
    return t[:n], v[:n]


@dataclass
class SignalView:
    """Bir sinyalin görünüm durumu (veriden bağımsız)."""
    key: str
    color: str = ""
    visible: bool = True
    frozen_at: float | None = None       # None: canlı
    offset: float = 0.0
    scale: float = 1.0
    group: str = ""
    source: str = ""

    def to_dict(self) -> dict:
        d = {"key": self.key, "color": self.color, "visible": self.visible, "offset": self.offset,
             "scale": self.scale, "group": self.group}
        return d                          # freeze ve kaynak oturuma özgüdür; yerleşimle saklanmaz


@dataclass
class TrendLayout:
    order: list = field(default_factory=list)
    views: dict = field(default_factory=dict)       # key -> SignalView
    strip_mode: bool = True
    window_s: float = 60.0
    table_visible: bool = True

    def to_json(self) -> str:
        return json.dumps({
            "version": LAYOUT_VERSION, "order": self.order, "strip_mode": self.strip_mode,
            "window_s": self.window_s, "table_visible": self.table_visible,
            "views": [self.views[k].to_dict() for k in self.order if k in self.views],
        }, ensure_ascii=False, indent=1)

    @staticmethod
    def from_json(text: str) -> "TrendLayout":
        """Bozuk/eksik alanlara dayanıklı: geçersiz girdi ``ValueError``; bilinmeyen alanlar yok sayılır."""
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Yerleşim dosyası okunamadı: {exc}") from exc
        if not isinstance(raw, dict):
            raise ValueError("Yerleşim dosyası bir nesne değil")
        lay = TrendLayout()
        lay.strip_mode = bool(raw.get("strip_mode", True))
        w = raw.get("window_s", 60.0)
        lay.window_s = float(w) if isinstance(w, (int, float)) and math.isfinite(w) and w > 0 else 60.0
        lay.table_visible = bool(raw.get("table_visible", True))
        for item in raw.get("views", []) if isinstance(raw.get("views"), list) else []:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                continue
            off, sc = item.get("offset", 0.0), item.get("scale", 1.0)
            sv = SignalView(
                key=item["key"], color=str(item.get("color", "")), visible=bool(item.get("visible", True)),
                offset=float(off) if isinstance(off, (int, float)) and math.isfinite(off) else 0.0,
                scale=float(sc) if isinstance(sc, (int, float)) and math.isfinite(sc) and sc != 0 else 1.0,
                group=str(item.get("group", "")))
            lay.views[sv.key] = sv
            lay.order.append(sv.key)
        return lay
