"""MIL kalibrasyonu: MODELDE HİÇBİR DEĞİŞİKLİK YAPMADAN, MATLAB Engine ile base workspace'teki
``Simulink.Parameter`` / ``Simulink.LookupTable`` nesnelerini listeleme ve değiştirme.

Akış: kullanıcı parametre ``.m`` dosyasını seçer -> MATLAB Engine dosyayı çalıştırır (base workspace)
-> ``simulink/matlab/mil_list_params.m`` nesneleri JSON olarak listeler -> burada sentetik A2L özeti
(``A2LSummary``) üretilir (A2L dosyası YOKTUR; birim/min/max/tip nesnenin kendisinden gelir) ->
``EngineParamClient`` mevcut Kalibrasyon ekranına CCPClient gibi görünür; yazma ``NAME.Value = ...`` ile yapılır.

DOĞRULANMADI: gerçek MATLAB/Simulink ile denenmedi (sahte engine ile test edilir). Özellikle çalışan modelde
workspace değişikliğinin ``SimulationCommand=update`` ile uygulanıp uygulanmadığı gerçek ortamda doğrulanmalıdır.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from dataclasses import dataclass, field

from app.a2l import A2LSummary, AxisInfo, CharacteristicInfo
from app.ccp import protocol as ccp
from app.ccp import codec

_NAME_RE = re.compile(r"^[A-Za-z_]\w*$")
_A2L_TYPES = {"double": "FLOAT64_IEEE", "single": "FLOAT32_IEEE", "int8": "SBYTE", "uint8": "UBYTE",
              "int16": "SWORD", "uint16": "UWORD", "int32": "SLONG", "uint32": "ULONG", "logical": "UBYTE",
              "boolean": "UBYTE"}
_BASE_ADDRESS = 0x1000


class EngineParamError(ccp.CCPError):
    def __init__(self, message: str, return_code: int = ccp.RC_ACCESS_DENIED):
        Exception.__init__(self, message)
        self.command = 0
        self.return_code = return_code


@dataclass
class EngineParam:
    name: str
    kind: str                       # "param" | "lut"
    mclass: str                     # değerin MATLAB sınıfı (double/single/uint8/logical...)
    dims: tuple                     # (satır, sütun)
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    storage: str = ""
    axes: list = field(default_factory=list)      # [(değerler, birim)] MATLAB sırasıyla: Breakpoints{1}, {2}...
    address: int = 0

    @property
    def count(self) -> int:
        return self.dims[0] * self.dims[1]

    @property
    def expr(self) -> str:
        return f"{self.name}.Table.Value" if self.kind == "lut" else f"{self.name}.Value"

    @property
    def tunable_running(self) -> bool:
        """Çalışan modelde yazılabilir varsayımı: StorageClass 'Auto' (satır içi/inlined) DEĞİLSE tunable."""
        return bool(self.storage) and self.storage != "Auto"


def _num(v):
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, list):                      # jsonencode boş [] -> boş liste (Min/Max tanımsız)
        return None if not v else _num(v[0])
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def parse_listing(text: str):
    """``mil_list_params`` JSON çıktısı -> (parametre listesi, atlananlar [(ad, neden)])."""
    try:
        raw = json.loads(text) if text else []
    except json.JSONDecodeError as exc:
        raise EngineParamError(f"Parametre listesi çözülemedi: {exc}") from exc
    if isinstance(raw, dict):
        raw = [raw]
    params, skipped, seen = [], [], set()
    for it in raw:
        name = str(it.get("name", ""))
        if not _NAME_RE.match(name):
            skipped.append((name, "geçersiz MATLAB değişken adı"))
            continue
        if it.get("error"):
            skipped.append((name, f"MATLAB okuma hatası: {it['error']}"))
            continue
        mclass = str(it.get("mclass", ""))
        if mclass not in _A2L_TYPES:
            skipped.append((name, f"desteklenmeyen veri tipi {mclass or '?'} (fixdt/enum/struct vb.)"))
            continue
        dims = it.get("dims") or [1, 1]
        if not (isinstance(dims, list) and len(dims) == 2 and all(isinstance(d, int) and d >= 1 for d in dims)):
            skipped.append((name, f"desteklenmeyen boyut {dims}"))
            continue
        axes = []
        for bp in (it.get("breakpoints") or []):
            vals = bp.get("values", [])
            vals = vals if isinstance(vals, list) else [vals]
            axes.append(([float(x) for x in vals], str(bp.get("unit") or "")))
        kind = it.get("kind", "param")
        if kind == "lut":
            if it.get("bpspec") not in (None, "", "Explicit values"):
                skipped.append((name, f"eksen tanımı '{it.get('bpspec')}' (yalnız 'Explicit values' desteklenir)"))
                continue
            if len(axes) not in (1, 2):
                skipped.append((name, f"{len(axes)} eksenli tablo desteklenmiyor (1B/2B desteklenir)"))
                continue
            counts = [len(a[0]) for a in axes]
            if len(axes) == 1 and dims[0] * dims[1] != counts[0]:
                skipped.append((name, "tablo boyutu eksenle uyuşmuyor"))
                continue
            if len(axes) == 2 and (dims[0], dims[1]) != (counts[0], counts[1]):
                skipped.append((name, "tablo boyutu eksenlerle uyuşmuyor"))
                continue
            if len(axes) == 1:
                dims = [1, counts[0]]
        elif dims[0] > 1 and dims[1] == 1:       # sütun vektörü -> 1xN (doğrusal indeks aynı sırayı verir)
            dims = [1, dims[0]]
        if name in seen:
            continue
        seen.add(name)
        params.append(EngineParam(name, kind, mclass, (dims[0], dims[1]), str(it.get("unit") or ""),
                                  _num(it.get("min")), _num(it.get("max")), str(it.get("storage") or ""), axes))
    return params, skipped


def build_summary(params: list, label: str = "MIL parametreleri") -> A2LSummary:
    """Sentetik A2L özeti: her nesneye sanal bir adres atanır (hücreler ardışık, satır-majör)."""
    chars, addr = [], _BASE_ADDRESS
    for p in params:
        p.address = addr
        dt = _A2L_TYPES[p.mclass]
        size = codec.datatype_size(dt)
        addr += ((size * p.count + 15) // 16) * 16
        axes, kind, char_type, dims = [], "SCALAR", "VALUE", None
        if p.kind == "lut":
            # GUI: axes[0]=X (sütun), axes[1]=Y (satır). MATLAB: Breakpoints{1}=satır, Breakpoints{2}=sütun.
            order = list(reversed(p.axes)) if len(p.axes) == 2 else p.axes
            axes = [AxisInfo(count=len(v), unit=u, attribute="FIX_AXIS", values=list(v)) for v, u in order]
            kind, char_type = ("MAP", "MAP") if len(p.axes) == 2 else ("CURVE", "CURVE")
        elif p.count > 1:
            kind, char_type = "ARRAY", "VAL_BLK"
            dims = (p.dims[1],) if p.dims[0] == 1 else (p.dims[0], p.dims[1])
        chars.append(CharacteristicInfo(
            name=p.name, description=f"Simulink {'LookupTable' if p.kind == 'lut' else 'Parameter'}"
            + (f" · {p.storage}" if p.storage else ""),
            kind=kind, address=p.address, unit=p.unit, datatype=dt, minimum=p.minimum, maximum=p.maximum,
            read_only=False, num_axes=len(axes), byte_order="LITTLE_ENDIAN", compu_method=None, axes=axes,
            char_type=char_type, dims=dims))
    return A2LSummary(path="", project_name=label, module_name="Simulink", default_byte_order="LITTLE_ENDIAN",
                      measurements=[], characteristics=chars)


def helper_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for up in (os.path.join(here, "..", "..", "..", "simulink", "matlab"),
               os.path.join(here, "..", "..", "simulink", "matlab")):
        if os.path.isfile(os.path.join(up, "mil_list_params.m")):
            return os.path.normpath(up)
    return ""


def load_from_engine(eng, mfile: str, lock=None):
    """Parametre ``.m`` dosyasını MATLAB'da (base workspace) çalıştırır ve nesneleri listeler."""
    if not os.path.isfile(mfile):
        raise EngineParamError(f"Dosya bulunamadı: {mfile}")
    hdir = helper_dir()
    if not hdir:
        raise EngineParamError("simulink/matlab/mil_list_params.m bulunamadı.")
    lock = lock or threading.RLock()
    q = lambda s: s.replace("'", "''")  # noqa: E731 - MATLAB tek tırnak kaçışı
    with lock:
        try:
            eng.eval(f"addpath('{q(hdir)}');", nargout=0)
            eng.eval(f"evalin('base', \"run('{q(mfile)}')\");", nargout=0)
            text = eng.eval("mil_list_params()", nargout=1)
        except Exception as exc:  # noqa: BLE001 - MATLAB her tür hata verebilir
            raise EngineParamError(f"MATLAB parametre dosyasını çalıştıramadı/listeleyemedi: {exc}") from exc
    return parse_listing(str(text))


def _flat(v) -> list:
    if isinstance(v, list):
        out = []
        for x in v:
            out.extend(_flat(x))
        return out
    return [float(v)]


class EngineParamClient:
    """CCPClient bellek arayüzünü MATLAB Engine üzerinden taklit eder (adres = sentetik, hücre = tek eleman)."""
    cro_id = dto_id = station_address = 0
    timeout, retries = 0.5, 1

    def __init__(self, engine_provider, params: list, model_running=None, model_name=None, lock=None):
        self._engine = engine_provider
        self._running = model_running or (lambda: False)
        self._model = model_name or (lambda: "")
        self._lock = lock or threading.RLock()
        self._cells = {}
        self._types = {}
        for p in params:
            dt = _A2L_TYPES[p.mclass]
            size = codec.datatype_size(dt)
            self._types[p.name] = (p, dt, size)
            for k in range(p.count):
                self._cells[p.address + k * size] = (p, k)
        self.params = {p.name: p for p in params}

    @property
    def is_connected(self) -> bool:
        return self._engine() is not None

    def start_listening(self): pass
    def stop_listening(self): pass
    def connect(self): pass
    def disconnect(self, permanent: bool = False): pass

    def test_connection(self) -> bool:
        return self.is_connected

    def urgent(self):
        import contextlib
        return contextlib.nullcontext()

    def mapped_names(self) -> list:
        return sorted(self.params)

    def write_flash_memory(self, *_a, **_kw):
        raise EngineParamError("MIL'de kalıcı (flaş) yazma yoktur; yalnızca workspace parametresi yazılır.")

    # -- yardımcılar --
    def _eng(self):
        eng = self._engine()
        if eng is None:
            raise EngineParamError("MATLAB Engine bağlı değil (model panelinden MATLAB Engine ile bağlanın).")
        return eng

    def _fetch(self, p: EngineParam) -> list:
        eng = self._eng()
        with self._lock:
            try:
                text = eng.eval(f"jsonencode(double({p.expr}))", nargout=1)
            except Exception as exc:  # noqa: BLE001
                raise EngineParamError(f"{p.name}: MATLAB okuma hatası: {exc}") from exc
        vals = _flat(json.loads(str(text)))
        if len(vals) != p.count:
            raise EngineParamError(f"{p.name}: modelde eleman sayısı {len(vals)} (beklenen {p.count}); "
                                   "parametre dosyasını yeniden yükleyin.")
        return vals

    def _cell(self, address: int):
        ent = self._cells.get(address)
        if ent is None:
            raise EngineParamError("Bu adres bir MIL parametresine ait değil.", ccp.RC_OUT_OF_RANGE)
        return ent

    def read_memory(self, address: int, length: int, address_extension: int = 0) -> bytes:
        out, addr, end, cache = b"", address, address + length, {}
        while addr < end:
            p, k = self._cell(addr)
            _p, dt, size = self._types[p.name]
            if p.name not in cache:
                cache[p.name] = self._fetch(p)
            out += codec.encode_value(dt, cache[p.name][k], "LITTLE_ENDIAN")
            addr += size
        if addr != end:
            raise EngineParamError("Okuma hücre sınırına hizalı değil", ccp.RC_OUT_OF_RANGE)
        return out

    @staticmethod
    def _fmt(p: EngineParam, v: float) -> str:
        if p.mclass in ("logical", "boolean"):
            return "true" if v else "false"
        if p.mclass not in ("double", "single"):
            return str(int(round(v)))
        return repr(float(v))

    def _assign(self, p: EngineParam, k: int, v: float) -> str:
        val = self._fmt(p, v)
        if p.count == 1:
            return f"{p.expr} = {p.mclass if p.mclass != 'boolean' else 'logical'}({val});"
        if p.dims[0] > 1 and p.dims[1] > 1:
            r, c = divmod(k, p.dims[1])
            return f"{p.expr}({r + 1},{c + 1}) = {val};"
        return f"{p.expr}({k + 1}) = {val};"

    def write_memory(self, address: int, data: bytes, address_extension: int = 0, verify: bool = False):
        pos, addr, end, todo = 0, address, address + len(data), []
        running = bool(self._running())
        while addr < end:
            p, k = self._cell(addr)
            _p, dt, size = self._types[p.name]
            if running and not p.tunable_running:
                raise EngineParamError(f"{p.name}: model ÇALIŞIRKEN yazılamaz (StorageClass "
                                       f"'{p.storage or 'Auto'}' tunable değil). Modeli durdurun, yazın, yeniden başlatın.")
            chunk = data[pos:pos + size]
            if len(chunk) != size:
                raise EngineParamError("Yazma hücre sınırına hizalı değil", ccp.RC_OUT_OF_RANGE)
            v = float(codec.decode_value(dt, chunk, "LITTLE_ENDIAN"))
            if not math.isfinite(v):
                raise EngineParamError(f"{p.name}: değer sonlu değil", ccp.RC_OUT_OF_RANGE)
            if (p.minimum is not None and v < p.minimum) or (p.maximum is not None and v > p.maximum):
                raise EngineParamError(f"{p.name}: {v:g} değeri Min/Max ({p.minimum}..{p.maximum}) dışında",
                                       ccp.RC_OUT_OF_RANGE)
            todo.append((p, k, v))
            pos += size
            addr += size
        eng = self._eng()
        with self._lock:
            try:
                for p, k, v in todo:
                    eng.eval(self._assign(p, k, v), nargout=0)
                model = self._model()
                if running and model:
                    eng.set_param(model, "SimulationCommand", "update", nargout=0)
            except Exception as exc:  # noqa: BLE001
                raise EngineParamError(f"MATLAB yazma/güncelleme hatası: {exc}") from exc
        if verify:
            cache = {}
            for p, k, v in todo:
                if p.name not in cache:
                    cache[p.name] = self._fetch(p)
                got = cache[p.name][k]
                if abs(got - v) > 1e-6 * max(1.0, abs(v)):
                    raise EngineParamError(f"{p.name}: workspace'te {got:g}, yazılan {v:g} (doğrulama başarısız)",
                                           ccp.RC_OUT_OF_RANGE)
