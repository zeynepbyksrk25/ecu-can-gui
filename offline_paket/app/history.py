"""Kalibrasyon revizyon geçmişi (SRS Faz 5, genişletilmiş): her CCP
Characteristic yazımının (RAM VEYA FLAŞ) eski/yeni değerini, kullanıcı/
rol ve zaman bilgisiyle tutar. Harita (grid) geri alma zaten Harita
Editörü'ndeki Geri Al/Yinele ile yapıldığından, burası tekil CCP
Characteristic yazımlarına odaklanır.

Flaş (kalıcı) yazımlar uygulama kapansa/yeniden başlasa bile geri
alınabilir olmalı ("kalıcı flaşa kaydedildikten sonra bile eski haline
getirebilmek" isteği) — bu yüzden, RAM'den farklı olarak, bu geçmiş
isteğe bağlı olarak diske (JSON) kalıcı yazılır ve açılışta geri okunur.
"""

import json
import os
import time
from dataclasses import asdict, dataclass


@dataclass
class HistoryEntry:
    timestamp: float
    user: str
    role: str
    object_name: str
    old_value: float | None
    new_value: float
    unit: str
    persistent: bool = False  # True ise bu bir FLAŞ (kalıcı) yazımdı, RAM değil
    detail: str = ""  # tablo/dizi yazımı gibi toplu işlemlerin açıklaması (geri alınamaz)


MAX_ENTRIES = 5000  # disk dosyasının sınırsız büyümesini engeller (en eskiler silinir)


class CalibrationHistory:
    def __init__(self, file_path: str | None = None):
        self.file_path = file_path
        self.entries: list[HistoryEntry] = []
        if self.file_path and os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                fields = set(HistoryEntry.__dataclass_fields__)
                self.entries = [HistoryEntry(**{k: v for k, v in e.items() if k in fields})
                                for e in raw][-MAX_ENTRIES:]
            except (OSError, ValueError, TypeError):
                self.entries = []  # bozuk/okunamayan dosya sessizce yok sayılır

    def add(self, user: str, role: str, object_name: str,
            old_value: float | None, new_value: float, unit: str,
            persistent: bool = False, detail: str = ""):
        self.entries.append(HistoryEntry(
            timestamp=time.time(), user=user, role=role, object_name=object_name,
            old_value=old_value, new_value=new_value, unit=unit, persistent=persistent, detail=detail,
        ))
        if len(self.entries) > MAX_ENTRIES:
            del self.entries[:len(self.entries) - MAX_ENTRIES]
        self._save()

    def _save(self):
        if not self.file_path:
            return
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump([asdict(e) for e in self.entries], f, ensure_ascii=False, indent=2)
        except OSError:
            pass  # diske kalıcı yazma başarısız olsa da uygulama içi geçmiş çalışmaya devam eder

    def export_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.entries], f, ensure_ascii=False, indent=2)
