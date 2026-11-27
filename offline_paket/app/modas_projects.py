"""Modas Sport proje / workbase deposu (Qt'den bağımsız).

Kılavuz §2 ("Creating a workbase"):

* Bir **proje** klasörüdür; içinde ``DATA`` (ECU programı: A2L / HEX), ``CONFIG``, ``LOGFILES`` ve ``MACRO`` alt klasörleri bulunur.
* Bir **workbase**, projenin altında kendi adıyla bir alt klasördür ve şu bilgileri tutar: ad, A2L dosyası, HEX dosyası,
  ECU, Seed&Key kütüphanesi, iletişim protokolü, baudrate, iletişim donanımı, açıklama.

Diskte: ``<kök>/<Proje>/project.json`` ve ``<kök>/<Proje>/<Workbase>/workbase.json``. Mevcut (dışarıdan) projeler
``Add existing`` ile kök dışından da eklenebilir; bunların yolu ``<kök>/projects_index.json``'da tutulur.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from dataclasses import asdict, dataclass, field

PROJECT_SUBDIRS = ("DATA", "CONFIG", "LOGFILES", "MACRO")
PROTOCOLS = ("CCP", "KWP2000")
HARDWARE = ("PCAN", "MSA-Box")
_BAD_NAME = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class ProjectError(ValueError):
    """Geçersiz ad / zaten var / bulunamadı gibi kullanıcıya gösterilebilir hatalar."""


def check_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ProjectError("Ad boş olamaz.")
    if _BAD_NAME.search(name) or name in (".", "..") or name.endswith("."):
        raise ProjectError('Ad şu karakterleri içeremez: \\ / : * ? " < > |')
    if len(name) > 64:
        raise ProjectError("Ad en çok 64 karakter olabilir.")
    return name


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _read_json(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path: str, data: dict):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


@dataclass
class Workbase:
    name: str
    created: str = ""
    a2l: str = ""
    hex: str = ""
    ecu: str = ""
    seedkey: str = ""
    protocol: str = "CCP"
    baudrate: int = 500000
    hardware: str = "PCAN"
    comment: str = ""
    path: str = field(default="", compare=False)           # workbase klasörü (diske yazılmaz)

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("path", None)
        return d


@dataclass
class Project:
    name: str
    path: str
    created: str = ""
    comment: str = ""


class ProjectStore:
    def __init__(self, root: str):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self._index_path = os.path.join(root, "projects_index.json")

    # ---- projeler -----------------------------------------------------------------
    def _external(self) -> list:
        raw = _read_json(self._index_path).get("external", [])
        return [p for p in raw if isinstance(p, str)]

    def _project_at(self, path: str) -> Project | None:
        meta_path = os.path.join(path, "project.json")
        if not os.path.isfile(meta_path):
            return None
        meta = _read_json(meta_path)
        return Project(name=str(meta.get("name") or os.path.basename(path)), path=path,
                       created=str(meta.get("created", "")), comment=str(meta.get("comment", "")))

    def list_projects(self) -> list:
        found = []
        for entry in sorted(os.listdir(self.root), key=str.lower):
            pr = self._project_at(os.path.join(self.root, entry))
            if pr is not None:
                found.append(pr)
        for path in self._external():
            pr = self._project_at(path)
            if pr is not None and all(os.path.abspath(pr.path) != os.path.abspath(f.path) for f in found):
                found.append(pr)
        return found

    def get_project(self, name: str) -> Project:
        for pr in self.list_projects():
            if pr.name == name:
                return pr
        raise ProjectError(f"Proje bulunamadı: {name}")

    def create_project(self, name: str, comment: str = "") -> Project:
        name = check_name(name)
        path = os.path.join(self.root, name)
        if os.path.exists(path) or any(p.name.lower() == name.lower() for p in self.list_projects()):
            raise ProjectError(f"'{name}' adlı proje zaten var.")
        os.makedirs(path)
        for sub in PROJECT_SUBDIRS:
            os.makedirs(os.path.join(path, sub), exist_ok=True)
        _write_json(os.path.join(path, "project.json"), {"name": name, "created": _now(), "comment": comment})
        return self._project_at(path)

    def add_existing(self, path: str) -> Project:
        """Başka bir yerdeki proje klasörünü (project.json içeren) listeye ekler."""
        path = os.path.abspath(path)
        pr = self._project_at(path)
        if pr is None:
            raise ProjectError("Seçilen klasörde project.json yok; Modas projesi değil.")
        if any(os.path.abspath(p.path) == path for p in self.list_projects()):
            raise ProjectError("Bu proje zaten listede.")
        _write_json(self._index_path, {"external": self._external() + [path]})
        return pr

    def delete_project(self, name: str, delete_files: bool = False):
        """Projeyi listeden çıkarır; ``delete_files`` doğruysa klasörünü de siler (yalnızca kök altındakiler)."""
        pr = self.get_project(name)
        ext = [p for p in self._external() if os.path.abspath(p) != os.path.abspath(pr.path)]
        _write_json(self._index_path, {"external": ext})
        inside_root = os.path.abspath(pr.path).startswith(os.path.abspath(self.root) + os.sep)
        if delete_files and inside_root:
            shutil.rmtree(pr.path, ignore_errors=True)

    # ---- workbase'ler -------------------------------------------------------------
    def list_workbases(self, project: str) -> list:
        pr = self.get_project(project)
        out = []
        for entry in sorted(os.listdir(pr.path), key=str.lower):
            wb_dir = os.path.join(pr.path, entry)
            meta = os.path.join(wb_dir, "workbase.json")
            if os.path.isfile(meta):
                out.append(self._load_workbase(wb_dir))
        return out

    def _load_workbase(self, wb_dir: str) -> Workbase:
        d = _read_json(os.path.join(wb_dir, "workbase.json"))
        wb = Workbase(name=str(d.get("name") or os.path.basename(wb_dir)))
        for key in ("created", "a2l", "hex", "ecu", "seedkey", "comment"):
            setattr(wb, key, str(d.get(key, "")))
        wb.protocol = d.get("protocol") if d.get("protocol") in PROTOCOLS else "CCP"
        wb.hardware = d.get("hardware") if d.get("hardware") in HARDWARE else "PCAN"
        try:
            wb.baudrate = int(d.get("baudrate", 500000))
        except (TypeError, ValueError):
            wb.baudrate = 500000
        wb.path = wb_dir
        return wb

    def get_workbase(self, project: str, name: str) -> Workbase:
        for wb in self.list_workbases(project):
            if wb.name == name:
                return wb
        raise ProjectError(f"Workbase bulunamadı: {name}")

    def save_workbase(self, project: str, wb: Workbase, create: bool = True) -> Workbase:
        """Yeni workbase oluşturur (``create``) ya da mevcut olanı günceller. Doğrulama burada yapılır."""
        pr = self.get_project(project)
        wb.name = check_name(wb.name)
        if wb.protocol not in PROTOCOLS:
            raise ProjectError(f"Protokol şunlardan biri olmalı: {', '.join(PROTOCOLS)}")
        if wb.hardware not in HARDWARE:
            raise ProjectError(f"Donanım şunlardan biri olmalı: {', '.join(HARDWARE)}")
        if not 10000 <= int(wb.baudrate) <= 1000000:
            raise ProjectError("Baudrate 10 kbit/s ile 1 Mbit/s arasında olmalı.")
        for label, path in (("A2L", wb.a2l), ("HEX", wb.hex)):
            if path and not os.path.isfile(path):
                raise ProjectError(f"{label} dosyası bulunamadı: {path}")
        wb_dir = os.path.join(pr.path, wb.name)
        exists = os.path.isfile(os.path.join(wb_dir, "workbase.json"))
        if create and exists:
            raise ProjectError(f"'{wb.name}' adlı workbase bu projede zaten var.")
        if not create and not exists:
            raise ProjectError(f"Workbase bulunamadı: {wb.name}")
        os.makedirs(wb_dir, exist_ok=True)
        wb.created = wb.created or _now()
        wb.path = wb_dir
        _write_json(os.path.join(wb_dir, "workbase.json"), wb.to_dict())
        return wb

    def delete_workbase(self, project: str, name: str):
        wb = self.get_workbase(project, name)
        shutil.rmtree(wb.path, ignore_errors=True)
