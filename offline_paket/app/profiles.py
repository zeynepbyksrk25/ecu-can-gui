"""Konfigürasyon profilleri (SRS Faz 5): bağlantı (arayüz/kanal/baudrate),
CCP (CRO/DTO/istasyon adresi) ve A2L dosya yolu bir arada, isimli bir
profil olarak kaydedilip diskte (JSON) saklanır, sonra tek tıkla tekrar
uygulanabilir.
"""

import json
import os
from dataclasses import asdict, dataclass


@dataclass
class ConfigProfile:
    name: str
    interface: str = "pcan"
    channel: str = "PCAN_USBBUS1"
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
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.profiles = [ConfigProfile(**p) for p in data]
        except (OSError, ValueError, TypeError):
            self.profiles = []

    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([asdict(p) for p in self.profiles], f, ensure_ascii=False, indent=2)

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
