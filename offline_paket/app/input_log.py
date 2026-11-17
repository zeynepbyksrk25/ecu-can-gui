"""Kullanıcının TÜM sayfalarda yaptığı girişlerin/değişikliklerin yapılandırılmış kaydı.

Ana Sayfa (eyleyici, motor komutu, uçuş koşulu), Kontrol Paneli, Kalibrasyon (Parametre Listesi, Harita Editörü,
CCP, geçmişten geri alma) hangi sayfada olursa olsun her giriş buraya bir satır olarak eklenir: ne zaman, hangi sayfa,
hangi hedef (CAN sinyali / A2L adı), eski ve yeni değer, başarılı mı, kim/hangi rol. Excel raporunun "Girişler (tüm
sayfalar)" sayfası bu kayıttan üretilir.

Bellekte tutulur (sınırlı). Bir oturum açıkken ayrıca satır satır bir CSV dosyasına da yazılır (program çökse bile
oturumun girişleri kaybolmasın).
"""
from __future__ import annotations

import csv
import logging
import os
import threading
import time
from dataclasses import dataclass

log = logging.getLogger(__name__)

MAX_ENTRIES = 50_000
HEADER = ["tarih_saat", "sayfa", "tur", "kaynak", "hedef", "eski_deger", "yeni_deger", "birim", "sonuc",
          "kullanici", "rol", "aciklama"]
_AUTO = object()


@dataclass
class InputEntry:
    timestamp: float
    page: str            # "Ana Sayfa", "Kontrol Paneli", "Kalibrasyon > Parametre Listesi" ...
    kind: str            # "Değer girişi", "Switch (_sw)", "Motor komutu", "Uçuş koşulu", "RAM yazımı" ...
    source: str          # "CAN" | "A2L" | "CCP"
    target: str          # "MESAJ.SİNYAL" ya da A2L adı
    old_value: object
    new_value: object
    unit: str = ""
    ok: bool = True
    user: str = "-"
    role: str = "-"
    detail: str = ""


class InputLog:
    def __init__(self, max_entries: int = MAX_ENTRIES):
        self.entries: list[InputEntry] = []
        self._max = max_entries
        self._last: dict[tuple, object] = {}        # (kaynak, hedef) -> son BAŞARILI yeni değer
        self._lock = threading.Lock()
        self._file = None
        self._writer = None
        self.file_path: str | None = None
        self.file_error: str | None = None

    def add(self, page: str, kind: str, source: str, target: str, new_value, *, old_value=_AUTO, unit: str = "",
            ok: bool = True, user: str = "-", role: str = "-", detail: str = "",
            timestamp: float | None = None) -> InputEntry:
        """Bir giriş ekler. ``old_value`` verilmezse aynı hedefe daha önce GİRİLEN son başarılı değer kullanılır
        (bilinmiyorsa boş)."""
        with self._lock:
            key = (source, target)
            if old_value is _AUTO:
                old_value = self._last.get(key)
            e = InputEntry(timestamp if timestamp is not None else time.time(), page, kind, source, target,
                           old_value, new_value, unit or "", bool(ok), user, role, str(detail or ""))
            self.entries.append(e)
            if len(self.entries) > self._max:
                del self.entries[:len(self.entries) - self._max]
            if ok:
                self._last[key] = new_value
            self._write_row(e)
        return e

    # ---- oturum CSV'si
    def start_file(self, path: str):
        self.stop_file()
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._file = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(HEADER)
            self._file.flush()
            self.file_path, self.file_error = path, None
        except OSError as exc:
            self._file = self._writer = None
            self.file_error = str(exc)
            log.error("Giriş kaydı dosyası açılamadı (%s): %s", path, exc)

    def stop_file(self):
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
            self._file = self._writer = None

    def _write_row(self, e: InputEntry):
        if self._writer is None:
            return
        try:
            self._writer.writerow([
                time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp)) + f".{int((e.timestamp % 1) * 1000):03d}",
                e.page, e.kind, e.source, e.target,
                "" if e.old_value is None else e.old_value, "" if e.new_value is None else e.new_value,
                e.unit, "BAŞARILI" if e.ok else "BAŞARISIZ", e.user, e.role, e.detail])
            self._file.flush()                       # düşük hızlı (kullanıcı girişleri): her satır diske
        except OSError as exc:
            self.file_error = str(exc)
            log.error("Giriş kaydı yazılamadı: %s", exc)
            self._file = self._writer = None

    def since(self, start: float | None) -> list[InputEntry]:
        with self._lock:
            return [e for e in self.entries if start is None or e.timestamp >= start]
