"""Ana Sayfa (Dashboard) için, koddan bağımsız olarak KULLANICI tarafından
"Eşleşmeler" penceresinde girilip diske (JSON) kaydedilen eşleşmeler.

Her değişken (sensör değeri, eyleyici komutu, motor komutu...) bir
``Binding`` ile tanımlanır; kaynak iki türden biri olabilir:

  * ``can`` — DBC mesajı + sinyali (CAN hattından gönderilir / okunur)
  * ``a2l`` — A2L değişken adı (CCP ile yazılır / okunur)

Sensörler ve eyleyiciler için Simulink tarafında her değişkenin bir
"anahtar" (``<ad>_sw``) değişkeni vardır: anahtar 1 iken ``<ad>`` değeri
arayüzden değiştirilebilir, 0 iken değiştirilemez. Bu yüzden her sensör ve
her eyleyicinin ``value`` (değer) ve ``sw`` (anahtar) olmak üzere İKİ ayrı
eşleşmesi vardır; ikisinin kaynağı (CAN/A2L) birbirinden bağımsız seçilir.
"""


from app.persist import atomic_write_json, load_json
from dataclasses import asdict, dataclass, field

DEFAULT_PATH = "dashboard_config.json"

# Motor Parametreleri panelindeki 9 gösterge (= 9 sensör). Yakıt basıncı ikiye ayrıldı:
# FP_start = Başlangıç Yakıt Basıncı, FP_main = Ana Yakıt Basıncı (eski tek "FP" göstergesi kaldırıldı).
GAUGE_KEYS = ["RPM", "İtki", "PLA", "Tt5", "FP_start", "FP_main", "FT", "Ps2", "Ps3"]
# Motor Modu: göstergesi yoktur (başlıkta çip olarak görünür) ama sensör gibi CAN/A2L'den eşlenir.
MODE_KEY = "motor_mode"
# Alt modlar (Starter / Start / Run / Stop): Motor Modu gibi göstergesiz, CAN/A2L'den eşlenen sayısal durum slotları.
SUB_MODE_KEYS = ["starter_mode", "start_mode", "run_mode", "stop_mode"]
MODE_KEYS = [MODE_KEY] + SUB_MODE_KEYS
SENSOR_KEYS = GAUGE_KEYS + MODE_KEYS
# A2L'deki EN_MODE_*_u8 sabitleri (motor_mode değeri -> ekranda yazan ad).
MOTOR_MODE_NAMES = {0: "POWER ON", 1: "READY", 2: "START UP", 3: "IDLE", 4: "RUN", 5: "COOLING", 6: "STOP"}
# Alt mod değer -> ad tabloları (algoritmadaki *_u8 sabitlerinin gerçek değerleri).
# Gerçek sayılar farklıysa YALNIZCA buradan düzeltilir.
SUB_MODE_NAMES = {
    "starter_mode": {0: "OFF", 1: "ON", 2: "COOLDOWN"},
    "start_mode": {21: "MTRNG", 22: "IGN ON", 23: "F1 ON", 24: "LIGHTS UP", 25: "F1 BACKUP ON",
                   26: "SELF SUST N", 27: "SUCCESS", 28: "ABORT"},
    "run_mode": {41: "LOW", 42: "MID", 43: "INTERM", 44: "HIGH", 45: "MAX"},
    "stop_mode": {61: "CMD", 62: "TIMER"},
}
SUB_MODE_TITLES = {"starter_mode": "STARTER", "start_mode": "START", "run_mode": "RUN", "stop_mode": "STOP"}
# Ana mod (MOTOR_MODE_NAMES değeri) -> o anda "etkin" sayılan alt modlar (Ana Sayfa'da vurgulanır).
ACTIVE_SUB_MODES = {2: ("starter_mode", "start_mode"), 4: ("run_mode",), 5: ("starter_mode",), 6: ("stop_mode",)}


def mode_name(key: str, value) -> str:
    """Mod sayısını ad olarak döndürür: bilinmeyen -> 'BİLİNMİYOR (n)', değer yok -> '—'."""
    try:
        n = float(value)
    except (TypeError, ValueError):
        return "—"
    if n != n or n != int(n):
        return "—"
    n = int(n)
    names = MOTOR_MODE_NAMES if key == MODE_KEY else SUB_MODE_NAMES.get(key, {})
    return names.get(n, f"BİLİNMİYOR ({n})")


def motor_mode_name(value) -> str:
    return mode_name(MODE_KEY, value)

SENSOR_LABELS = {
    "RPM": "Devir (RPM)", "İtki": "İtki", "PLA": "Gaz Kolu (PLA)", "Tt5": "Egzoz Sıcaklığı (Tt5)",
    "FP_start": "Başlangıç Yakıt Basıncı (FPs)", "FP_main": "Ana Yakıt Basıncı (FPm)",
    "FT": "Yakıt Sıcaklığı (FT)", "Ps2": "Giriş Basıncı (Ps2)",
    "Ps3": "Basınç (Ps3)",
    "motor_mode": "Motor Modu",
    "starter_mode": "Starter Modu", "start_mode": "Start Modu", "run_mode": "Run Modu", "stop_mode": "Stop Modu",
}

# Eyleyiciler (manuel override).
EYLEYICI_KEYS = ["pompa_start", "pompa_fuel", "valf", "glow_plug", "starter"]
# Motor Kontrol (Çalıştırma, Gaz Kolu): CAN (DBC) ya da A2L, kilitsiz DEĞER kutusu (değer + Enter ile direkt komut, rol gerekir). ANAHTAR (_sw)
# YOKTUR: switch (_sw) yalnızca Eyleyicilerdedir (kilitlenince değer 0'a çekilir). Ateşleme ve Birincil Yakıt
# kaldırıldı (zaten Eyleyicilerde var).
CONTROL_KEYS = ["start", "throttle"]
# _sw (anahtar) eşlemesi olan TEK grup: Eyleyiciler. Sensörlerde ve Motor Kontrol'de switch yoktur.
SWITCH_KEYS = EYLEYICI_KEYS
# Manuel-override (kilitli) davranışı olan TÜM satırlar.
ACTUATOR_KEYS = EYLEYICI_KEYS + CONTROL_KEYS
ACTUATOR_LABELS = {
    "pompa_start": "Yakıt Pompası Start",
    "pompa_fuel": "Yakıt Pompası Fuel",
    "valf": "Yakıt Debisi Valfi",
    "glow_plug": "Glow Plug",
    "starter": "Başlatma Motoru",
    "start": "Çalıştırma (Start)",
    "throttle": "Gaz Kolu (PLA)",
}
# "valve" -> sayısal değer kutusu (Eyleyicilerde kilit açılınca _sw=1 yazılır). Ana Sayfa'da ON/OFF anahtarı
# (toggle) YOKTUR: tüm satırlar değer kutusudur.
ACTUATOR_KINDS = {
    "pompa_start": "valve",
    "pompa_fuel": "valve",
    "valf": "valve",
    "glow_plug": "valve",
    "starter": "valve",
    "start": "valve",
    "throttle": "valve",
}

MOTOR_COMMAND_KEYS = ["motor_start", "motor_stop", "estop"]
MOTOR_COMMAND_LABELS = {
    "motor_start": "Motoru Başlat",
    "motor_stop": "Motoru Durdur",
    "estop": "Acil Durdurma",
}


SOURCE_CAN = "can"
SOURCE_A2L = "a2l"


@dataclass
class Binding:
    """Tek bir değişkenin kaynağı: CAN (DBC mesaj+sinyal) veya A2L adı."""
    source: str = SOURCE_CAN
    message: str = ""     # DBC mesaj adı (source == "can")
    signal: str = ""      # DBC sinyal adı (source == "can")
    a2l_name: str = ""    # A2L değişken adı (source == "a2l")

    @property
    def is_set(self) -> bool:
        if self.source == SOURCE_A2L:
            return bool(self.a2l_name.strip())
        return bool(self.message.strip() and self.signal.strip())

    @property
    def text(self) -> str:
        if not self.is_set:
            return ""
        return self.a2l_name if self.source == SOURCE_A2L else f"{self.message}.{self.signal}"


@dataclass
class SignalMap:
    """Bir sensör/eyleyici için değer + anahtar (+ sensörlerde arıza) eşleşmesi."""
    value: Binding = field(default_factory=Binding)
    sw: Binding = field(default_factory=Binding)
    fault: Binding = field(default_factory=Binding)   # yalnız sensörler: ≠0 ise arıza


# Motor komutları (Başlat / Durdur / Acil Durdurma) basılınca bu sabit değeri eşlenen sinyale/değişkene yazar.
COMMAND_VALUE = 1.0


@dataclass
class MotorCommand:
    """Motor Başlat/Durdur/Acil Durdurma: yalnızca CAN sinyali ya da A2L değişkeni eşlenir. Düğmeye basınca
    ``COMMAND_VALUE`` (1) doğrudan yazılır; Değer ve Switch (_sw) YOKTUR. (``value``/``sw`` alanları yalnızca eski
    kayıtların okunması içindir: yüklerken ve kaydederken temizlenir, çalışma mantığında kullanılmaz.)"""
    binding: Binding = field(default_factory=Binding)
    value: float = COMMAND_VALUE
    sw: Binding = field(default_factory=Binding)


def strip_unused_switches(cfg: "DashboardConfig") -> "DashboardConfig":
    """Switch (_sw) yalnızca Eyleyicilerde kullanılır: sensör ve Motor Kontrol satırlarının eski kayıtlardan gelen
    anahtar eşlemeleri temizlenir (arayüzde de çalışma mantığında da yoktur)."""
    for smap in cfg.sensors.values():
        smap.sw = Binding()
    for key in CONTROL_KEYS:
        if key in cfg.actuators:
            cfg.actuators[key].sw = Binding()
    for key in MOTOR_COMMAND_KEYS:                    # komutlarda Değer ve Switch yok: sabit 1, anahtarsız
        cmd = getattr(cfg, key)
        cmd.value, cmd.sw = COMMAND_VALUE, Binding()
    return cfg


def _default_sensors() -> dict:
    return {k: SignalMap() for k in SENSOR_KEYS}


def _default_actuators() -> dict:
    return {k: SignalMap() for k in ACTUATOR_KEYS}


@dataclass
class DashboardConfig:
    sensors: dict = field(default_factory=_default_sensors)
    actuators: dict = field(default_factory=_default_actuators)
    motor_start: MotorCommand = field(default_factory=MotorCommand)
    motor_stop: MotorCommand = field(default_factory=MotorCommand)
    estop: MotorCommand = field(default_factory=MotorCommand)

    # Canlı Trendler'de çizilen sinyaller (kalıcı). Kimlikler:
    # "g:<gösterge anahtarı>" (ör. "g:RPM") veya "m:<A2L ölçüm adı>".

    # ---- sorgular ---------------------------------------------------------
    def sensor_map(self, key: str) -> SignalMap:
        return self.sensors.setdefault(key, SignalMap())

    def actuator_map(self, key: str) -> SignalMap:
        return self.actuators.setdefault(key, SignalMap())

    def gauge_a2l_map(self) -> dict:
        """{gösterge: A2L adı} — değeri A2L'den (CCP) okunacak sensörler."""
        return {k: m.value.a2l_name.strip() for k, m in self.sensors.items()
                if m.value.source == SOURCE_A2L and m.value.a2l_name.strip()}

    def gauge_can_map(self) -> dict:
        """{gösterge: (mesaj, sinyal)} — değeri CAN'dan (DBC) okunacak sensörler."""
        return {k: (m.value.message.strip(), m.value.signal.strip()) for k, m in self.sensors.items()
                if m.value.source == SOURCE_CAN and m.value.is_set}

    def unbound_gauges(self) -> list:
        return [k for k in GAUGE_KEYS if not self.sensor_map(k).value.is_set]

    def measurement_map(self) -> dict:
        """Eski ad: {gösterge: A2L adı}."""
        return self.gauge_a2l_map()


# ---------------------------------------------------------------------------
# Kalıcılık
# ---------------------------------------------------------------------------
def _binding_from(raw) -> Binding:
    if not isinstance(raw, dict):
        return Binding()
    return Binding(
        source=SOURCE_A2L if raw.get("source") == SOURCE_A2L else SOURCE_CAN,
        message=str(raw.get("message", "") or ""),
        signal=str(raw.get("signal", "") or ""),
        a2l_name=str(raw.get("a2l_name", "") or ""),
    )


def _signalmap_from(raw) -> SignalMap:
    raw = raw if isinstance(raw, dict) else {}
    return SignalMap(value=_binding_from(raw.get("value")), sw=_binding_from(raw.get("sw")),
                     fault=_binding_from(raw.get("fault")))


def _float(v, default=1.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# Eski sürüm (measurement_* alanları) -> yeni sensör anahtarı. Eski tek "FP" (measurement_fp) iki yeni yakıt
# basıncı göstergesinden hiçbirine taşınmaz: ikisi de boş başlar.
_LEGACY_GAUGE_ATTR = {
    "RPM": "measurement_rpm", "İtki": "measurement_itki", "PLA": "measurement_pla",
    "Tt5": "measurement_tt5", "FT": "measurement_ft",
    "Ps2": "measurement_ps2", "Ps3": "measurement_ps3",
}


def config_from_dict(raw: dict) -> DashboardConfig:
    """JSON sözlüğünden yapılandırma kurar; eski biçimi (measurement_*,
    ActuatorCommand.message/enable_signal/value_signal/channel) otomatik göç ettirir."""
    cfg = DashboardConfig()
    if not isinstance(raw, dict):
        return cfg

    # --- sensörler
    sensors = raw.get("sensors")
    if isinstance(sensors, dict):
        for key in SENSOR_KEYS:
            cfg.sensors[key] = _signalmap_from(sensors.get(key))
    else:  # eski biçim
        for key, attr in _LEGACY_GAUGE_ATTR.items():
            name = str(raw.get(attr, "") or "").strip()
            if name:
                cfg.sensors[key] = SignalMap(value=Binding(SOURCE_A2L, a2l_name=name))

    # --- eyleyiciler
    actuators = raw.get("actuators", {})
    for key in ACTUATOR_KEYS:
        sub = actuators.get(key, {}) if isinstance(actuators, dict) else {}
        if isinstance(sub, dict) and ("value" in sub or "sw" in sub):
            cfg.actuators[key] = _signalmap_from(sub)
        elif isinstance(sub, dict):  # eski biçim
            if sub.get("channel") == "a2l":
                cfg.actuators[key] = SignalMap(
                    value=Binding(SOURCE_A2L, a2l_name=str(sub.get("a2l_value", "") or "")),
                    sw=Binding(SOURCE_A2L, a2l_name=str(sub.get("a2l_enable", "") or "")))
            else:
                msg = str(sub.get("message", "") or "")
                cfg.actuators[key] = SignalMap(
                    value=Binding(SOURCE_CAN, msg, str(sub.get("value_signal", "") or "")),
                    sw=Binding(SOURCE_CAN, msg, str(sub.get("enable_signal", "") or "")))

    # --- motor komutları
    for key in MOTOR_COMMAND_KEYS:
        sub = raw.get(key, {})
        if not isinstance(sub, dict):
            continue
        if "binding" in sub:
            cfg_cmd = MotorCommand(binding=_binding_from(sub.get("binding")), value=_float(sub.get("value")),
                                   sw=_binding_from(sub.get("sw")))
        else:  # eski biçim: yalnız DBC
            cfg_cmd = MotorCommand(
                binding=Binding(SOURCE_CAN, str(sub.get("message", "") or ""), str(sub.get("signal", "") or "")),
                value=_float(sub.get("value")))
        setattr(cfg, key, cfg_cmd)

    return strip_unused_switches(cfg)


class DashboardConfigStore:
    def __init__(self, path: str = DEFAULT_PATH):
        self.path = path

    def load(self) -> DashboardConfig:
        raw = load_json(self.path, None, dict)
        if raw is None:
            return DashboardConfig()
        try:
            return config_from_dict(raw)
        except (ValueError, TypeError, AttributeError):
            return DashboardConfig()

    def save(self, cfg: DashboardConfig) -> bool:
        return atomic_write_json(self.path, asdict(strip_unused_switches(cfg)))
