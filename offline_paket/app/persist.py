"""Kalıcı JSON dosyaları için ortak, güvenli okuma/yazma.

  * atomic_write_json: önce .tmp'ye yazar, fsync yapar, os.replace ile yerine
    koyar; mevcut iyi dosya `.bak` olarak saklanır. Çökme/elektrik kesintisi
    yarım dosya bırakmaz.
  * load_json: dosya yok -> default; bozuk/okunamaz -> dosya `.corrupt-<zaman>`
    adıyla KORUNUR (sonraki kayıt onu ezmesin), son iyi `.bak` denenir, yoksa
    default döner. Hiçbir durumda istisna fırlatmaz.
Başarısızlıklar `logging` ile loglanır; çağıran yazma sonucunu bool olarak alır.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger(__name__)


def atomic_write_json(path: str, data, indent: int | None = 2) -> bool:
    """True: yazıldı. False: yazılamadı (loglanır; mevcut dosya bozulmaz)."""
    tmp = path + ".tmp"
    try:
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            try:
                os.replace(path, path + ".bak")
            except OSError:
                pass
        os.replace(tmp, path)
        return True
    except (OSError, TypeError, ValueError) as exc:
        log.error("Kayıt başarısız: %s (%s)", path, exc)
        try:
            os.remove(tmp)
        except OSError:
            pass
        return False


def _quarantine(path: str, reason: str):
    dest = f"{path}.corrupt-{time.strftime('%Y%m%d_%H%M%S')}"
    try:
        os.replace(path, dest)
        log.error("Bozuk dosya %s -> %s olarak saklandı (%s)", path, dest, reason)
    except OSError:
        log.error("Bozuk dosya %s saklanamadı (%s)", path, reason)


def load_json(path: str, default=None, expect: type | tuple | None = None):
    """JSON yükler; expect verilirse kök tür doğrulanır (dict/list)."""
    # Ana dosya yoksa da `.bak` denenir: atomic_write_json'da eski dosya `.bak`'a taşındıktan sonra,
    # yenisi yerine konmadan çökülürse geriye yalnızca `.bak` kalır.
    if not path or not (os.path.exists(path) or os.path.exists(path + ".bak")):
        return default
    for candidate, is_backup in ((path, False), (path + ".bak", True)):
        if not os.path.exists(candidate):
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                data = json.load(f)
            if expect is not None and not isinstance(data, expect):
                raise ValueError(f"beklenen kök tür {expect}, gelen {type(data).__name__}")
            if is_backup:
                log.warning("%s yok ya da okunamadı; son iyi yedek (.bak) kullanıldı.", path)
            return data
        except (OSError, ValueError) as exc:
            if not is_backup:
                _quarantine(path, str(exc))
    return default
