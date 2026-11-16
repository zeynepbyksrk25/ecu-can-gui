"""Test oturumu boyunca izlenen parametrelerin (A2L/CCP, DBC, gösterge, giriş) değerlerini
sürekli bir CSV dosyasına yazan modül.

Amaç: oturum bittikten (hatta program kapandıktan/çöktükten) sonra değerleri inceleyebilmek.
Bellekteki grafik geçmişi sınırlıdır ve program kapanınca kaybolur; bu kayıt diske yazılır.

Biçim ("uzun" CSV; Çalışma Alanı > "CSV aç" ile geri yüklenip grafikte çizilebilir):
    time,signal,value,unix_time
    time      : oturum başlangıcından itibaren saniye
    signal    : sinyal kimliği (a2l:<ölçüm>, dbc:<MESAJ>.<SİNYAL>, gauge:<anahtar>, input:<anahtar>)
    value     : fiziksel değer
    unix_time : mutlak zaman (epoch saniye)
Dosya yolu: <veri klasörü>/oturum_kayitlari/<oturum_adı>_<tarih_saat>.csv
"""
from __future__ import annotations

import csv
import datetime
import re
import threading
import time
from pathlib import Path

HEADER = ["time", "signal", "value", "unix_time"]
FLUSH_EVERY_S = 1.0          # çökmede en çok bu kadar saniyelik veri kaybolur
DEDUP_S = 0.05               # aynı sinyalin aynı değeri bu süre içinde iki kaynaktan gelirse tek yazılır


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", (name or "").strip(), flags=re.UNICODE).strip("_")
    return name[:40] or "oturum"


class SessionRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._file = None
        self._writer = None
        self._t0 = 0.0
        self._last_flush = 0.0
        self._last: dict[str, tuple[float, float]] = {}
        self.path: str | None = None
        self.rows = 0
        self.error: str | None = None      # yazma hatası olduysa mesaj (kayıt durdurulur)

    @property
    def is_active(self) -> bool:
        return self._file is not None

    def start(self, directory: str, session_name: str = "") -> str:
        self.stop()
        directory = (directory or "").strip()
        if not directory:
            raise OSError("Kayıt klasörü boş.")
        Path(directory).mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{_safe_name(session_name)}_{stamp}"
        path = Path(directory) / f"{base}.csv"
        n = 1
        while path.exists():                 # aynı saniyede başlatılsa da üzerine yazma
            path = Path(directory) / f"{base}_{n}.csv"
            n += 1
        with self._lock:
            self._file = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(HEADER)
            self._file.flush()
            self._t0 = time.time()
            self._last_flush = self._t0
            self._last = {}
            self.rows = 0
            self.error = None
            self.path = str(path)
        return self.path

    def record(self, sid: str, value, t_unix: float | None = None):
        """Bir örnek yazar. Kayıt açık değilse ya da değer sayısal değilse sessizce yok sayılır."""
        if self._writer is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if v != v:                           # NaN
            return
        now = time.time() if t_unix is None else t_unix
        with self._lock:
            if self._writer is None:
                return
            prev = self._last.get(sid)
            if prev is not None and prev[1] == v and now - prev[0] < DEDUP_S:
                return
            self._last[sid] = (now, v)
            try:
                self._writer.writerow([f"{now - self._t0:.4f}", sid, f"{v:.9g}", f"{now:.3f}"])
                self.rows += 1
                if now - self._last_flush >= FLUSH_EVERY_S:
                    self._file.flush()
                    self._last_flush = now
            except OSError as exc:           # disk dolu / sürücü çıkarıldı
                self.error = str(exc)
                self._close_locked()

    def stop(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError as exc:
                self.error = self.error or str(exc)
        self._file = None
        self._writer = None
