"""Ana Sayfa (Dashboard) için, koddan bağımsız olarak KULLANICI tarafından
girilip diske (JSON) kaydedilen eşlemeler:

  - Motor Start / Motor Stop / Acil Stop (E-Stop) komutlarının hangi DBC
    mesajı/sinyaline, hangi değerle gönderileceği.
  - Motor Parametreleri panelindeki 8 gösterge (RPM, İtki, PLA, Tt5, FP,
    FT, Ps2, Tt2) ile Ortam Koşulları panelindeki 4 değerin A2L
    dosyasındaki hangi Measurement ismina karşılık geldiği.
  - Eyleyiciler panelindeki her bir manuel override kontrolünün (Yakıt
    Pompası Start/Fuel, Yakıt Debisi Valfi, Glow Plug, Başlatma Motoru)
    hangi DBC mesajı/"override enable" sinyali/"komut değeri" sinyaline
    karşılık geldiği.

Bu bilgiler projeye özel (kullanıcının kendi DBC/A2L dosyasına bağlı)
olduğu için kod içine gömülmek yerine burada, Ana Sayfa sekmesindeki
"Ayarlar" panelinden kullanıcı tarafından bir kere girilip kalıcı
tutulur — yeni bir kod değişikliği gerekmez.
"""

import json
import os

from app.persist import atomic_write_json, load_json
from dataclasses import asdict, dataclass, field

DEFAULT_PATH = "dashboard_config.json"

# Motor Parametreleri panelindeki 8 gösterge; sıra mockup'taki ile aynıdır:
# ilk 4'ü büyük/birincil (RPM, İtki, PLA, Tt5), son 4'ü küçük/ikincil
# (FP, FT, Ps2, Tt2).
GAUGE_KEYS = ["RPM", "İtki", "PLA", "Tt5", "FP", "FT", "Ps2", "Tt2"]

# Ortam Koşulları panelindeki 4 değer.
AMBIENT_KEYS = ["BataryaV", "OrtamBasinc", "AtmSicaklik", "Tt0"]

AMBIENT_LABELS = {
    "BataryaV": "Batarya Gerilimi",
    "OrtamBasinc": "Ortam Basıncı",
    "AtmSicaklik": "Atmosferik Sıcaklık",
    "Tt0": "Toplam Hava Basıncı/Tt0",
}
AMBIENT_UNITS = {
    "BataryaV": "V",
    "OrtamBasinc": "bar",
    "AtmSicaklik": "°C",
    "Tt0": "bar",
}

# Eyleyiciler panelindeki 5 manuel override kontrolü.
ACTUATOR_KEYS = ["pompa_start", "pompa_fuel", "valf", "glow_plug", "starter"]
ACTUATOR_LABELS = {
    "pompa_start": "Yakıt Pompası Start",
    "pompa_fuel": "Yakıt Pompası Fuel",
    "valf": "Yakıt Debisi Valfi",
    "glow_plug": "Glow Plug",
    "starter": "Başlatma Motoru",
}
# "toggle" -> açma/kapama anahtarı; "valve" -> 0-100 arası sayısal komut.
ACTUATOR_KINDS = {
    "pompa_start": "toggle",
    "pompa_fuel": "toggle",
    "valf": "valve",
    "glow_plug": "toggle",
    "starter": "toggle",
}

# Ortam Koşulları/Measurement eşleme alanlarının dataclass öznitelik adına
# çevrimi, DashboardConfig.measurement_map() içinde kullanılır.
_GAUGE_ATTR = {
    "RPM": "measurement_rpm",
    "İtki": "measurement_itki",
    "PLA": "measurement_pla",
    "Tt5": "measurement_tt5",
    "FP": "measurement_fp",
    "FT": "measurement_ft",
    "Ps2": "measurement_ps2",
    "Tt2": "measurement_tt2",
}
_AMBIENT_ATTR = {
    "BataryaV": "measurement_batarya",
    "OrtamBasinc": "measurement_ortam_basinc",
    "AtmSicaklik": "measurement_atm_sicaklik",
    "Tt0": "measurement_tt0",
}


DEFAULT_GRAPH_SIGNALS = ["g:RPM", "g:Tt5", "g:İtki"]


@dataclass
class MotorCommand:
    message: str = ""   # DBC mesaj ismi
    signal: str = ""    # DBC sinyal ismi
    value: float = 1.0  # gönderilecek sinyal değeri


@dataclass
class ActuatorCommand:
    """Bir eyleyici override kontrolünün DBC karşılığı. İki sinyal de AYNI
    mesaj içinde olabilir: biri 'override enable = 0/1' (dış MATLAB/
    Simulink modelindeki override anahtarını süren bit), diğeri de o an
    komut edilen değeri taşır (toggle'larda 0/1, valfte 0-100)."""
    message: str = ""
    enable_signal: str = ""
    value_signal: str = ""
    # Gönderim kanalı: "can" (DBC mesajı) veya "a2l" (CCP ile A2L adı yazımı).
    channel: str = "can"
    a2l_enable: str = ""   # A2L'de override-enable değişkeninin adı
    a2l_value: str = ""    # A2L'de komut değeri değişkeninin adı


@dataclass
class DashboardConfig:
    # A2L Measurement adları (kullanıcının gerçek A2L dosyasındaki isimler)
    measurement_itki: str = ""
    measurement_pla: str = ""
    measurement_tt2: str = ""
    measurement_tt5: str = ""
    measurement_fp: str = ""
    measurement_ft: str = ""
    measurement_rpm: str = ""
    measurement_ps2: str = ""

    measurement_batarya: str = ""
    measurement_ortam_basinc: str = ""
    measurement_atm_sicaklik: str = ""
    measurement_tt0: str = ""

    # Motor komutları (DBC'de zaten tanımlı mesaj/sinyaller)
    motor_start: MotorCommand = field(default_factory=MotorCommand)
    motor_stop: MotorCommand = field(default_factory=MotorCommand)
    estop: MotorCommand = field(default_factory=MotorCommand)

    # Eyleyici override komutları (bkz. ACTUATOR_KEYS)
    actuators: dict = field(default_factory=lambda: {k: ActuatorCommand() for k in ACTUATOR_KEYS})

    # Ana Sayfa > Canlı Grafik'te çizilen sinyaller (kullanıcı seçer, kalıcıdır).
    # Kimlikler: "g:<gösterge anahtarı>" (ör. "g:RPM") veya "m:<A2L ölçüm adı>".
    graph_signals: list = field(default_factory=lambda: list(DEFAULT_GRAPH_SIGNALS))

    def measurement_map(self) -> dict:
        """{tile_key: measurement_name} — boş olanlar dahil değildir.
        Hem gösterge (gauge) hem Ortam Koşulları anahtarlarını içerir."""
        pairs = {}
        for key, attr in {**_GAUGE_ATTR, **_AMBIENT_ATTR}.items():
            value = getattr(self, attr, "")
            if value and value.strip():
                pairs[key] = value.strip()
        return pairs

    def gauge_measurement_map(self) -> dict:
        return {k: getattr(self, attr) for k, attr in _GAUGE_ATTR.items() if getattr(self, attr, "").strip()}

    def ambient_measurement_map(self) -> dict:
        return {k: getattr(self, attr) for k, attr in _AMBIENT_ATTR.items() if getattr(self, attr, "").strip()}


class DashboardConfigStore:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path

    def load(self) -> DashboardConfig:
        raw = load_json(self.path, None, dict)
        if raw is None:
            return DashboardConfig()
        try:
            cfg = DashboardConfig()
            for k in ("measurement_itki", "measurement_pla", "measurement_tt2",
                      "measurement_tt5", "measurement_fp", "measurement_ft",
                      "measurement_rpm", "measurement_ps2",
                      "measurement_batarya", "measurement_ortam_basinc",
                      "measurement_atm_sicaklik", "measurement_tt0"):
                v = raw.get(k, "")
                setattr(cfg, k, v if isinstance(v, str) else "")
            for k in ("motor_start", "motor_stop", "estop"):
                sub = raw.get(k, {})
                sub = sub if isinstance(sub, dict) else {}
                try:
                    value = float(sub.get("value", 1.0))
                except (TypeError, ValueError):
                    value = 1.0
                setattr(cfg, k, MotorCommand(
                    message=str(sub.get("message", "")),
                    signal=str(sub.get("signal", "")),
                    value=value,
                ))
            actuators = {}
            raw_actuators = raw.get("actuators", {})
            raw_actuators = raw_actuators if isinstance(raw_actuators, dict) else {}
            for key in ACTUATOR_KEYS:
                sub = raw_actuators.get(key, {})
                sub = sub if isinstance(sub, dict) else {}
                actuators[key] = ActuatorCommand(
                    message=sub.get("message", ""),
                    enable_signal=sub.get("enable_signal", ""),
                    value_signal=sub.get("value_signal", ""),
                    channel="a2l" if sub.get("channel") == "a2l" else "can",
                    a2l_enable=sub.get("a2l_enable", ""),
                    a2l_value=sub.get("a2l_value", ""),
                )
            cfg.actuators = actuators
            sigs = raw.get("graph_signals")
            if isinstance(sigs, list):
                cfg.graph_signals = [s for s in sigs if isinstance(s, str) and s]
            return cfg
        except (ValueError, TypeError, AttributeError):
            return DashboardConfig()

    def save(self, cfg: DashboardConfig) -> bool:
        return atomic_write_json(self.path, asdict(cfg))
