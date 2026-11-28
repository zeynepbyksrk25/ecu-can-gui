"""Worksheet şablonları (Qt'siz): hazır test / kalibrasyon dizilimleri ve kullanıcının kendi şablonları.

Bir şablon, worksheet pencere tanımlarının listesidir (``ModasWorkspace`` kaydıyla aynı biçim):
``{"kind": "value" | "table" | "scope", "name": ..., "geom": [x, y, w, h], ...}``.

Hazır şablonlar A2L'deki etiketleri ADLA eşler (ör. devir / sıcaklık / basınç ölçümleri); bulunamayanlar sessizce atlanır ve
kullanıcıya kaç etiketin eşleştiği bildirilir. Şablon uygulamak hiçbir şeyi ECU'ya yazmaz ve ölçümü başlatmaz.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from app.persist import atomic_write_json, load_json
from app.ui.modas.scope import sid_of

VALUE_W, VALUE_H, GAP = 260, 54, 8
COL_X = (10, 290)
SCOPE_GEOM_W, SCOPE_GEOM_H = 640, 380
MAX_MEAS = 8


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


_PERF_ALIASES = [   # Monitoring şablonu: performans ekibinin ölçüm takma adları (etiket, takma adlar)
    ('Comp Air Mass Flow Rate', ('compairmassflowrate', 'compmassflow', 'compflow', 'wcomp')),
    ('Comp Total Outlet Pressure', ('comptotaloutletpressure', 'compoutletpressure', 'comppout', 'p3')),
    ('Comp PR', ('comppr', 'compressorpr', 'prcomp')),
    ('Comp N', ('compn', 'compnrpm', 'compspeed', 'rpm', 'n')),
    ('Comp Surge Margin', ('compsurgemargin', 'surgemargin', 'compsm')),
    ('Comp Eff', ('compeff', 'compefficiency', 'etacomp')),
    ('CC Primer Fuel Mass Flow Rate', ('ccprimerfuelmassflowrate', 'ccprimerfuel', 'primerfuelflow', 'wfprimer')),
    ('CC Seconder Fuel Mass Flow Rate', ('ccsecoderfuelmassflowrate', 'ccsecnderfuel', 'ccsecondaryfuel', 'secoderfuelflow', 'wfsecond')),
    ('CC TIT', ('cctit', 'tit', 't4', 'turbineinlettemperature')),
    ('CC deIP', ('ccdeip', 'deip', 'dp', 'ccdp')),
    ('CC Eff', ('cceff', 'ccefficiency', 'etacc')),
    ('Turb Total Outlet Pressure', ('turbtotaloutletpressure', 'turboutletpressure', 'turbpout', 'p5')),
    ('Turb PR', ('turbpr', 'turbinepr', 'prturb')),
    ('Turb EGT', ('turbegt', 'egt', 't5', 'tt5')),
    ('Nozz Thrust', ('nozzthrust', 'thrust', 'fn')),
    ('Nozz Outlet Velocity', ('nozzoutletvelocity', 'nozzvelocity', 'outletvelocity', 'vnozz')),
    ('Nozz PR', ('nozzpr', 'nozzlepr', 'prnozz')),
]

_MONITOR_WORDS = re.compile(r"rpm|(^|_)n(_|$)|tit|t4|temp|tt\d|ps\d|p3|pressure|fuel|pump|flow", re.I)


@dataclass(frozen=True)
class TemplateInfo:
    name: str
    description: str
    builtin: bool = True


BUILTINS = [
    TemplateInfo("İzleme", "Motor performans çıkışları (devir, sıcaklık, basınç, yakıt) ve osiloskop"),
    TemplateInfo("Kalibrasyon", "Ayarlanabilir değerler ve ilk eğri / haritalar"),
    TemplateInfo("Test Tezgâhı", "Eyleyiciler penceresi, izleme değerleri ve osiloskop"),
]


def _value(name: str, x: int, y: int) -> dict:
    return {"kind": "value", "name": name, "geom": [x, y, VALUE_W, VALUE_H], "fmt": "phys"}


def _scope(labels: list, x: int, y: int, name: str = "Scope 1") -> dict:
    return {"kind": "scope", "name": name, "geom": [x, y, SCOPE_GEOM_W, SCOPE_GEOM_H], "span": 30.0,
            "panel": {"signals": [sid_of(n) for n in labels], "mode": 1 if len(labels) > 1 else 0}}


def _column(items: list, x: int, y0: int = 10) -> list:
    """Alt alta dizilen pencereler için ``(öğe, x, y)``."""
    return [(it, x, y0 + i * (VALUE_H + GAP)) for i, it in enumerate(items)]


def _readable(summary) -> list:
    return list(getattr(summary, "measurements", []) or []) if summary is not None else []


def _perf_matches(summary) -> list:
    """Performans arayüzü takma adlarıyla (devir, TIT, yakıt debisi …) eşleşen ölçüm adları, tanım sırasıyla."""
    by_norm = {}
    for m in _readable(summary):
        by_norm.setdefault(norm(m.name), []).append(m.name)
    out = []
    for label, aliases in _PERF_ALIASES:
        for alias in (*aliases, label):
            hits = by_norm.get(norm(alias), [])
            if len(hits) == 1 and hits[0] not in out:
                out.append(hits[0])
                break
    return out


def _monitor_names(summary) -> list:
    names = _perf_matches(summary)
    for m in _readable(summary):
        if len(names) >= MAX_MEAS:
            break
        if m.name not in names and _MONITOR_WORDS.search(m.name):
            names.append(m.name)
    return names[:MAX_MEAS]


def build_builtin(name: str, summary) -> list:
    """Hazır şablonun pencere tanımları (A2L eşleşmeleri ``summary``'den)."""
    specs: list = []
    if name == "İzleme":
        meas = _monitor_names(summary)
        specs += [_value(n, x, y) for n, x, y in _column(meas, COL_X[0])]
        specs.append(_scope(meas[:4], 290, 10))
    elif name == "Test Tezgâhı":
        meas = _monitor_names(summary)[:4]
        specs.append({"kind": "actuator", "name": "Eyleyiciler", "geom": [COL_X[0], 10, 300, 226]})
        specs += [_value(n, x, y + 236) for n, x, y in _column(meas, COL_X[0])]
        specs.append(_scope(meas, 330, 10))
    elif name == "Kalibrasyon":
        chars = list(getattr(summary, "characteristics", []) or []) if summary is not None else []
        scalars = [c for c in chars if c.kind == "SCALAR" and not c.read_only and getattr(c, "address", None)][:12]
        tables = [c for c in chars if c.kind in ("CURVE", "MAP") and not c.read_only and getattr(c, "address", None)][:3]
        specs += [_value(c.name, x, y) for c, x, y in _column(scalars, COL_X[0])]
        for i, c in enumerate(tables):
            specs.append({"kind": "table", "name": c.name, "geom": [COL_X[1] + 10 + i * 24, 10 + i * 40, 560, 300], "fmt": "phys"})
    return specs


class TemplateStore:
    """Kullanıcı şablonları: ``{"templates": {ad: [pencere tanımları]}}`` (JSON; hatada sessizce boş döner)."""

    def __init__(self, path: str | None):
        self.path = path

    def _all(self) -> dict:
        if not self.path:
            return {}
        data = load_json(self.path, {}, dict)
        raw = data.get("templates") if isinstance(data, dict) else None
        out = {}
        for k, v in (raw.items() if isinstance(raw, dict) else []):
            if isinstance(k, str) and isinstance(v, list):
                out[k] = [w for w in v if isinstance(w, dict) and isinstance(w.get("name"), str)]
        return out

    def names(self) -> list:
        return sorted(self._all(), key=str.lower)

    def get(self, name: str) -> list | None:
        return self._all().get(name)

    def save(self, name: str, specs: list) -> bool:
        name = (name or "").strip()
        if not name or not self.path or name in {t.name for t in BUILTINS}:
            return False
        data = self._all()
        data[name] = [w for w in specs if isinstance(w, dict)]
        return atomic_write_json(self.path, {"templates": data})

    def delete(self, name: str) -> bool:
        data = self._all()
        if name not in data:
            return False
        del data[name]
        return atomic_write_json(self.path, {"templates": data})


def build_specs(name: str, summary, store: TemplateStore | None = None) -> list | None:
    """Şablon adından pencere tanımları: hazır şablon ya da kullanıcı şablonu; bilinmiyorsa ``None``."""
    if name in {t.name for t in BUILTINS}:
        return build_builtin(name, summary)
    return store.get(name) if store is not None else None
