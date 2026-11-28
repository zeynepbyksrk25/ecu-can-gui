"""Çalışma Alanı için ortak sinyal deposu (Qt'den bağımsız, saf Python+numpy).

Kaynaklar (sinyal kimliği öneki):
  a2l:<ölçüm>        CCP ile okunan A2L ölçümleri
  dbc:<MESAJ>.<SİNYAL>  CAN'den çözülen DBC sinyalleri
  gauge:<anahtar>    Ana Sayfa gösterge sinyalleri (RPM, PLA ...)
  input:<anahtar>    Simülasyon girişleri (Throttle ...)
  math:<isim>        Kullanıcının tanımladığı matematik sinyalleri
  csv:<dosya>:<ad>   İçe aktarılan kayıtlar (salt okunur)

Her sinyal (zaman, değer) dizisidir; zaman, hub başlangıcına (t0) göre
saniyedir. Yalnızca "etkin" (bir panelde kullanılan) sinyaller saklanır; böylece
yüzlerce DBC sinyali bellek/CPU tüketmez.

Matematik sinyalleri (türetilmiş):
  scale   : y = gain * x + offset
  op      : y = A (+,-,*,/) B   (B'nin son bilinen değeriyle, "sample & hold")
  movavg  : y = son `window` saniyenin ortalaması
Tanım değişince veya sinyal eklenince mevcut geçmişe de uygulanır.
"""
from __future__ import annotations

import csv
import math
import time

import numpy as np

MAX_POINTS = 60000
OPS = {"+": np.add, "-": np.subtract, "*": np.multiply, "/": np.divide}
OP_LABELS = {"+": "A + B", "-": "A − B", "*": "A × B", "/": "A ÷ B"}


def kind_of(sig_id: str) -> str:
    return sig_id.split(":", 1)[0] if ":" in sig_id else ""


def label_of(sig_id: str) -> str:
    """Ekranda gösterilecek kısa ad."""
    k = kind_of(sig_id)
    rest = sig_id.split(":", 1)[1] if ":" in sig_id else sig_id
    if k == "dbc":
        return rest.split(".", 1)[1] if "." in rest else rest
    if k == "csv":
        return rest.split(":", 1)[1] if ":" in rest else rest
    return rest


class _Series:
    __slots__ = ("t", "v")

    def __init__(self):
        self.t: list[float] = []
        self.v: list[float] = []

    def append(self, t: float, v: float):
        self.t.append(t)
        self.v.append(v)
        if len(self.t) > MAX_POINTS + 2000:      # toplu kırpma (amortize)
            del self.t[:2000]
            del self.v[:2000]

    def arrays(self):
        return np.asarray(self.t, dtype=float), np.asarray(self.v, dtype=float)


class SignalHub:
    def __init__(self):
        self.t0 = time.time()
        self._series: dict[str, _Series] = {}
        self._last: dict[str, float] = {}
        self._active: set[str] = set()
        self.derived: dict[str, dict] = {}       # "math:isim" -> spec
        self.static: set[str] = set()            # csv: vb. (yeniden etkinleştirmeden saklanır)
        self._recomputing: set[str] = set()
        self.tap = None                          # callable(sid, değer): etkin olsun olmasın her dış örnek (oturum kaydı)
        self.on_active = None                    # callable(): etkin küme değişti (DBC çözümleme tablosu yenilenir)

    # ------------------------------------------------------------ zaman
    def now(self) -> float:
        return time.time() - self.t0

    # ------------------------------------------------------------ etkin küme
    def set_active(self, ids):
        """Panellerde kullanılan sinyaller. Türetilmişlerin kaynakları da etkin sayılır."""
        want = set(ids)
        for sid in list(want):
            want |= self._deps(sid)
        self._active = want
        for sid in want:
            self._series.setdefault(sid, _Series())
        if self.on_active is not None:
            self.on_active()

    def active(self) -> set:
        return set(self._active)

    def sources_needed(self) -> set:
        """Dış kaynaktan (CCP/CAN/...) beslenmesi gereken etkin kimlikler."""
        return {s for s in self._active if kind_of(s) not in ("math", "csv")}

    def _deps(self, sid: str, seen=None) -> set:
        seen = seen or set()
        spec = self.derived.get(sid)
        out = set()
        if spec is None or sid in seen:
            return out
        seen.add(sid)
        for key in ("src", "src2"):
            s = spec.get(key)
            if s:
                out.add(s)
                out |= self._deps(s, seen)
        return out

    # ------------------------------------------------------------ yazma
    def push(self, sid: str, value, t: float | None = None):
        if sid in self.static:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if not math.isfinite(v):                  # NaN ve ±inf: grafiğe / matematik sinyallerine taşınmasın
            return
        if self.tap is not None and kind_of(sid) not in ("math", "csv"):
            try:
                self.tap(sid, v)
            except Exception:                     # noqa: BLE001 - kayıt hatası canlı akışı bozmasın
                pass
        if sid not in self._active:
            return
        t = self.now() if t is None else t
        ser = self._series.setdefault(sid, _Series())
        ser.append(t, v)
        self._last[sid] = v
        self._propagate(sid, t, v)

    def _propagate(self, sid: str, t: float, v: float, depth: int = 0):
        if depth > 4:
            return
        for name, spec in self.derived.items():
            if name not in self._active:
                continue
            if spec.get("src") != sid and spec.get("src2") != sid:
                continue
            # op: yalnızca A geldiğinde örnek üret (B tutulur)
            if spec["kind"] == "op" and spec.get("src") != sid:
                continue
            y = self._eval_point(spec, t, v)
            if y is None:
                continue
            self._series.setdefault(name, _Series()).append(t, y)
            self._last[name] = y
            self._propagate(name, t, y, depth + 1)

    def _eval_point(self, spec: dict, t: float, a: float):
        k = spec["kind"]
        if k == "scale":
            return spec.get("gain", 1.0) * a + spec.get("offset", 0.0)
        if k == "op":
            b = self._last.get(spec.get("src2"))
            if b is None:
                return None
            if spec["op"] == "/" and b == 0:
                return None
            return float(OPS[spec["op"]](a, b))
        if k == "movavg":
            ser = self._series.get(spec["src"])
            if ser is None or not ser.t:
                return a
            w = max(float(spec.get("window", 1.0)), 1e-6)
            i = len(ser.t) - 1
            total, n = 0.0, 0
            while i >= 0 and ser.t[i] >= t - w:
                total += ser.v[i]
                n += 1
                i -= 1
            return total / n if n else a
        return None

    # ------------------------------------------------------------ okuma
    def get(self, sid: str, t_min: float | None = None):
        """(t, v) numpy dizileri; t_min verilirse yalnızca o zamandan sonrası."""
        ser = self._series.get(sid)
        if ser is None or not ser.t:
            return np.empty(0), np.empty(0)
        if t_min is not None:
            # t artan sıralı: ikili arama ile kes
            import bisect
            i = bisect.bisect_left(ser.t, t_min)
            return (np.asarray(ser.t[i:], dtype=float), np.asarray(ser.v[i:], dtype=float))
        return ser.arrays()

    def last(self, sid: str):
        return self._last.get(sid)

    def has_data(self, sid: str) -> bool:
        ser = self._series.get(sid)
        return bool(ser and ser.t)

    def all_ids_with_data(self) -> list:
        return [s for s, ser in self._series.items() if ser.t]

    def clear_live(self):
        """Canlı kaydı siler ve zamanı sıfırlar (içe aktarılanlar ve tanımlar kalır)."""
        for sid in list(self._series):
            if sid in self.static:
                continue
            self._series[sid] = _Series()
        self._last = {k: v for k, v in self._last.items() if k in self.static}
        self.t0 = time.time()

    # ------------------------------------------------------------ matematik
    def would_cycle(self, sid: str, spec: dict) -> bool:
        """``sid`` bu ``spec`` ile tanımlanırsa kendi kendine (doğrudan ya da başka türetilmiş sinyaller üzerinden)
        bağımlı olur mu? (A = B + 1, B = A + 1 gibi döngüler sonsuz özyinelemeye yol açar.)"""
        sid = sid if sid.startswith("math:") else f"math:{sid}"
        seen: set = set()
        stack = [s for s in (spec.get("src"), spec.get("src2")) if s]
        while stack:
            cur = stack.pop()
            if cur == sid:
                return True
            if cur in seen:
                continue
            seen.add(cur)
            sub = self.derived.get(cur)
            if sub is not None:
                stack += [s for s in (sub.get("src"), sub.get("src2")) if s]
        return False

    def define_derived(self, name: str, spec: dict):
        """name 'math:' önekli ya da öneksiz verilebilir; kimliği döner. Döngüsel bağımlılık ValueError."""
        sid = name if name.startswith("math:") else f"math:{name}"
        if self.would_cycle(sid, spec):
            raise ValueError(f"'{name}' kendisine bağımlı olurdu (döngüsel bağımlılık).")
        self.derived[sid] = dict(spec)
        self.recompute(sid)
        return sid

    def remove_derived(self, sid: str):
        self.derived.pop(sid, None)
        self._series.pop(sid, None)
        self._last.pop(sid, None)
        self._active.discard(sid)

    def recompute(self, sid: str):
        """Türetilmiş sinyali, kaynakların mevcut geçmişinden baştan hesaplar."""
        spec = self.derived.get(sid)
        if spec is None or sid in self._recomputing:      # döngüsel tanım (örn. dosyadan yüklenen) sonsuz özyineleme yapmasın
            return
        self._recomputing.add(sid)
        try:
            self._recompute(sid, spec)
        finally:
            self._recomputing.discard(sid)

    def _recompute(self, sid: str, spec: dict):
        ser = _Series()
        ta, va = self._source_arrays(spec.get("src"))
        if ta.size:
            k = spec["kind"]
            if k == "scale":
                y = spec.get("gain", 1.0) * va + spec.get("offset", 0.0)
                ser.t, ser.v = ta.tolist(), y.tolist()
            elif k == "op":
                tb, vb = self._source_arrays(spec.get("src2"))
                if tb.size:
                    idx = np.searchsorted(tb, ta, side="right") - 1
                    ok = idx >= 0
                    b = vb[np.clip(idx, 0, None)]
                    if spec["op"] == "/":
                        ok &= (b != 0)
                    with np.errstate(all="ignore"):
                        y = OPS[spec["op"]](va, b)
                    ser.t, ser.v = ta[ok].tolist(), y[ok].tolist()
            elif k == "movavg":
                w = max(float(spec.get("window", 1.0)), 1e-6)
                csum = np.concatenate(([0.0], np.cumsum(va)))
                lo = np.searchsorted(ta, ta - w, side="left")
                n = np.arange(1, ta.size + 1) - lo
                y = (csum[1:] - csum[lo]) / np.maximum(n, 1)
                ser.t, ser.v = ta.tolist(), y.tolist()
        self._series[sid] = ser
        if ser.v:
            self._last[sid] = ser.v[-1]
        # bu sinyale bağlı olanlar da yeniden hesaplanır
        for other, ospec in self.derived.items():
            if other != sid and sid in (ospec.get("src"), ospec.get("src2")):
                self.recompute(other)

    def _source_arrays(self, sid):
        if not sid:
            return np.empty(0), np.empty(0)
        return self.get(sid)

    # ------------------------------------------------------------ içe/dışa aktarım
    def export_csv(self, path: str, ids=None):
        """Uzun biçim: time,signal,value (her sinyal kendi zaman damgalarıyla)."""
        ids = list(ids) if ids is not None else self.all_ids_with_data()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["time", "signal", "value"])
            for sid in ids:
                t, v = self.get(sid)
                for ti, vi in zip(t, v):
                    w.writerow([f"{ti:.4f}", sid, f"{vi:.9g}"])
        return len(ids)

    def import_csv(self, path: str, tag: str) -> list:
        """Uzun (time,signal,value) veya geniş (ilk sütun zaman) CSV'yi içe aktarır.
        Sinyaller 'csv:<tag>:<ad>' olarak eklenir; eklenen kimlikleri döner."""
        added: dict[str, _Series] = {}
        with open(path, newline="", encoding="utf-8-sig") as f:
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
            except csv.Error:
                dialect = csv.excel
            rows = list(csv.reader(f, dialect))
        if len(rows) < 2:
            raise ValueError("CSV boş ya da tek satırlık.")
        head = [h.strip() for h in rows[0]]

        def num(x):
            return float(str(x).strip().replace(",", ".")) if str(x).strip() != "" else None

        if [h.lower() for h in head[:3]] == ["time", "signal", "value"]:
            for r in rows[1:]:
                if len(r) < 3:
                    continue
                try:
                    t, v = num(r[0]), num(r[2])
                except ValueError:
                    continue
                if t is None or v is None:
                    continue
                name = r[1].strip()
                sid = f"csv:{tag}:{name}"
                added.setdefault(sid, _Series()).append(t, v)
        else:
            for r in rows[1:]:
                try:
                    t = num(r[0])
                except (ValueError, IndexError):
                    continue
                if t is None:
                    continue
                for j in range(1, min(len(r), len(head))):
                    try:
                        v = num(r[j])
                    except ValueError:
                        continue
                    if v is None:
                        continue
                    added.setdefault(f"csv:{tag}:{head[j]}", _Series()).append(t, v)
        if not added:
            raise ValueError("CSV'de sayısal sinyal bulunamadı.")
        for sid, ser in added.items():
            self._series[sid] = ser
            self.static.add(sid)
            self._active.add(sid)
            if ser.v:
                self._last[sid] = ser.v[-1]
        return list(added)

    def remove_static(self, sid: str):
        self.static.discard(sid)
        self._series.pop(sid, None)
        self._last.pop(sid, None)
        self._active.discard(sid)
