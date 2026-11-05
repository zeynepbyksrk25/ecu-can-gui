"""Konfigürasyon profilleri (SRS Faz 5): bağlantı (arayüz/kanal/baudrate),
CCP (CRO/DTO/istasyon adresi) ve A2L dosya yolu bir arada, isimli bir
profil olarak kaydedilip diskte (JSON) saklanır, sonra tek tıkla tekrar
uygulanabilir.
"""

import json
import os
from dataclasses import asdict, dataclass

from app.persist import atomic_write_json, load_json


@dataclass
class ConfigProfile:
    name: str
    interface: str = "virtual"
    channel: str = "test"
    bitrate: int = 500_000
    cro_id: str = "6F9"
    dto_id: str = "6F8"
    station_address: str = "0000"
    a2l_path: str = ""


class ProfileStore:
    def __init__(self, path: str = "profiles.json"):
        self.path = path
        self.profiles: list[ConfigProfile] = []
        self.load()

    def load(self):
        self.profiles = []
        data = load_json(self.path, [], list)
        fields = set(ConfigProfile.__dataclass_fields__)
        for p in data:              # bilinmeyen anahtar/bozuk tek profil diğerlerini düşürmesin
            try:
                self.profiles.append(ConfigProfile(**{k: v for k, v in p.items() if k in fields}))
            except (AttributeError, TypeError):
                continue

    def save(self):
        if not atomic_write_json(self.path, [asdict(p) for p in self.profiles]):
            raise OSError(f"Profil dosyası yazılamadı: {self.path}")

    def upsert(self, profile: ConfigProfile):
        self.profiles = [p for p in self.profiles if p.name != profile.name]
        self.profiles.append(profile)
        self.save()

    def delete(self, name: str):
        self.profiles = [p for p in self.profiles if p.name != name]
        self.save()

    def get(self, name: str) -> ConfigProfile | None:
        for p in self.profiles:
            if p.name == name:
                return p
        return None

    def names(self) -> list:
        return [p.name for p in self.profiles]
