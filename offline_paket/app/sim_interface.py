"""Simülasyon Arayüzü (Ana Sayfa girişleri) ve Performans sayfası için
tanımlar, kalıcı eşleme yapılandırması ve sinyal kaynağı yardımcıları.

Tablolar performans takımından gelen listelerdir:
  SIMULATION INTERFACE (girişler) ve PERFORMANCE INTERFACE (çıkışlar).
Sinyal ISIMLERI DBC/A2L'den seçilir; burada yalnızca ekranda görünen ad,
birim, aralık ve otomatik eşleşme takma adları tutulur.
"""

from app.persist import atomic_write_json, load_json
import re
from dataclasses import dataclass


# ======================= Girişler (Simülasyon Arayüzü) =======================
@dataclass(frozen=True)
class InputDef:
    key: str
    label: str
    unit: str
    minimum: float
    maximum: float
    kind: str            # "switch" | "slider" | "const"
    group: str           # "control" | "aircraft" | "const"
    enabled: bool = True
    note: str = ""
    aliases: tuple = ()
    title: str = ""      # Ana Sayfa'da gösterilen tek satırlık Türkçe ad (boşsa label)

    @property
    def display(self) -> str:
        return self.title or self.label


INPUT_DEFS: list[InputDef] = [
    InputDef("start", "Start", "", 0, 1, "switch", "control", aliases=("start", "engstart", "enginestart"), title="Çalıştırma (Start)"),
    InputDef("throttle", "Throttle", "%", 0, 120, "slider", "control", aliases=("throttle", "pla", "thr"), title="Gaz Kolu (PLA)"),
    InputDef("altitude", "Altitude", "kft", 0, 30, "slider", "aircraft", aliases=("altitude", "alt", "acaltitude"), title="Rakım"),
    InputDef("alfa", "Alfa", "°", -90, 90, "slider", "aircraft",
             aliases=("alfa", "alpha", "acalpha", "acalfa"), title="Hücum Açısı (α)"),
    InputDef("beta", "Beta", "°", -90, 90, "slider", "aircraft",
             aliases=("beta", "acbeta"), title="Kayma Açısı (β)"),
    InputDef("ma", "Ma Number", "", 0, 2, "const", "aircraft", aliases=("ma", "mach", "manumber", "acmach"), title="Mach Sayısı"),
    InputDef("p_total", "Total Inlet Pressure", "bar", 0.01, 10, "const", "aircraft",
             aliases=("totalinletpressure", "ptotal", "pt", "pinlet", "totalpressure"), title="Toplam Giriş Basıncı"),
    InputDef("p_amb", "Ambient Pressure", "bar", 0.01, 10, "const", "aircraft",
             aliases=("ambientpressure", "pamb", "pambient", "pa", "ps0"), title="Ortam Basıncı"),
    InputDef("t_amb", "Ambient Temperature", "°C", -40, 40, "const", "aircraft",
             aliases=("ambienttemperature", "tamb", "tambient", "ta", "ambtemp", "acambtemp"), title="Ortam Sıcaklığı"),
]
INPUT_BY_KEY = {d.key: d for d in INPUT_DEFS}
# Uçuş Koşulları (uçaktan gelen değerler): yalnızca CAN, anında gönderilir. Motor Kontrol girişleri
# (start/throttle) doğrudan komuttur (değer + Enter, kilit yok) (bkz. dashboard_config.CONTROL_KEYS).
FLIGHT_DEFS = [d for d in INPUT_DEFS if d.group == "aircraft"]


# ======================= Çıkışlar (Performans Arayüzü) =======================
@dataclass(frozen=True)
class PerfDef:
    key: str
    label: str
    unit: str
    card: str            # "B".."E"
    kind: str            # "gauge" | "digital"
    hint: str = ""       # tabloda yazan formül/açıklama
    aliases: tuple = ()


PERF_DEFS: list[PerfDef] = [
    PerfDef("comp_flow", "Comp Air Mass Flow Rate", "kg/s", "B", "digital", aliases=("compairmassflowrate", "compmassflow", "compflow", "wcomp")),
    PerfDef("comp_pout", "Comp Total Outlet Pressure", "bar", "B", "digital", aliases=("comptotaloutletpressure", "compoutletpressure", "comppout", "p3")),
    PerfDef("comp_pr", "Comp PR", "", "B", "digital", "P3/P2", aliases=("comppr", "compressorpr", "prcomp")),
    PerfDef("comp_n", "Comp N", "RPM", "B", "gauge", aliases=("compn", "compnrpm", "compspeed", "rpm", "n")),
    PerfDef("comp_surge", "Comp Surge Margin", "%", "B", "digital", aliases=("compsurgemargin", "surgemargin", "compsm")),
    PerfDef("comp_eff", "Comp Eff", "", "B", "digital", aliases=("compeff", "compefficiency", "etacomp")),
    PerfDef("cc_fuel1", "CC Primer Fuel Mass Flow Rate", "kg/s", "C", "digital", aliases=("ccprimerfuelmassflowrate", "ccprimerfuel", "primerfuelflow", "wfprimer")),
    PerfDef("cc_fuel2", "CC Seconder Fuel Mass Flow Rate", "kg/s", "C", "digital", aliases=("ccsecoderfuelmassflowrate", "ccsecnderfuel", "ccsecondaryfuel", "secoderfuelflow", "wfsecond")),
    PerfDef("cc_tit", "CC TIT", "°C", "C", "gauge", aliases=("cctit", "tit", "t4", "turbineinlettemperature")),
    PerfDef("cc_deip", "CC deIP", "bar", "C", "digital", "P3-P4", aliases=("ccdeip", "deip", "dp", "ccdp")),
    PerfDef("cc_eff", "CC Eff", "", "C", "digital", aliases=("cceff", "ccefficiency", "etacc")),
    PerfDef("turb_pout", "Turb Total Outlet Pressure", "bar", "D", "digital", aliases=("turbtotaloutletpressure", "turboutletpressure", "turbpout", "p5")),
    PerfDef("turb_pr", "Turb PR", "", "D", "digital", "P4/P5", aliases=("turbpr", "turbinepr", "prturb")),
    PerfDef("turb_egt", "Turb EGT", "°C", "D", "gauge", aliases=("turbegt", "egt", "t5", "tt5")),
    PerfDef("nozz_thrust", "Nozz Thrust", "N", "E", "gauge", aliases=("nozzthrust", "thrust", "fn")),
    PerfDef("nozz_vel", "Nozz Outlet Velocity", "m/s", "E", "digital", aliases=("nozzoutletvelocity", "nozzvelocity", "outletvelocity", "vnozz")),
    PerfDef("nozz_pr", "Nozz PR", "bar", "E", "digital", "P5/Pamb", aliases=("nozzpr", "nozzlepr", "prnozz")),
]
PERF_BY_KEY = {d.key: d for d in PERF_DEFS}

CARD_STYLES = {
    # kart: (başlık, arka plan, kenar, başlık rengi)
    "A": ("A. FLIGHT CONDITIONS", "#E3EFFC", "#9CC3EE", "#1D4E89"),
    "B": ("B. COMPRESSOR", "#E2F3E2", "#9FD09F", "#1F6B2E"),
    "C": ("C. COMBUSTION CHAMBER", "#FFF4CF", "#EBCB61", "#8A6A00"),
    "D": ("D. TURBINE", "#FFE5D2", "#F0AE80", "#A34A10"),
    "E": ("E. NOZZLE", "#D6F3F4", "#7FCFD3", "#0E6A70"),
}

DEFAULT_GRAPHS = [
    {"title": "Basınçlar ve PR", "keys": ["comp_pout", "turb_pout", "comp_pr", "turb_pr", "cc_deip", "nozz_pr"], "normalize": True},
    {"title": "Sıcaklıklar", "keys": ["cc_tit", "turb_egt"], "normalize": False},
    {"title": "İtki ve Yakıt", "keys": ["nozz_thrust", "cc_fuel1", "cc_fuel2"], "normalize": True},
]


# ======================= Eşleme yardımcıları =======================
def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


@dataclass
class SourceSig:
    key: str            # "dbc:MSG.SIG" | "a2l:Name"
    name: str           # sinyal / ölçüm adı
    where: str          # mesaj adı ya da "A2L"
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    initial: float | None = None
    frame_id: int | None = None
    info: object = None  # A2L Measurement/Characteristic

    @property
    def label(self) -> str:
        return f"{self.name}   ·   {self.where}" + (f"   [{self.unit}]" if self.unit else "")


def list_sources(dbc, a2l_summary, dbc_only: bool = False) -> list[SourceSig]:
    out: list[SourceSig] = []
    cdb = getattr(dbc, "_db", None) if dbc is not None else None
    if cdb is not None:
        for m in cdb.messages:
            for s in m.signals:
                init = s.initial if isinstance(s.initial, (int, float)) else None
                out.append(SourceSig(f"dbc:{m.name}.{s.name}", s.name, m.name, s.unit or "",
                                     s.minimum, s.maximum, init, m.frame_id))
    if a2l_summary is not None and not dbc_only:
        readable = a2l_summary.readable() if hasattr(a2l_summary, "readable") else a2l_summary.measurements
        for me in readable:
            out.append(SourceSig(f"a2l:{me.name}", me.name, "A2L", getattr(me, "unit", "") or "",
                                 getattr(me, "minimum", None), getattr(me, "maximum", None), None, None, me))
    return out


def auto_match(aliases: tuple, label: str, sources: list[SourceSig]) -> SourceSig | None:
    """Önce tam eşleşme (etiket/takma ad), sonra tek-adaylı 'ile biter'
    eşleşmesi. Belirsizse (birden çok aday) HİÇBİRİNİ seçmez."""
    wanted = [norm(a) for a in aliases] + [norm(label)]
    by_norm: dict[str, list[SourceSig]] = {}
    for s in sources:
        by_norm.setdefault(norm(s.name), []).append(s)
    for w in wanted:
        hits = by_norm.get(w, [])
        if len(hits) == 1:
            return hits[0]
    for w in wanted:
        if len(w) < 4:
            continue
        hits = [s for s in sources if norm(s.name).endswith(w)]
        if len(hits) == 1:
            return hits[0]
    return None


# ======================= Kalıcı yapılandırma =======================
class SimConfig:
    def __init__(self, path: str | None = None):
        self.path = path
        self.input_map: dict[str, str] = {}     # giriş anahtarı -> "dbc:MSG.SIG"
        self.input_values: dict[str, float] = {}
        self.perf_map: dict[str, str] = {}      # çıkış anahtarı -> kaynak anahtarı
        self.ranges: dict[str, list] = {}       # gauge anahtarı -> [min, max]
        self.thresholds: dict[str, dict] = {}   # çıkış anahtarı -> {"warn","crit","mode"}
        self.graphs: list[dict] = [dict(g, keys=list(g["keys"])) for g in DEFAULT_GRAPHS]
        self.window_s: int = 60
        self._load()

    def _load(self):
        raw = load_json(self.path, None, dict) if self.path else None
        if raw is None:
            return

        def as_dict(key):
            v = raw.get(key, {})
            return dict(v) if isinstance(v, dict) else {}
        self.input_map = as_dict("input_map")
        self.input_values = {}
        for k, v in as_dict("input_values").items():
            try:
                self.input_values[str(k)] = float(v)
            except (TypeError, ValueError):
                pass
        self.perf_map = as_dict("perf_map")
        self.ranges = as_dict("ranges")
        self.thresholds = as_dict("thresholds")
        g = raw.get("graphs")
        if isinstance(g, list) and g and all(isinstance(x, dict) and isinstance(x.get("keys"), list) for x in g):
            self.graphs = g
        try:
            self.window_s = max(1, int(raw.get("window_s", 60)))
        except (TypeError, ValueError):
            self.window_s = 60

    def save(self):
        if not self.path:
            return
        return atomic_write_json(self.path, {
            "input_map": self.input_map, "input_values": self.input_values,
            "perf_map": self.perf_map, "ranges": self.ranges,
            "thresholds": self.thresholds, "graphs": self.graphs,
            "window_s": self.window_s})


def threshold_level(cfg: dict | None, value: float | None) -> int:
    """0 normal, 1 uyarı, 2 kritik. mode: 'low' (altında) | 'high' (üstünde)."""
    if not cfg or value is None:
        return 0
    mode = cfg.get("mode", "low")
    warn, crit = cfg.get("warn"), cfg.get("crit")
    if mode == "low":
        if crit is not None and value <= crit:
            return 2
        if warn is not None and value <= warn:
            return 1
    else:
        if crit is not None and value >= crit:
            return 2
        if warn is not None and value >= warn:
            return 1
    return 0
