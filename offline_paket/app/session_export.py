"""Kayıtlı oturumu (``<ad>.csv`` + ``.events.csv`` + ``.meta.json`` + ``.asc``) yükleme ve dışa aktarma.

Formatlar birbirinin yerine GEÇMEZ:
  * MDF4 (.mf4)  – fiziksel sinyal zaman serisi (her sinyal kendi zaman damgalarıyla, ayrı kanal grubu; ad, birim, kaynak
                   açıklamada). Ham CAN içermez. AVL Concerto ile uyumluluk burada DOĞRULANMADI (bkz. docs/DECISIONS.md).
  * ASC (.asc)   – ham CAN kareleri (Vector ASCII, python-can ``ASCWriter``). Fiziksel sinyal içermez.
  * LOG (.log)   – ``log_asc``: ASC içeriği ``.log`` uzantısıyla (uzantı değişimi hedef yazılımda doğrulanmadı);
                   ``log_candump``: can-utils ``candump -L`` biçimi (``(zaman) kanal ID#VERİ``).
  * CSV (.csv)   – uzun biçim (time,signal,value,unix_time) – kayıt dosyasının kendisi.
  * MAT (.mat)   – MATLAB: sinyal başına {time, values, unit}.
Büyük kayıtlarda bellek: değerler ``array('d')`` ile tutulur (Python float listesinin ~1/3'ü).
"""
from __future__ import annotations

import array
import csv
import json
import math
import os
import shutil
from dataclasses import dataclass, field

import numpy as np


@dataclass
class SessionData:
    path: str
    meta: dict = field(default_factory=dict)
    t_rel: dict = field(default_factory=dict)       # sid -> array('d') oturum başından saniye
    t_unix: dict = field(default_factory=dict)      # sid -> array('d') epoch
    values: dict = field(default_factory=dict)      # sid -> array('d')
    events: list = field(default_factory=list)      # (t_rel, t_unix, kind, text)
    skipped_rows: int = 0

    @property
    def root(self) -> str:
        return self.path[:-4] if self.path.lower().endswith(".csv") else self.path

    def signals(self) -> list:
        return sorted(self.values)

    def info(self, sid: str) -> dict:
        return (self.meta.get("signals") or {}).get(sid, {})

    def unit(self, sid: str) -> str:
        return self.info(sid).get("unit", "")

    def source(self, sid: str) -> str:
        return self.info(sid).get("source") or sid.split(":", 1)[0]

    def arrays(self, sid: str):
        return np.frombuffer(self.t_rel[sid], dtype=float), np.frombuffer(self.values[sid], dtype=float)

    def has_sim_time(self) -> bool:
        return "mil:sim_time" in self.values and len(self.values["mil:sim_time"]) >= 2

    def to_sim_time(self, t_unix) -> "np.ndarray | None":
        """Gerçek (alım) zamanını simülasyon zamanına çevirir (``mil:sim_time`` eşlemesiyle doğrusal ara değer).
        Eşleme yoksa / simülasyon zamanı geriye gitmişse (yeniden başlatma) ``None`` — uydurma dönüşüm yapılmaz.
        Eşleme aralığı dışındaki zamanlar NaN olur."""
        if not self.has_sim_time():
            return None
        wall = np.frombuffer(self.t_unix["mil:sim_time"], dtype=float)
        sim = np.frombuffer(self.values["mil:sim_time"], dtype=float)
        if np.any(np.diff(sim) < 0) or np.any(np.diff(wall) <= 0):
            return None
        t = np.asarray(t_unix, dtype=float)
        out = np.interp(t, wall, sim)
        out[(t < wall[0]) | (t > wall[-1])] = np.nan
        return out

    def asc_path(self) -> str | None:
        p = self.root + ".asc"
        return p if os.path.exists(p) else None


def load_session(csv_path: str, progress=None) -> SessionData:
    """Kayıt CSV'sini (+ olay/üst veri dosyaları) yükler. Bozuk/NaN/Inf satırlar atlanır ve sayılır; yarım kalmış (çökmüş)
    kaydın son satırı güvenle yok sayılır. ``progress(n_rows)`` isteğe bağlı geri çağrı (çalışan iş parçacığı için)."""
    sd = SessionData(path=csv_path)
    n = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)
        for row in reader:
            n += 1
            if progress and n % 200_000 == 0:
                progress(n)
            if len(row) < 4:
                sd.skipped_rows += 1
                continue
            try:
                tr, v, tu = float(row[0]), float(row[2]), float(row[3])
            except ValueError:
                sd.skipped_rows += 1
                continue
            if not (math.isfinite(tr) and math.isfinite(v) and math.isfinite(tu)):
                sd.skipped_rows += 1
                continue
            sid = row[1]
            if sid not in sd.values:
                sd.t_rel[sid], sd.t_unix[sid], sd.values[sid] = array.array("d"), array.array("d"), array.array("d")
            sd.t_rel[sid].append(tr)
            sd.t_unix[sid].append(tu)
            sd.values[sid].append(v)
    root = sd.root
    try:
        with open(root + ".meta.json", encoding="utf-8") as f:
            sd.meta = json.load(f)
    except (OSError, ValueError):
        sd.meta = {}
    try:
        with open(root + ".events.csv", newline="", encoding="utf-8") as f:
            r = csv.reader(f)
            next(r, None)
            for row in r:
                try:
                    sd.events.append((float(row[0]), float(row[1]), row[2], row[3] if len(row) > 3 else ""))
                except (ValueError, IndexError):
                    continue
    except OSError:
        pass
    return sd


def list_sessions(directory: str) -> list[dict]:
    """Klasördeki oturumlar (yeniden eskiye). ``status=recording`` olup uygulama artık çalışmıyorsa kayıt beklenmedik
    kapanmıştır: ``recovered`` olarak döner (CSV her saniye flush edildiğinden büyük ölçüde kurtarılır)."""
    out = []
    if not os.path.isdir(directory):
        return out
    for name in os.listdir(directory):
        if not name.endswith(".csv") or name.endswith((".events.csv", "_girisler.csv")):
            continue
        path = os.path.join(directory, name)
        root = path[:-4]
        meta = {}
        try:
            with open(root + ".meta.json", encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            pass
        status = meta.get("status", "unknown")
        if status == "recording":
            status = "recovered"
        out.append({"path": path, "name": meta.get("name") or name[:-4], "start": meta.get("start_unix") or
                    os.path.getmtime(path), "duration_s": meta.get("duration_s"), "status": status,
                    "mode": meta.get("mode", ""), "user": meta.get("user", ""), "size": os.path.getsize(path),
                    "has_asc": os.path.exists(root + ".asc")})
    out.sort(key=lambda d: d["start"], reverse=True)
    return out


# ---------------------------------------------------------------- yazıcılar
def write_mdf4(path: str, sd: SessionData, version: str = "4.10", signals: list | None = None) -> int:
    """MDF4: her sinyal kendi zaman damgalarıyla AYRI kanal grubuna yazılır (farklı örnekleme anlarında kayma olmaz).
    Zaman = oturum başından saniye; mutlak başlangıç MDF başlığında. Yazılan sinyal sayısını döner."""
    import datetime
    from asammdf import MDF, Signal
    sel = signals if signals is not None else sd.signals()
    mdf = MDF(version=version)
    try:
        start = sd.meta.get("start_unix")
        if start:
            mdf.header.start_time = datetime.datetime.fromtimestamp(float(start), tz=datetime.timezone.utc)
    except Exception:  # noqa: BLE001
        pass
    n = 0
    for sid in sel:
        if sid not in sd.values or not len(sd.values[sid]):
            continue
        t, v = sd.arrays(sid)
        info = sd.info(sid)
        comment = f"source={sd.source(sid)}; timebase={info.get('timebase', '')}"
        mdf.append(Signal(samples=v.copy(), timestamps=t.copy(), name=sid, unit=sd.unit(sid), comment=comment))
        n += 1
    if sd.events:
        mdf.append(Signal(samples=np.arange(1, len(sd.events) + 1, dtype=float),
                          timestamps=np.asarray([e[0] for e in sd.events], float), name="Olaylar",
                          comment="; ".join(f"{i + 1}={e[2]}:{e[3]}" for i, e in enumerate(sd.events))[:30000]))
    try:
        mdf.header.comment = json.dumps({k: sd.meta.get(k) for k in
                                         ("name", "user", "mode", "start_text", "dbc", "a2l", "simulink_model",
                                          "timebase", "connection")}, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 - başlık açıklaması eklenemese de veri yazılır
        pass
    mdf.save(path, overwrite=True)
    mdf.close()
    return n


def write_mat(path: str, sd: SessionData, signals: list | None = None):
    from scipy.io import savemat
    out, used = {}, set()
    for sid in (signals if signals is not None else sd.signals()):
        if sid not in sd.values:
            continue
        name = "".join(c if c.isalnum() else "_" for c in sid)
        if not name or not name[0].isalpha():
            name = "s_" + name
        base, k = name, 2
        while name in used:
            name, k = f"{base}_{k}", k + 1
        used.add(name)
        t, v = sd.arrays(sid)
        out[name] = {"time": t, "values": v, "unit": sd.unit(sid), "name": sid, "source": sd.source(sid)}
    out["events_time"] = np.asarray([e[0] for e in sd.events], float)
    out["events_label"] = np.asarray([f"{e[2]}: {e[3]}" for e in sd.events], dtype=object)
    savemat(path, out)


def write_csv(path: str, sd: SessionData):
    """Kayıt CSV'sinin kendisi (uzun biçim) kopyalanır."""
    shutil.copyfile(sd.path, path)


def write_asc(path: str, sd: SessionData) -> bool:
    """Ham CAN: kayıttaki ``.asc`` kopyalanır. Ham kare yoksa False (CAN'a bağlı olmadan/kare gelmeden kaydedilmiş)."""
    src = sd.asc_path()
    if src is None:
        return False
    shutil.copyfile(src, path)
    return True


def write_log(path: str, sd: SessionData, style: str = "asc") -> bool:
    """``.log``: style ``asc`` → ASC içeriği (uzantı farkı yalnızca ad); ``candump`` → can-utils ``candump -L``."""
    src = sd.asc_path()
    if src is None:
        return False
    if style == "asc":
        shutil.copyfile(src, path)
        return True
    import can
    w = can.CanutilsLogWriter(path, channel="can0")
    try:
        for msg in can.ASCReader(src):
            w.on_message_received(msg)
    finally:
        w.stop()
    return True


EXPORTERS = {"mf4": "MDF4 (.mf4) – fiziksel sinyaller", "asc": "ASC (.asc) – ham CAN",
             "log": "LOG (.log) – ASC içerikli", "candump": "LOG (.log) – candump biçimi",
             "csv": "CSV (.csv) – uzun biçim", "mat": "MAT (.mat) – MATLAB"}


def export(sd: SessionData, fmt: str, path: str) -> str:
    """Tek giriş noktası; yazılan dosya yolunu döner. Ham CAN yoksa ASC/LOG için ``ValueError``."""
    if fmt == "mf4":
        write_mdf4(path, sd)
    elif fmt == "mat":
        write_mat(path, sd)
    elif fmt == "csv":
        write_csv(path, sd)
    elif fmt == "asc":
        if not write_asc(path, sd):
            raise ValueError("Bu oturumda ham CAN karesi kaydı yok.")
    elif fmt in ("log", "candump"):
        if not write_log(path, sd, "asc" if fmt == "log" else "candump"):
            raise ValueError("Bu oturumda ham CAN karesi kaydı yok.")
    else:
        raise ValueError(f"Bilinmeyen biçim: {fmt}")
    return path
