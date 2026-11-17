"""Tablo (harita/eğri/dizi) yazımı öncesi ECU içeriğinin yedeği ve yedekten geri yükleme.

Her tablo yazımından önce ECU'daki mevcut içerik ``<veri klasörü>/tablo_yedekleri/<ad>_<tarih_saat>.json``
olarak saklanır. Geri yükleme yalnızca değerleri tabloya getirir; ECU'ya yazmak ayrı (rol denetimli) bir adımdır.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import NamedTuple


class Backup(NamedTuple):
    path: str
    name: str
    mtime: float
    label: str          # listede gösterilen: "16.11.2026 14:05:09  (3x4)"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", name)


def save(folder: str, characteristic, grid: list) -> str:
    """Yedeği yazar; dosya adını döner. Başarısızsa '' (yazma akışını durdurmaz)."""
    try:
        os.makedirs(folder, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        fname = f"{_safe(characteristic.name)}_{stamp}.json"
        n = 1
        while os.path.exists(os.path.join(folder, fname)):      # aynı saniyede ikinci yazma ezmesin
            fname = f"{_safe(characteristic.name)}_{stamp}_{n}.json"
            n += 1
        with open(os.path.join(folder, fname), "w", encoding="utf-8") as f:
            json.dump({"name": characteristic.name, "address": characteristic.address,
                       "unit": characteristic.unit, "grid": grid}, f, ensure_ascii=False)
        return fname
    except (OSError, TypeError, ValueError):
        return ""


def list_backups(folder: str, characteristic) -> list[Backup]:
    """Bu nesneye ait yedekler, en yeniden eskiye. Başka nesnelerin yedekleri (ad öneki benzese bile) gelmez."""
    out: list[Backup] = []
    if not os.path.isdir(folder):
        return out
    prefix = _safe(characteristic.name) + "_"
    for fname in os.listdir(folder):
        if not (fname.startswith(prefix) and fname.endswith(".json")):
            continue
        # "<ad>_<tarih>_<saat>[_n].json": addan sonra yalnızca tarih/saat parçaları gelmeli
        rest = fname[len(prefix):-5]
        if not re.fullmatch(r"\d{8}_\d{6}(_\d+)?", rest):
            continue
        path = os.path.join(folder, fname)
        try:
            data = _read(path)
        except ValueError:
            continue
        if data.get("name") != characteristic.name:
            continue
        mtime = os.path.getmtime(path)
        grid = data["grid"]
        shape = f"{len(grid)}x{len(grid[0]) if grid else 0}"
        out.append(Backup(path, fname, mtime,
                          f"{time.strftime('%d.%m.%Y %H:%M:%S', time.localtime(mtime))}  ({shape})"))
    return sorted(out, key=lambda b: (b.mtime, b.name), reverse=True)


def _read(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Yedek okunamadı: {exc}")
    grid = data.get("grid") if isinstance(data, dict) else None
    if not isinstance(grid, list) or not all(isinstance(r, list) for r in grid):
        raise ValueError("Yedek dosyası geçerli bir tablo içermiyor.")
    return data


def load(path: str, characteristic, expected_shape: tuple[int, int]) -> list:
    """Yedeği okur ve DOĞRULAR: aynı nesne, aynı adres, aynı boyut, sayısal ve sonlu değerler.
    Uymayan yedek (başka A2L revizyonu, boyut değişmiş) ValueError ile reddedilir."""
    data = _read(path)
    if data.get("name") != characteristic.name:
        raise ValueError(f"Yedek başka bir nesneye ait ({data.get('name')!r}).")
    if data.get("address") != characteristic.address:
        raise ValueError(
            f"Yedeğin adresi (0x{(data.get('address') or 0):X}) şu anki A2L'deki adresten "
            f"(0x{characteristic.address:X}) farklı; başka bir A2L revizyonundan olabilir.")
    grid = data["grid"]
    rows, cols = expected_shape
    if len(grid) != rows or any(len(r) != cols for r in grid):
        raise ValueError(f"Yedeğin boyutu şu anki tabloyla ({rows}x{cols}) uyuşmuyor.")
    out = []
    for r in grid:
        row = []
        for v in r:
            if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v or abs(v) == float("inf"):
                raise ValueError("Yedekte sayısal olmayan ya da sonlu olmayan değer var.")
            row.append(float(v))
        out.append(row)
    return out
