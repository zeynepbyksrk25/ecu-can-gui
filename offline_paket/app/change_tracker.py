"""Kalibrasyon değişiklik takibi (saf mantık, Qt yok).

Her parametre için dört ayrı değer ayrı tutulur ve karıştırılmaz:

* **baseline** – başlangıç referansı. A2L / kalibrasyon profilinde TANIMLI bir varsayılan varsa o
  (``source="a2l_default"``); yoksa oturum başında ECU'dan ilk okunan değer (``source="session_start"``).
  Varsayılan UYDURULMAZ; hangi referansın kullanıldığı ``baseline_label`` ile kullanıcıya gösterilir.
* **ecu** – ECU'da şu an uygulanmış olduğu bilinen değer (yazma doğrulanınca / yeniden okununca güncellenir).
* **edited** – kullanıcının düzenlediği ama ECU'ya HENÜZ yazılmamış değer (yoksa ``None``).
* **delta** – son uygulanan değişimin miktarı (yeni − eski).

Ok göstergesi yalnızca değişim gerçekten ECU'ya uygulandıktan sonra "yanıp sönen" olur; düzenlenmiş ama
yazılmamış değer ayrı bir durumdur (``pending``) ve uygulanmış gibi gösterilmez.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

ARROW_UP = "↑"
ARROW_DOWN = "↓"
BLINK_S = 1.5                   # ok bu süre yanıp söner; sonra sade (sabit) kalır
EPS = 1e-9

BASELINE_A2L = "a2l_default"
BASELINE_SESSION = "session_start"
BASELINE_LABELS = {
    BASELINE_A2L: "A2L varsayılanı",
    BASELINE_SESSION: "oturum başı ECU değeri",
}


def direction(old, new, eps: float = EPS) -> int:
    """+1 artış, -1 azalış, 0 değişmedi / karşılaştırılamaz (None, NaN, Inf)."""
    if not _finite(old) or not _finite(new):
        return 0
    d = float(new) - float(old)
    if abs(d) <= eps * max(1.0, abs(float(old))):
        return 0
    return 1 if d > 0 else -1


def format_delta(old, new, unit: str = "", with_arrow: bool = True) -> str:
    """``↑ +0.15`` / ``↓ -5`` biçimi; değişim yoksa boş metin. Gereksiz ondalık/kayan nokta artığı yok.
    ``with_arrow=False``: yalnızca ``+0.15 rpm`` (ok ayrı bir simge olarak çiziliyorsa)."""
    dr = direction(old, new)
    if dr == 0:
        return ""
    d = float(new) - float(old)
    text = _num(d)
    if d > 0:
        text = "+" + text
    arrow = ARROW_UP if dr > 0 else ARROW_DOWN
    suffix = f" {unit}" if unit else ""
    return f"{arrow} {text}{suffix}" if with_arrow else f"{text}{suffix}"


def _finite(v) -> bool:
    if v is None or isinstance(v, bool):
        return False
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _num(v: float) -> str:
    return f"{v:.6g}"


@dataclass
class ParamState:
    name: str
    unit: str = ""
    baseline: float | None = None
    baseline_source: str = BASELINE_SESSION
    ecu: float | None = None            # ECU'da uygulanmış son değer
    edited: float | None = None         # yazılmamış düzenleme
    last_old: float | None = None       # son uygulanan değişimin eski değeri
    last_new: float | None = None
    changed_at: float = 0.0             # son uygulanan değişimin zamanı (time.monotonic)
    last_write_ok: bool | None = None   # None: hiç yazılmadı
    last_error: str = ""
    writable: bool = True
    history_count: int = 0

    @property
    def status(self) -> str:
        """``pending`` (düzenlendi, yazılmadı) | ``failed`` | ``applied`` | ``clean``."""
        if self.edited is not None and direction(self.ecu, self.edited) != 0:
            return "pending"
        if self.last_write_ok is False:
            return "failed"
        if self.last_write_ok:
            return "applied"
        return "clean"


@dataclass
class ChangeTracker:
    """Oturum boyunca tüm parametrelerin durumunu tutar. İş parçacığı güvenli DEĞİL; GUI iş parçacığında
    kullanılır."""
    params: dict[str, ParamState] = field(default_factory=dict)

    def state(self, name: str, unit: str = "") -> ParamState:
        st = self.params.get(name)
        if st is None:
            st = self.params[name] = ParamState(name=name, unit=unit)
        elif unit and not st.unit:
            st.unit = unit
        return st

    # ---- referanslar ------------------------------------------------------------------
    def observe(self, name: str, value, unit: str = "", a2l_default=None, writable: bool = True):
        """ECU'dan okunan değeri bildirir. İlk okuma başlangıç referansını belirler (A2L varsayılanı
        tanımlıysa o; değilse bu ilk okuma). Sonraki okumalar yalnızca ``ecu`` değerini günceller: ECU'dan
        yeniden okuma, yazılmamış düzenlemeyi SİLMEZ ama artık ECU ile aynıysa bekleyen durumu temizler."""
        st = self.state(name, unit)
        st.writable = writable
        if not _finite(value):
            return st
        v = float(value)
        if st.baseline is None:
            if _finite(a2l_default):
                st.baseline, st.baseline_source = float(a2l_default), BASELINE_A2L
            else:
                st.baseline, st.baseline_source = v, BASELINE_SESSION
        elif a2l_default is not None and _finite(a2l_default) and st.baseline_source != BASELINE_A2L:
            st.baseline, st.baseline_source = float(a2l_default), BASELINE_A2L
        st.ecu = v
        if st.edited is not None and direction(v, st.edited) == 0:
            st.edited = None
        return st

    def baseline_label(self, name: str) -> str:
        st = self.params.get(name)
        if st is None or st.baseline is None:
            return "başlangıç referansı yok (ECU'dan okunmadı)"
        return BASELINE_LABELS.get(st.baseline_source, st.baseline_source)

    # ---- düzenleme / yazma --------------------------------------------------------------
    def edit(self, name: str, new_value, unit: str = "") -> ParamState:
        """Kullanıcı değeri değiştirdi; ECU'ya YAZILMADI."""
        st = self.state(name, unit)
        st.edited = float(new_value) if _finite(new_value) else None
        return st

    def discard_edit(self, name: str) -> float | None:
        """Yazılmamış düzenlemeyi geri alır; geri dönülen (ECU) değeri döner."""
        st = self.params.get(name)
        if st is None:
            return None
        st.edited = None
        return st.ecu

    def applied(self, name: str, old, new, unit: str = "", now: float | None = None) -> ParamState:
        """Değişim ECU'ya yazıldı ve (çağıran) doğruladı → uygulanmış sayılır, ok yanıp söner."""
        st = self.state(name, unit)
        st.last_old = float(old) if _finite(old) else None
        st.last_new = float(new) if _finite(new) else None
        st.ecu = st.last_new
        st.edited = None
        st.last_write_ok = True
        st.last_error = ""
        st.changed_at = time.monotonic() if now is None else now
        st.history_count += 1
        if st.baseline is None and st.last_old is not None:
            st.baseline, st.baseline_source = st.last_old, BASELINE_SESSION
        return st

    def failed(self, name: str, error: str = "", unit: str = "") -> ParamState:
        """Yazma başarısız: değer uygulanmış GÖSTERİLMEZ; düzenleme (varsa) bekleyen kalır."""
        st = self.state(name, unit)
        st.last_write_ok = False
        st.last_error = error
        return st

    # ---- görsel durum -----------------------------------------------------------------
    def arrow(self, name: str, now: float | None = None) -> tuple[str, str]:
        """(ok metni, mod): mod ``blink`` (≈1,5 sn) | ``steady`` | ``pending`` | ``''``.
        ``pending``: düzenlendi ama ECU'ya yazılmadı (ok ECU değerine göre yönü gösterir, uygulanmış değil)."""
        st = self.params.get(name)
        if st is None:
            return "", ""
        if st.status == "pending":
            dr = direction(st.ecu, st.edited)
            return (ARROW_UP if dr > 0 else ARROW_DOWN), "pending"
        dr = direction(st.last_old, st.last_new)
        if dr == 0 or st.last_write_ok is not True:
            return "", ""
        t = time.monotonic() if now is None else now
        mode = "blink" if t - st.changed_at < BLINK_S else "steady"
        return (ARROW_UP if dr > 0 else ARROW_DOWN), mode

    def delta_text(self, name: str, now: float | None = None, with_arrow: bool = True) -> str:
        st = self.params.get(name)
        if st is None:
            return ""
        if st.status == "pending":
            return format_delta(st.ecu, st.edited, st.unit, with_arrow)
        return format_delta(st.last_old, st.last_new, st.unit, with_arrow)

    def change_view(self, name: str, now: float | None = None) -> tuple[str, str, str, str]:
        """Arayüz için tek kaynak: ``(durum, ok, fark, mod)``.

        durum: ``pending`` (yazılmadı) | ``applied`` (ECU'ya yazıldı) | ``failed`` (yazma başarısız, ECU değişmedi)
        | ``""``. ``failed`` durumunda ok/fark BOŞTUR: ECU'da değişen bir şey yok, ok gösterilmemeli.
        ``fark`` ok içermez (ok ayrı simge); ``mod`` için bkz. ``arrow``."""
        st = self.params.get(name)
        if st is None:
            return "", "", "", ""
        if st.status == "failed":
            return "failed", "", "", ""
        arrow, mode = self.arrow(name, now)
        if not arrow:
            return "", "", "", ""
        return st.status, arrow, self.delta_text(name, now, with_arrow=False), mode

    def delta_from_baseline(self, name: str) -> str:
        st = self.params.get(name)
        if st is None or st.baseline is None:
            return ""
        cur = st.edited if st.edited is not None else st.ecu
        return format_delta(st.baseline, cur, st.unit)

    def summary(self, name: str) -> str:
        """Tooltip: ECU değeri, düzenlenen değer, başlangıç referansı (+kaynağı), son değişim, durum."""
        st = self.params.get(name)
        if st is None:
            return ""
        lines = []
        if st.ecu is not None:
            lines.append(f"ECU'daki değer: {_num(st.ecu)} {st.unit}".rstrip())
        if st.edited is not None:
            lines.append(f"Düzenlenen (yazılmadı): {_num(st.edited)} {st.unit}".rstrip())
        if st.baseline is not None:
            lines.append(f"Başlangıç ({self.baseline_label(name)}): {_num(st.baseline)} {st.unit}".rstrip())
        if st.last_new is not None and st.last_old is not None:
            lines.append(f"Son değişim: {_num(st.last_old)} → {_num(st.last_new)} "
                         f"({format_delta(st.last_old, st.last_new, st.unit)})")
        if st.last_write_ok is False:
            lines.append(f"Son yazma BAŞARISIZ: {st.last_error}")
        lines.append("Değiştirilebilir" if st.writable else "Salt okunur")
        return "\n".join(lines)

    # ---- geri alma hedefleri ----------------------------------------------------------
    def undo_targets(self) -> dict[str, float]:
        """Yazılmamış düzenlemeler için geri dönülecek ECU değerleri (ECU'ya yazma GEREKMEZ)."""
        return {n: st.ecu for n, st in self.params.items()
                if st.status == "pending" and st.ecu is not None}

    def default_targets(self, names=None) -> dict[str, float]:
        """Başlangıç referansına dönmek için yazılacak değerler (ECU'ya yazılması gerekir; yalnızca
        referansı olan, değiştirilebilir ve ECU değeri farklı olanlar). Referansı olmayan atlanır."""
        out = {}
        for n in (names if names is not None else list(self.params)):
            st = self.params.get(n)
            if st is None or st.baseline is None or not st.writable:
                continue
            cur = st.ecu if st.edited is None else st.edited
            if direction(st.baseline, cur) != 0:
                out[n] = st.baseline
        return out
