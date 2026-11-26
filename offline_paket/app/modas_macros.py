"""Macro manager (Qt'siz): kullanıcının yaptığı ayar yazımlarını kaydedip aynı sırayla yeniden oynatır.

Bir macro, adım listesidir: ``{"kind": "value" | "table" | "input", "label": ..., "value": sayı | tablo}``. Macro dosyası ASLA
kendi başına bir şey yazmaz: oynatma, MainWindow'daki güvenli yazma yollarından (rol, yedek, doğrulama) geçer. Kayıt,
yalnızca BAŞARILI yazımları ekler.
"""
from __future__ import annotations

import json
import os
import re
import time

from app.modas_dataset import _valid
from app.persist import atomic_write_json
from app.ui.modas.pages import _copy

KINDS = ("value", "table", "input")
EXT = ".json"
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class MacroError(ValueError):
    pass


def check_step(step) -> dict:
    if not isinstance(step, dict) or step.get("kind") not in KINDS:
        raise MacroError("Geçersiz macro adımı.")
    label = step.get("label")
    if not isinstance(label, str) or not label:
        raise MacroError("Macro adımında etiket yok.")
    if not _valid(step.get("value")):
        raise MacroError(f"'{label}' için geçersiz değer.")
    if step["kind"] == "table" and not isinstance(step["value"], list):
        raise MacroError(f"'{label}' tablo adımı tablo değeri taşımalı.")
    if step["kind"] != "table" and isinstance(step["value"], list):
        raise MacroError(f"'{label}' tek değer adımı tablo taşıyamaz.")
    return {"kind": step["kind"], "label": label, "value": _copy(step["value"])}


class MacroRecorder:
    """Kayıt: art arda aynı etiketin yazımları tek adıma indirilir (yalnızca son değer kalır)."""

    def __init__(self):
        self.steps: list = []
        self.active = False

    def start(self):
        self.steps, self.active = [], True

    def stop(self) -> list:
        self.active = False
        return list(self.steps)

    def add(self, kind: str, label: str, value):
        if not self.active:
            return
        step = check_step({"kind": kind, "label": label, "value": value})
        if self.steps and self.steps[-1]["kind"] == kind and self.steps[-1]["label"] == label:
            self.steps[-1] = step
        else:
            self.steps.append(step)


def safe_name(name: str) -> str:
    name = _BAD.sub("_", (name or "").strip()).strip(". ")
    if not name:
        raise MacroError("Macro adı boş olamaz.")
    return name[:80]


class MacroStore:
    def __init__(self, folder: str):
        self.folder = folder

    def path_for(self, name: str) -> str:
        return os.path.join(self.folder, safe_name(name) + EXT)

    def names(self) -> list:
        if not os.path.isdir(self.folder):
            return []
        return sorted((fn[:-len(EXT)] for fn in os.listdir(self.folder) if fn.lower().endswith(EXT)), key=str.lower)

    def load(self, name: str) -> list:
        try:
            with open(self.path_for(name), encoding="utf-8") as fh:
                raw = json.load(fh)
        except OSError as exc:
            raise MacroError(f"Macro okunamadı: {exc}") from exc
        except ValueError as exc:
            raise MacroError(f"Macro dosyası bozuk: {exc}") from exc
        steps = raw.get("steps") if isinstance(raw, dict) else None
        if not isinstance(steps, list) or not steps:
            raise MacroError("Macro adım içermiyor.")
        return [check_step(s) for s in steps]

    def save(self, name: str, steps: list, overwrite: bool = False) -> str:
        if not steps:
            raise MacroError("Boş macro kaydedilemez (hiç yazım yapılmadı).")
        checked = [check_step(s) for s in steps]
        path = self.path_for(name)
        if os.path.exists(path) and not overwrite:
            raise MacroError(f"'{safe_name(name)}' adlı macro zaten var.")
        if not atomic_write_json(path, {"saved": time.strftime("%Y-%m-%d %H:%M:%S"), "steps": checked}):
            raise MacroError("Macro yazılamadı.")
        return path

    def delete(self, name: str) -> bool:
        path = self.path_for(name)
        if not os.path.isfile(path):
            return False
        os.remove(path)
        return True


def missing_labels(steps: list, available: set) -> list:
    """Macro'nun kullandığı ama worksheet'te açık olmayan etiketler (oynatmadan önce kullanıcıya söylenir)."""
    return sorted({s["label"] for s in steps if s["label"] not in available})


def describe(step: dict) -> str:
    v = step["value"]
    text = f"{len(v)}×{len(v[0])} tablo" if isinstance(v, list) else f"{v:g}"
    return f"{step['label']} = {text}"
