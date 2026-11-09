"""Test oturumu / denetim (audit) olay günlüğü. Uygulama genelinde önemli
olayları (bağlantı, CCP, kalibrasyon yazma, hata) zaman damgası VE
kullanıcı/rol bilgisiyle tutar (SRS Faz 4 Test Session Management + Faz 5
Audit/Event Log). İstenirse her olay aynı anda diske de (kalıcı denetim
kaydı) yazılır — uygulama kapansa/çökse bile geçmiş kaybolmaz.
"""

import csv
import logging
import os
import time
from dataclasses import dataclass


@dataclass
class EventEntry:
    timestamp: float
    category: str    # "BAGLANTI" | "CCP" | "KALIBRASYON" | "OTURUM" | "KULLANICI" | "HATA" ...
    message: str
    user: str = "-"
    role: str = "-"


log = logging.getLogger(__name__)
MAX_MEMORY_ENTRIES = 20000
MAX_LOG_BYTES = 5 * 1024 * 1024  # bu boyut aşılınca dosya .1 olarak yedeklenir (tek yedek)


class EventLog:
    def __init__(self, file_path: str | None = None):
        self.entries: list[EventEntry] = []
        self.file_path = file_path
        self.write_failures = 0          # kalıcı yazma hataları (görünür: arayüz uyarabilir)
        self.last_write_error: str | None = None
        if self.file_path:
            directory = os.path.dirname(self.file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

    @staticmethod
    def _clean(text) -> str:
        """Satır/sekme taklidini (sahte kayıt) engeller: denetim satırı tek satır kalır."""
        return str(text).replace("\r", "\\r").replace("\n", "\\n").replace("\t", " ")

    def add(self, category: str, message: str, user: str = "-", role: str = "-"):
        category, message, user, role = (self._clean(x) for x in (category, message, user, role))
        entry = EventEntry(timestamp=time.time(), category=category, message=message, user=user, role=role)
        self.entries.append(entry)
        if len(self.entries) > MAX_MEMORY_ENTRIES:
            del self.entries[:len(self.entries) - MAX_MEMORY_ENTRIES]    # bellek sınırsız büyümesin
        if self.file_path:
            try:
                if os.path.exists(self.file_path) and os.path.getsize(self.file_path) > MAX_LOG_BYTES:
                    os.replace(self.file_path, self.file_path + ".1")  # eski yedek üzerine yazılır
                with open(self.file_path, "a", encoding="utf-8") as f:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.timestamp))
                    f.write(f"{ts}\t{category}\t{user}\t{role}\t{message}\n")
            except OSError as exc:
                # Uygulama içi günlük çalışmaya devam eder ama kayıp SESSİZ olmaz.
                self.write_failures += 1
                self.last_write_error = str(exc)
                log.error("Denetim günlüğü yazılamadı (%s): %s", self.file_path, exc)

    # Denetim günlüğü arayüzden SİLİNEMEZ (bilinçli): bellekteki liste oturum PDF raporunun kaynağıdır ve
    # diskteki audit_log.txt yalnızca eklemeli (append-only) tutulur. Bu yüzden clear() yoktur.

    def export_csv(self, path: str):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["zaman", "kategori", "kullanici", "rol", "mesaj"])
            for e in self.entries:
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp)),
                    e.category, e.user, e.role, e.message,
                ])
