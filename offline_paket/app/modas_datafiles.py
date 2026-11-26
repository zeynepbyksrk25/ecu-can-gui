"""Veri / parametre dosyaları (Qt'siz): worksheet etiketlerinin WP değerlerini dosyaya yazar, dosyadan okur, karşılaştırır.

Biçim (``.json``): ``{"format": "openecu-parameters", "version": 1, "saved": ..., "project": ..., "workbase": ...,
"values": {etiket: sayı | tablo}}``. Dosya ASLA ECU'ya yazmaz; uygulamak, MainWindow'daki güvenli yazma yolundan geçer.
"""
from __future__ import annotations

import json
import os
import re
import time

from app.modas_dataset import DiffEntry, _valid, compare
from app.persist import atomic_write_json
from app.ui.modas.pages import _copy

FORMAT = "openecu-parameters"
VERSION = 1
EXT = ".json"
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class DataFileError(ValueError):
    """Kullanıcıya gösterilebilir dosya hatası."""


def export_values(path: str, values: dict, project: str = "", workbase: str = "") -> int:
    """Geçerli değerleri dosyaya yazar; yazılan etiket sayısını döner. Hiç geçerli değer yoksa hata (boş dosya üretilmez)."""
    clean = {str(k): _copy(v) for k, v in values.items() if _valid(v)}
    if not clean:
        raise DataFileError("Kaydedilecek geçerli değer yok (worksheet'te okunmuş ayar değeri bulunmuyor).")
    ok = atomic_write_json(path, {"format": FORMAT, "version": VERSION, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
                                  "project": project, "workbase": workbase, "values": clean})
    if not ok:
        raise DataFileError(f"Dosya yazılamadı: {path}")
    return len(clean)


def load_values(path: str) -> dict:
    """Dosyadaki değerler. Biçim / sürüm / içerik doğrulanır; geçersiz girdiler elenir, hiç kalmazsa hata."""
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except OSError as exc:
        raise DataFileError(f"Dosya okunamadı: {exc}") from exc
    except ValueError as exc:
        raise DataFileError(f"Dosya JSON değil ya da bozuk: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("format") != FORMAT:
        raise DataFileError("Bu bir OpenECU parametre dosyası değil.")
    if not isinstance(raw.get("version"), int) or raw["version"] > VERSION:
        raise DataFileError(f"Desteklenmeyen dosya sürümü: {raw.get('version')}")
    vals = raw.get("values")
    if not isinstance(vals, dict):
        raise DataFileError("Dosyada 'values' bölümü yok.")
    out = {str(k): _copy(v) for k, v in vals.items() if _valid(v)}
    if not out:
        raise DataFileError("Dosyada geçerli değer yok.")
    return out


def compare_with_file(wp: dict, file_values: dict) -> tuple:
    """``(farklar, yalnızca_dosyada, yalnızca_wp)``: farklar ``DiffEntry(name, pc=WP, ecu=dosya)``; yani ``pc`` alanı WP
    değeri, ``ecu`` alanı DOSYA değeridir (ortak ``compare`` yeniden kullanıldığı için)."""
    diffs = compare(wp, file_values)
    only_file = sorted(k for k in file_values if k not in wp)
    only_wp = sorted(k for k in wp if k not in file_values)
    return diffs, only_file, only_wp


def safe_file_name(name: str) -> str:
    name = _BAD.sub("_", (name or "").strip()).strip(". ")
    if not name:
        raise DataFileError("Dosya adı boş olamaz.")
    return name[:80]


class ParameterFolder:
    """Bir klasördeki parametre dosyaları (``*.json``): listele, kaydet, sil."""

    def __init__(self, folder: str):
        self.folder = folder

    def list(self) -> list:
        """``[(ad, yol, değiştirilme zamanı)]``, en yeni üstte; yalnızca geçerli parametre dosyaları."""
        if not os.path.isdir(self.folder):
            return []
        out = []
        for fn in os.listdir(self.folder):
            path = os.path.join(self.folder, fn)
            if fn.lower().endswith(EXT) and os.path.isfile(path):
                try:
                    load_values(path)
                except DataFileError:
                    continue
                out.append((fn[:-len(EXT)], path, os.path.getmtime(path)))
        return sorted(out, key=lambda t: -t[2])

    def path_for(self, name: str) -> str:
        return os.path.join(self.folder, safe_file_name(name) + EXT)

    def save(self, name: str, values: dict, project: str = "", workbase: str = "", overwrite: bool = False) -> str:
        path = self.path_for(name)
        if os.path.exists(path) and not overwrite:
            raise DataFileError(f"'{os.path.basename(path)}' zaten var.")
        os.makedirs(self.folder, exist_ok=True)
        export_values(path, values, project, workbase)
        return path

    def delete(self, name: str) -> bool:
        path = self.path_for(name)
        if not os.path.isfile(path):
            return False
        os.remove(path)
        return True
