"""A2L parametresi -> Simulink model değişkeni eşleme katmanı (JSON manifest).

A2L adresleri ile Simulink değişkenlerinin aynı olduğu VARSAYILMAZ; eşleme açıktır:
``A2L Parameter -> Simulink Model Variable -> Data Type -> Scaling -> Access Permission``.

Manifest örneği::

    {"version": 1, "parameters": [
      {"a2l": "Kp_Governor", "simulink": "Governor/Kp", "index": 1, "datatype": "double",
       "factor": 1.0, "offset": 0.0, "access": "rw", "tunable_running": true},
      {"a2l": "FuelMap", "simulink": "Fuel/Table", "index": 10, "count": 12, "datatype": "double", "access": "rw",
       "tunable_running": false}]}

Ölçekleme: ``model_değeri = a2l_fiziksel * factor + offset``. ``count`` > 1: dizi/harita hücreleri (satır-öncelikli),
indeksler ``index .. index+count-1``. ``tunable_running``: model ÇALIŞIRKEN yazılabilir mi (Simulink tunable kuralı);
değilse yazma reddedilir ve kullanıcıya modelin durdurulması gerektiği bildirilir.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

DATATYPES = {"double", "single", "int8", "uint8", "int16", "uint16", "int32", "uint32", "boolean"}
ACCESS = {"rw", "ro"}
_INT_RANGES = {"int8": (-128, 127), "uint8": (0, 255), "int16": (-32768, 32767), "uint16": (0, 65535),
               "int32": (-2**31, 2**31 - 1), "uint32": (0, 2**32 - 1), "boolean": (0, 1)}


class ManifestError(ValueError):
    pass


@dataclass(frozen=True)
class ParamMap:
    a2l: str
    simulink: str
    index: int
    datatype: str = "double"
    factor: float = 1.0
    offset: float = 0.0
    access: str = "rw"
    tunable_running: bool = False
    count: int = 1

    @property
    def writable(self) -> bool:
        return self.access == "rw"

    def to_model(self, phys: float) -> float:
        return phys * self.factor + self.offset

    def from_model(self, value: float) -> float:
        return (value - self.offset) / self.factor

    def check_model_value(self, value: float):
        """Veri tipi aralığı (tamsayı/boolean) denetimi; double/single için yalnızca sonlu olmalı."""
        if not math.isfinite(value):
            raise ValueError("değer sonlu değil")
        rng = _INT_RANGES.get(self.datatype)
        if rng and not rng[0] <= value <= rng[1]:
            raise ValueError(f"{self.datatype} aralığı dışında: {value:g} (izinli {rng[0]}..{rng[1]})")


@dataclass
class Manifest:
    params: list

    def by_a2l(self) -> dict:
        return {p.a2l: p for p in self.params}


def parse_manifest(raw) -> Manifest:
    if not isinstance(raw, dict) or not isinstance(raw.get("parameters"), list):
        raise ManifestError("Manifest 'parameters' listesi içermiyor")
    out, names, used = [], set(), set()
    for i, e in enumerate(raw["parameters"]):
        if not isinstance(e, dict):
            raise ManifestError(f"#{i}: nesne değil")
        try:
            a2l, sim, idx = str(e["a2l"]), str(e["simulink"]), int(e["index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ManifestError(f"#{i}: a2l/simulink/index zorunlu ({exc})") from exc
        dt = str(e.get("datatype", "double"))
        if dt not in DATATYPES:
            raise ManifestError(f"{a2l}: veri tipi {dt!r} desteklenmiyor")
        acc = str(e.get("access", "rw"))
        if acc not in ACCESS:
            raise ManifestError(f"{a2l}: erişim {acc!r} geçersiz (rw/ro)")
        try:
            factor, offset, count = float(e.get("factor", 1.0)), float(e.get("offset", 0.0)), int(e.get("count", 1))
        except (TypeError, ValueError) as exc:
            raise ManifestError(f"{a2l}: sayısal alan hatalı ({exc})") from exc
        if not (math.isfinite(factor) and factor != 0 and math.isfinite(offset)):
            raise ManifestError(f"{a2l}: factor sıfır/sonsuz olamaz")
        if count < 1 or idx < 0 or idx + count - 1 > 0xFFFF:
            raise ManifestError(f"{a2l}: index/count aralık dışı")
        if a2l in names:
            raise ManifestError(f"{a2l}: tekrarlanan A2L adı")
        cells = set(range(idx, idx + count))
        if cells & used:
            raise ManifestError(f"{a2l}: indeks çakışması")
        names.add(a2l)
        used |= cells
        out.append(ParamMap(a2l, sim, idx, dt, factor, offset, acc, bool(e.get("tunable_running", False)), count))
    return Manifest(out)


def load_manifest(path: str) -> Manifest:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except OSError as exc:
        raise ManifestError(f"Manifest okunamadı: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ManifestError(f"Manifest JSON hatalı: {exc}") from exc
    return parse_manifest(raw)
