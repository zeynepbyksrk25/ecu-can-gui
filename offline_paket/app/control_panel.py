"""Kontrol Paneli mantık katmanı (arayüzden bağımsız, test edilebilir).

Tek doğru kaynak DBC ve A2L dosyalarıdır; kullanıcı ayrıca sinyal listesi /
CSV / eşleme hazırlamaz. Bu modül:

  * build_catalog(): DBC + A2L'den "sinyal kataloğu" çıkarır ve her sinyali
    sınıflandırır:
        AIRCRAFT_IN : DBC'de GÖNDERENİ giriş düğümü olan (uçak/arayüz) mesajların
                      sinyalleri -> arayüz tarafından periyodik gönderilir.
        SENSOR_OVR  : A2L'de <İsim>_Ovr_Val + <İsim>_Ovr_En çiftleri -> CCP ile
                      yazılır (takılı olmayan sensörün yerine geçer).
        OUTPUT      : ECU'nun gönderdiği DBC sinyalleri ve A2L measurement'ları.
        INTERNAL    : kullanıcının "iç sinyal" olarak işaretlediği measurement'lar.
  * diff_catalogs(): dosya değişince yeni/değişen/silinen sinyalleri bulur.
  * TxScheduler: DBC mesajlarını periyodik gönderir (aynı mesajdaki sinyaller
    TEK karede).
  * ControlPanelConfig: çalışma listesi, görünümler, senaryolar, sınıflama
    düzeltmeleri (JSON, isme göre -> dosyalar değişse de korunur).
  * ccp_read_value / ccp_write_value: A2L bilgisinden CCP okuma/yazma.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, Signal

from app.ccp import codec as ccp_codec
from app.persist import atomic_write_json, load_json

log = logging.getLogger(__name__)

ROLE_AIRCRAFT_IN = "AIRCRAFT_IN"
ROLE_SENSOR_OVR = "SENSOR_OVR"
ROLE_OUTPUT = "OUTPUT"
ROLE_INTERNAL = "INTERNAL"
ALL_ROLES = (ROLE_AIRCRAFT_IN, ROLE_SENSOR_OVR, ROLE_OUTPUT, ROLE_INTERNAL)

ROLE_TITLES = {
    ROLE_AIRCRAFT_IN: "UÇAK GİRİŞLERİ",
    ROLE_SENSOR_OVR: "SENSÖR GİRİŞLERİ",
    ROLE_OUTPUT: "ÇIKIŞLAR",
    ROLE_INTERNAL: "İÇ SİNYALLER",
}

# DBC'de bu isimleri (büyük/küçük harf fark etmez, parça eşleşmesi) taşıyan
# düğümler "giriş gönderen" (uçak/arayüz) sayılır. Panelden değiştirilebilir.
DEFAULT_INPUT_NODES = ("AIRCRAFT", "UCAK", "UÇAK", "AC", "TESTER", "TOOL", "HOST",
                       "ARAYUZ", "ARAYÜZ", "GUI", "SIM", "HIL", "PC", "DASH")
OVR_VAL_SUFFIX = "_Ovr_Val"
OVR_EN_SUFFIX = "_Ovr_En"
DEFAULT_CYCLE_MS = 100
_FAULT_RE = re.compile(r"fault|diag|err|ariza|arıza|hata|open|short|range|fail|warn", re.I)


# ---- Veri sınıfları -----------------------------------------------------
@dataclass
class SignalDef:
    key: str                        # benzersiz: "dbc:MSG.SIG" | "ovr:<isim>" | "a2l:<isim>"
    name: str                       # ekranda görünen isim
    role: str                       # ROLE_*
    source: str                     # "CAN" | "CCP"
    group: str = ""                 # mesaj ismi veya isim öneki
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    initial: float | None = None
    choices: dict | None = None     # {sayı: etiket}
    description: str = ""
    # CAN
    message: str = ""
    signal: str = ""
    frame_id: int | None = None
    cycle_ms: int | None = None
    senders: tuple = ()
    # CCP / A2L
    meas: object | None = None      # MeasurementInfo (çıkış / ECU'nun gördüğü)
    ovr_val: object | None = None   # CharacteristicInfo
    ovr_en: object | None = None    # CharacteristicInfo
    missing: bool = False           # çalışma listesinde olup dosyada artık yok
    default_role: str = ""          # otomatik sınıflama (kullanıcı düzeltmesinden önce)

    @property
    def is_boolean(self) -> bool:
        if self.choices is not None and len(self.choices) <= 2:
            return True
        return self.minimum == 0 and self.maximum == 1

    @property
    def is_fault_like(self) -> bool:
        return self.is_boolean and bool(_FAULT_RE.search(self.name))

    def range_text(self) -> str:
        if self.minimum is None and self.maximum is None:
            return ""
        lo = "" if self.minimum is None else f"{self.minimum:g}"
        hi = "" if self.maximum is None else f"{self.maximum:g}"
        return f"{lo} … {hi}"

    def fingerprint(self) -> dict:
        """Dosya değişince fark bulmak için karşılaştırılan alanlar."""
        def addr(info):
            return None if info is None else getattr(info, "address", None)
        return {
            "unit": self.unit, "min": self.minimum, "max": self.maximum,
            "frame_id": self.frame_id, "cycle_ms": self.cycle_ms, "message": self.message,
            "addr": addr(self.meas), "addr_val": addr(self.ovr_val), "addr_en": addr(self.ovr_en),
        }


@dataclass
class CatalogDiff:
    added: list = field(default_factory=list)     # [SignalDef]
    removed: list = field(default_factory=list)   # [SignalDef] (eski kataloğdan)
    changed: list = field(default_factory=list)   # [(SignalDef, "açıklama")]

    @property
    def empty(self) -> bool:
        return not (self.added or self.removed or self.changed)


# ---- Katalog çıkarımı -----------------------------------------------------
def _is_input_node(node: str, input_nodes) -> bool:
    n = (node or "").upper()
    for pat in input_nodes:
        p = pat.upper()
        if n == p or p in n and len(p) > 2:
            return True
    return False


def _msg_cycle_ms(msg) -> int:
    ct = getattr(msg, "cycle_time", None)
    try:
        if ct:
            return int(ct)
    except (TypeError, ValueError):
        pass
    return DEFAULT_CYCLE_MS


def _choices_dict(signal) -> dict | None:
    ch = getattr(signal, "choices", None)
    if not ch:
        return None
    return {int(k): str(v) for k, v in ch.items()}


def _prefix(name: str) -> str:
    return name.split("_", 1)[0] if "_" in name else "Diğer"


def build_catalog(dbc_db, a2l_summary, input_nodes=DEFAULT_INPUT_NODES,
                  role_overrides: dict | None = None,
                  cycle_overrides: dict | None = None) -> list[SignalDef]:
    """DBC (DbcDatabase ya da None) + A2L özeti (A2LSummary ya da None) ->
    sınıflandırılmış sinyal listesi. role_overrides kullanıcının elle
    düzelttiği sınıflardır ({anahtar: rol})."""
    role_overrides = role_overrides or {}
    cycle_overrides = cycle_overrides or {}
    out: list[SignalDef] = []

    # --- DBC ---
    cantools_db = getattr(dbc_db, "_db", None) if dbc_db is not None else None
    if cantools_db is not None:
        for msg in cantools_db.messages:
            senders = tuple(msg.senders or ())
            is_in = any(_is_input_node(s, input_nodes) for s in senders)
            cycle = int(cycle_overrides.get(msg.name, _msg_cycle_ms(msg)))
            for sig in msg.signals:
                key = f"dbc:{msg.name}.{sig.name}"
                default_role = ROLE_AIRCRAFT_IN if is_in else ROLE_OUTPUT
                role = role_overrides.get(key, default_role)
                initial = sig.initial if isinstance(sig.initial, (int, float)) else None
                out.append(SignalDef(
                    key=key, name=sig.name, role=role, source="CAN", group=msg.name,
                    unit=sig.unit or "", minimum=sig.minimum, maximum=sig.maximum,
                    initial=initial, choices=_choices_dict(sig), description=sig.comment or "",
                    message=msg.name, signal=sig.name, frame_id=msg.frame_id,
                    cycle_ms=cycle, senders=senders, default_role=default_role,
                ))

    # --- A2L ---
    if a2l_summary is not None:
        chars = {c.name: c for c in a2l_summary.characteristics}
        meas_by_name = {m.name: m for m in a2l_summary.measurements}
        paired_bases = set()
        for cname, c in chars.items():
            if not cname.lower().endswith(OVR_VAL_SUFFIX.lower()):
                continue
            base = cname[: -len(OVR_VAL_SUFFIX)]
            en = None
            for cand in (base + OVR_EN_SUFFIX, base + "_ovr_en", base + "_OVR_EN"):
                if cand in chars:
                    en = chars[cand]
                    break
            key = f"ovr:{base}"
            paired_bases.add(base)
            role = role_overrides.get(key, ROLE_SENSOR_OVR)
            out.append(SignalDef(
                key=key, name=base, role=role, source="CCP", group="Sensör",
                unit=c.unit or "", minimum=c.minimum, maximum=c.maximum,
                description=c.description or "", meas=meas_by_name.get(base),
                ovr_val=c, ovr_en=en, default_role=ROLE_SENSOR_OVR,
            ))
        for mname, m in meas_by_name.items():
            key = f"a2l:{mname}"
            role = role_overrides.get(key, ROLE_OUTPUT)
            out.append(SignalDef(
                key=key, name=mname, role=role, source="CCP", group=_prefix(mname),
                unit=m.unit or "", minimum=m.minimum, maximum=m.maximum,
                description=m.description or "", meas=m, default_role=ROLE_OUTPUT,
            ))
    return out


def catalog_index(catalog: list[SignalDef]) -> dict:
    return {s.key: s for s in catalog}


def diff_catalogs(old: list[SignalDef], new: list[SignalDef]) -> CatalogDiff:
    oi, ni = catalog_index(old), catalog_index(new)
    d = CatalogDiff()
    for k, s in ni.items():
        if k not in oi:
            d.added.append(s)
    for k, s in oi.items():
        if k not in ni:
            d.removed.append(s)
    labels = {"unit": "birim", "min": "alt sınır", "max": "üst sınır", "frame_id": "CAN ID",
              "cycle_ms": "periyot", "message": "mesaj", "addr": "adres",
              "addr_val": "override değer adresi", "addr_en": "override bayrak adresi"}
    for k, s in ni.items():
        o = oi.get(k)
        if o is None:
            continue
        fo, fn = o.fingerprint(), s.fingerprint()
        parts = []
        for f, lbl in labels.items():
            if fo[f] != fn[f]:
                def fmt(v):
                    return "—" if v is None else (f"0x{v:X}" if f.startswith("addr") or f == "frame_id" else f"{v}")
                parts.append(f"{lbl} {fmt(fo[f])} → {fmt(fn[f])}")
        if parts:
            d.changed.append((s, ", ".join(parts)))
    return d


# ---- Yapılandırma (kalıcı) ------------------------------------------------
class ControlPanelConfig:
    def __init__(self, path: str | None = None):
        self.path = path
        self.pinned: list[str] = []
        self.views: dict[str, list[str]] = {}
        self.current_view: str = ""
        self.role_overrides: dict[str, str] = {}
        self.cycle_overrides: dict[str, int] = {}
        self.input_nodes: list[str] = list(DEFAULT_INPUT_NODES)
        self.scenarios: dict[str, dict] = {}
        self.collapsed: list[str] = [ROLE_INTERNAL]
        self.compact: bool = False
        if path and os.path.exists(path):
            self._load()

    def _load(self):
        raw = load_json(self.path, None, dict)
        if raw is None:
            return
        try:
            self._apply_raw(raw)
        except (TypeError, ValueError, AttributeError):
            log.exception("kontrol_paneli.json içeriği geçersiz; varsayılanlar kullanıldı")

    def _apply_raw(self, raw: dict):
        self.pinned = [str(k) for k in raw.get("pinned", []) if isinstance(k, str)]
        views = raw.get("views", {})
        self.views = {str(n): [str(k) for k in ks] for n, ks in (views.items() if isinstance(views, dict) else [])
                      if isinstance(ks, list)}
        self.current_view = str(raw.get("current_view", ""))
        ro = raw.get("role_overrides", {})
        self.role_overrides = {str(k): str(v) for k, v in (ro.items() if isinstance(ro, dict) else [])
                               if v in ALL_ROLES}
        self.cycle_overrides = {}
        co = raw.get("cycle_overrides", {})
        for k, v in (co.items() if isinstance(co, dict) else []):
            try:
                self.cycle_overrides[str(k)] = max(1, int(v))
            except (TypeError, ValueError):
                pass
        nodes = raw.get("input_nodes")
        if isinstance(nodes, list) and nodes:
            self.input_nodes = [str(n) for n in nodes]
        sc = raw.get("scenarios", {})
        self.scenarios = {str(n): v for n, v in (sc.items() if isinstance(sc, dict) else []) if isinstance(v, dict)}
        self.collapsed = [str(r) for r in raw.get("collapsed", [ROLE_INTERNAL])]
        self.compact = bool(raw.get("compact", False))

    def save(self):
        if not self.path:
            return
        data = {
            "v": 1, "pinned": self.pinned, "views": self.views, "current_view": self.current_view,
            "role_overrides": self.role_overrides, "cycle_overrides": self.cycle_overrides,
            "input_nodes": self.input_nodes, "scenarios": self.scenarios,
            "collapsed": self.collapsed, "compact": self.compact,
        }
        atomic_write_json(self.path, data)


# ---- CCP yardımcıları -----------------------------------------------------
def ccp_read_value(client, info) -> float:
    """MeasurementInfo/CharacteristicInfo -> fiziksel değer."""
    return ccp_codec.read_value(client, info).phys


def ccp_write_value(client, info, phys: float, enforce_limits: bool = True, verify: bool = False):
    """A2L bilgisinden fiziksel değer yazar. Değer doğrulanır (sonlu, tür
    aralığı; enforce_limits ise A2L min/max ve READ_ONLY). Güvenlik amaçlı
    "override kapat" yazımı enforce_limits=False ile çağrılır: kapatma değeri
    hiçbir sınır yüzünden engellenmemelidir (yine de sonlu/tür kontrolü var)."""
    if enforce_limits:
        data = ccp_codec.encode_for_write(info, phys)
    else:
        raw = ccp_codec.physical_to_raw(info.compu_method, float(phys))
        data = ccp_codec.encode_value(info.datatype, raw, info.byte_order)
    client.write_memory(info.address, data, info.address_extension or 0, verify=verify)


def parse_input_value(text, choices: dict | None = None) -> float | None:
    """Kullanıcı girişi -> sayı. Durum listesi varsa etiket de kabul edilir."""
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    if choices:
        for k, label in choices.items():
            if s.lower() == label.lower():
                return float(k)
    s = s.replace(",", ".")
    try:
        v = float(int(s, 16)) if s.lower().startswith("0x") else float(s)
    except ValueError:
        return None
    return v if v == v and abs(v) != float("inf") else None


# ---- Periyodik CAN gönderici ------------------------------------------------
class _TxThread(threading.Thread):
    """Bir mesajı kendi periyoduyla gönderen iş parçacığı. İlk kare ``set_values`` tarafından hemen
    gönderildiği için bu iş parçacığı ilk gönderimini bir periyot SONRA yapar."""

    def __init__(self, tick, period_s: float):
        super().__init__(daemon=True, name="panel-tx")
        self._tick = tick
        self.period_s = period_s
        self._stop_event = threading.Event()

    def stop(self):
        self._stop_event.set()

    def stopped(self) -> bool:
        return self._stop_event.is_set()

    def run(self):
        next_t = time.monotonic() + self.period_s
        while not self._stop_event.wait(max(0.0, next_t - time.monotonic())):
            self._tick()
            next_t += self.period_s
            if next_t - time.monotonic() < -1.0:      # uzun kesintiden sonra patlama (burst) yapma
                next_t = time.monotonic()


class TxScheduler(QObject):
    """DBC mesajlarını periyodik olarak gönderir. Bir mesajın TÜM sinyalleri
    son değerleriyle tek karede kodlanır (ECU yarım değişmiş mesaj görmez).

    Gönderim ARAYÜZ İŞ PARÇACIĞINDA DEĞİL, mesaj başına bir arka plan iş parçacığında yapılır: arayüz
    takılsa (uzun işlem, pencere sürükleme, modal kutu) bile ECU'ya giden kareler kesilmez. Kare, değerler
    değiştiğinde (``set_values``, arayüz iş parçacığı) bir kez kodlanır; iş parçacığı yalnızca hazır baytları
    yollar. Gönderim hatası (bus-off, TX kuyruğu dolu, hat toparlanıyor...) mesajı DURDURMAZ: hata yalnızca
    bir kez (ardışık hata dizisinin başında) `failed` ile bildirilir ve hat düzelince gönderim kendiliğinden
    devam eder."""

    failed = Signal(str, str)        # mesaj, hata (ardışık hata dizisinin başında bir kez)
    recovered = Signal(str)          # hata dizisinden sonra gönderim yeniden başarılı
    state_changed = Signal()

    def __init__(self, dbc, send_fn, parent=None):
        super().__init__(parent)
        self._dbc = dbc
        self._send = send_fn                 # (can_id, data: bytes, extended: bool); her iş parçacığından çağrılır
        self._values: dict[str, dict] = {}   # mesaj -> {sinyal: değer}
        self._frames: dict[str, tuple] = {}  # mesaj -> (can_id, data, extended): gönderilecek hazır kare
        self._cycles: dict[str, int] = {}    # mesaj -> son kullanılan periyot (ms)
        self._tasks: dict[str, _TxThread] = {}
        self._lock = threading.Lock()
        self.frames_sent = 0
        self.errors = 0
        self._failing: set = set()          # şu an hata dizisinde olan mesajlar

    # -- durum --
    def running_messages(self) -> set:
        return {n for n, t in self._tasks.items() if not t.stopped()}

    def is_running(self, message: str) -> bool:
        t = self._tasks.get(message)
        return bool(t is not None and not t.stopped())

    def values_of(self, message: str) -> dict:
        return dict(self._values.get(message, {}))

    # -- kontrol --
    def set_values(self, message: str, values: dict, cycle_ms: int | None = None,
                   start: bool = True) -> tuple[int, bytes]:
        """Sinyal değerlerini günceller ve HEMEN bir kare gönderir; mesaj
        zaten periyodik gönderiliyorsa yeni değerlerle sürer, değilse (start)
        periyodik göndermeyi başlatır. (frame_id, data) döner."""
        cur = self._values.setdefault(message, {})
        cur.update(values)
        frame = self._send_now(message)          # hata -> istisna çağırana gider
        if cycle_ms:
            self._cycles[message] = max(1, int(cycle_ms))
        if start:
            self._ensure_task(message, self._cycles.get(message) or self._cycle_of(message))
        return frame

    def _cycle_of(self, message: str) -> int:
        msg = self._dbc.get_message(message) if self._dbc is not None else None
        return _msg_cycle_ms(msg) if msg is not None else DEFAULT_CYCLE_MS

    def _ensure_task(self, message: str, cycle_ms: int):
        cycle_ms = max(1, int(cycle_ms))
        self._cycles[message] = cycle_ms
        t = self._tasks.get(message)
        if t is not None and not t.stopped():
            t.period_s = cycle_ms / 1000.0
            return
        t = _TxThread(lambda m=message: self._tick(m), cycle_ms / 1000.0)
        self._tasks[message] = t
        t.start()
        self.state_changed.emit()

    def _defaults_for(self, message: str) -> dict:
        msg = self._dbc.get_message(message)
        d = {}
        for s in msg.signals:
            if isinstance(s.initial, (int, float)):
                d[s.name] = s.initial
            elif s.minimum is not None:
                d[s.name] = s.minimum if s.minimum > 0 else 0
            else:
                d[s.name] = 0
        return d

    def _encode(self, message: str) -> tuple:
        merged = self._defaults_for(message)
        merged.update(self._values.get(message, {}))
        return self._dbc.encode(message, merged)

    def _send_now(self, message: str) -> tuple[int, bytes]:
        """Güncel değerlerle kareyi kodlar, periyodik gönderimin kullanacağı hazır kareyi günceller ve
        bir kare yollar (arayüz iş parçacığı)."""
        can_id, data, extended = self._encode(message)
        with self._lock:
            self._frames[message] = (can_id, data, extended)
        self._send(can_id, data, extended)
        self.frames_sent += 1
        return can_id, data

    def refresh_frames(self):
        """DBC yeniden yüklenince: hazır kareler yeni tanımla yeniden kodlanır. Artık kodlanamayan
        (DBC'den silinmiş / değeri sığmayan) mesajın gönderimi durdurulur ve `failed` ile bildirilir."""
        for message in list(self._frames):
            try:
                frame = self._encode(message)
            except Exception as exc:  # noqa: BLE001
                self.stop_message(message)
                with self._lock:
                    self._frames.pop(message, None)
                self.failed.emit(message, f"DBC değişti, mesaj kodlanamıyor: {exc}")
                continue
            with self._lock:
                self._frames[message] = frame

    def _tick(self, message: str):
        """Hazır kareyi bir kez yollar (periyodik iş parçacığından çağrılır)."""
        with self._lock:
            frame = self._frames.get(message)
        if frame is None:
            return
        try:
            self._send(*frame)
        except Exception as exc:
            with self._lock:
                self.errors += 1
                first = message not in self._failing    # hata dizisinin başında bir kez bildir
                self._failing.add(message)
            if first:
                self._emit(self.failed, message, str(exc))
            return
        with self._lock:
            self.frames_sent += 1
            was_failing = message in self._failing
            self._failing.discard(message)
        if was_failing:
            self._emit(self.recovered, message)

    @staticmethod
    def _emit(signal, *args):
        try:
            signal.emit(*args)       # arka plan iş parçacığından: Qt, alıcıya kuyruklu iletir
        except RuntimeError:         # uygulama kapanırken nesne silinmiş olabilir
            pass

    def _stop_task(self, message: str) -> bool:
        t = self._tasks.pop(message, None)
        if t is None or t.stopped():
            return False
        t.stop()
        if t is not threading.current_thread():
            t.join(timeout=0.3)      # "durdur" döndüğünde artık kare gitmiyor olsun
        return True

    def stop_message(self, message: str):
        if self._stop_task(message):
            self.state_changed.emit()

    def stop_all(self):
        changed = False
        for m in list(self._tasks):
            changed = self._stop_task(m) or changed
        if changed:
            self.state_changed.emit()

    def resume_all(self):
        """Durdurulmuş (ör. Gönderimi durdur) mesajları son değerleri ve son periyotlarıyla sürdürür."""
        for m in list(self._values):
            try:
                if m not in self._frames:
                    with self._lock:
                        self._frames[m] = self._encode(m)
                self._ensure_task(m, self._cycles.get(m) or self._cycle_of(m))
            except Exception:  # noqa: BLE001
                log.exception("%s gönderimi sürdürülemedi", m)

    def clear_values(self):
        self.stop_all()
        self._values.clear()
        with self._lock:
            self._frames.clear()


def now() -> float:
    return time.monotonic()
