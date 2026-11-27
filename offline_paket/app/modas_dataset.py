"""Workbase'in kayıtlı veri seti (Modas "PC dataset") — Qt'den bağımsız.

Kılavuz §4: ECU'ya bağlanınca bilgisayardaki veri seti ECU'dakiyle karşılaştırılır. Bu projede HEX okuyucu yoktur;
bilgisayar veri seti, workbase klasöründeki ``dataset.json``'dır: son kaydedilen WP değerleri (``{etiket: sayı | tablo}``).
Karşılaştırma yalnızca iki tarafta da değeri olan etiketleri kapsar (worksheet'te açık etiketler).
"""
from __future__ import annotations

import math
import os
import time
from dataclasses import dataclass

from app.persist import atomic_write_json
from app.ui.modas.pages import _same, _copy

FILE_NAME = "dataset.json"


@dataclass
class DiffEntry:
    name: str
    pc: object
    ecu: object


def compare(pc: dict, ecu: dict) -> list:
    """İki tarafta da bulunup değeri farklı olan etiketler, ada göre sıralı."""
    return [DiffEntry(k, pc[k], ecu[k]) for k in sorted(pc)
            if k in ecu and pc[k] is not None and ecu[k] is not None and not _same(pc[k], ecu[k])]


def _valid(v) -> bool:
    if isinstance(v, bool):
        return False
    if isinstance(v, (int, float)):
        return math.isfinite(v)                       # NaN / ±inf dosyaya girmez (JSON'da geçersiz)
    return isinstance(v, list) and bool(v) and all(
        isinstance(r, list) and r and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                                          for x in r) for r in v)


class DatasetStore:
    def __init__(self, workbase_path: str):
        self.path = os.path.join(workbase_path, FILE_NAME)

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def load(self) -> dict | None:
        """Kayıtlı değerler; dosya yok / bozuk ise ``None`` (bozuk dosya sessizce 'veri seti yok' sayılır, hata fırlatmaz)."""
        import json
        try:
            with open(self.path, encoding="utf-8") as fh:
                raw = json.load(fh)
        except (OSError, ValueError):
            return None
        vals = raw.get("values") if isinstance(raw, dict) else None
        if not isinstance(vals, dict):
            return None
        return {str(k): _copy(v) for k, v in vals.items() if _valid(v)}

    def save(self, values: dict) -> bool:
        clean = {str(k): _copy(v) for k, v in values.items() if _valid(v)}
        return atomic_write_json(self.path, {"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "values": clean})
