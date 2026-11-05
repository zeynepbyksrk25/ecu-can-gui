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
from app.persist import atomic_write_json, load_json
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
        self.save_failed = False
        if self.file_path:
            raw = load_json(self.file_path, [], list)
            fields = set(HistoryEntry.__dataclass_fields__)
            required = {"timestamp", "user", "role", "object_name", "new_value", "unit", "old_value"}
            entries = []
            for e in raw:           # tek bozuk kayıt tüm geçmişi düşürmesin
                try:
                    d = {k: v for k, v in e.items() if k in fields}
                    if required <= set(d):
                        entries.append(HistoryEntry(**d))
                except (AttributeError, TypeError):
                    continue
            self.entries = entries[-MAX_ENTRIES:]

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
        # Atomik yazma; başarısızlık görünür (save_failed) ve loglanır.
        self.save_failed = not atomic_write_json(self.file_path, [asdict(e) for e in self.entries])

    def export_json(self, path: str):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([asdict(e) for e in self.entries], f, ensure_ascii=False, indent=2)
