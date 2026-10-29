"""Test oturumu / denetim (audit) olay günlüğü. Uygulama genelinde önemli
olayları (bağlantı, CCP, kalibrasyon yazma, hata) zaman damgası VE
kullanıcı/rol bilgisiyle tutar (SRS Faz 4 Test Session Management + Faz 5
Audit/Event Log). İstenirse her olay aynı anda diske de (kalıcı denetim
kaydı) yazılır — uygulama kapansa/çökse bile geçmiş kaybolmaz.
"""

import csv
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


MAX_LOG_BYTES = 5 * 1024 * 1024  # bu boyut aşılınca dosya .1 olarak yedeklenir (tek yedek)


class EventLog:
    def __init__(self, file_path: str | None = None):
        self.entries: list[EventEntry] = []
        self.file_path = file_path
        if self.file_path:
            directory = os.path.dirname(self.file_path)
            if directory:
                os.makedirs(directory, exist_ok=True)

    def add(self, category: str, message: str, user: str = "-", role: str = "-"):
        entry = EventEntry(timestamp=time.time(), category=category, message=message, user=user, role=role)
        self.entries.append(entry)
        if self.file_path:
            try:
                if os.path.exists(self.file_path) and os.path.getsize(self.file_path) > MAX_LOG_BYTES:
                    os.replace(self.file_path, self.file_path + ".1")  # eski yedek üzerine yazılır
                with open(self.file_path, "a", encoding="utf-8") as f:
                    ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.timestamp))
                    f.write(f"{ts}\t{category}\t{user}\t{role}\t{message}\n")
            except OSError:
                pass  # kalıcı kayıt başarısız olsa da uygulama içi günlük çalışmaya devam eder

    def clear(self):
        self.entries.clear()

    def export_csv(self, path: str):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["zaman", "kategori", "kullanici", "rol", "mesaj"])
            for e in self.entries:
                writer.writerow([
                    time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.timestamp)),
                    e.category, e.user, e.role, e.message,
                ])
