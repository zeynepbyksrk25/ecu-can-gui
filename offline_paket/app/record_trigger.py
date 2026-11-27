"""Tetikleyici ile otomatik kayıt mantığı (saf Python; docs/GOREV.md 6.2): eşik, hata sayacı artışı, durum geçişi,
pre-trigger (tetik öncesi) ve post-trigger (tetik sonrası) veri.

Akış: ``TriggerEngine.feed(sid, value, t)`` her örnekte çağrılır; tetik oluşunca ``fired`` olur ve pre-trigger tamponu
(``pre_s`` saniyelik son örnekler) ``take_pre_buffer()`` ile kayda yazılmak üzere verilir; ``post_s`` sonra
``should_stop(t)`` True olur. Eşik değerleri KULLANICIDAN gelir; varsayılan eşik yoktur.
NOT: Bu modül arayüze/MainWindow'a henüz BAĞLANMADI (bkz. docs/PROGRESS.md)."""
from __future__ import annotations

import math
import operator
from collections import deque
from dataclasses import dataclass

OPS = {">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne}
THRESHOLD, COUNTER_INCREASE, TRANSITION = "threshold", "counter_increase", "transition"


@dataclass
class Trigger:
    kind: str
    signal: str
    op: str = ">"               # eşik için
    value: float = 0.0          # eşik değeri / artış miktarı (counter_increase: en az bu kadar artış)
    from_value: float | None = None   # geçiş için (None: herhangi bir değerden)
    to_value: float | None = None     # geçiş için (None: herhangi bir değişim)
    name: str = ""

    def validate(self):
        if self.kind not in (THRESHOLD, COUNTER_INCREASE, TRANSITION):
            raise ValueError(f"Bilinmeyen tetik türü: {self.kind}")
        if not self.signal:
            raise ValueError("Tetik sinyali boş")
        if self.kind == THRESHOLD and (self.op not in OPS or not math.isfinite(self.value)):
            raise ValueError("Eşik tetiği için geçerli op ve sonlu değer gerekir")
        if self.kind == COUNTER_INCREASE and not (math.isfinite(self.value) and self.value > 0):
            raise ValueError("Sayaç tetiği için pozitif artış miktarı gerekir")


class TriggerEngine:
    def __init__(self, triggers: list, pre_s: float = 5.0, post_s: float = 10.0, max_buffer: int = 200_000):
        for t in triggers:
            t.validate()
        self.triggers = list(triggers)
        self.pre_s, self.post_s = max(0.0, pre_s), max(0.0, post_s)
        self._buf: deque = deque(maxlen=max_buffer)
        self._last: dict = {}
        self.armed = True
        self.fired: Trigger | None = None
        self.fired_at: float | None = None
        self.fire_value: float | None = None

    def rearm(self):
        self.armed, self.fired, self.fired_at, self.fire_value = True, None, None, None
        self._buf.clear()

    def feed(self, sid: str, value, t: float) -> Trigger | None:
        """Örneği tampona ekler ve tetikleri değerlendirir; bu çağrıda tetik oluştuysa onu döner."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(v):
            return None                      # NaN/Inf tetik üretmez, tampona girmez
        if self.fired is None:
            self._buf.append((t, sid, v))
            while self._buf and t - self._buf[0][0] > self.pre_s:
                self._buf.popleft()
        prev = self._last.get(sid)
        self._last[sid] = v
        if not self.armed or self.fired is not None:
            return None
        for trg in self.triggers:
            if trg.signal != sid:
                continue
            hit = False
            if trg.kind == THRESHOLD:
                hit = OPS[trg.op](v, trg.value) and (prev is None or not OPS[trg.op](prev, trg.value))   # kenar tetik
            elif trg.kind == COUNTER_INCREASE:
                hit = prev is not None and v - prev >= trg.value
            elif trg.kind == TRANSITION:
                if prev is not None and prev != v:
                    hit = (trg.from_value is None or prev == trg.from_value) and (trg.to_value is None or v == trg.to_value)
            if hit:
                self.fired, self.fired_at, self.fire_value = trg, t, v
                return trg
        return None

    def take_pre_buffer(self) -> list:
        """Tetik anına kadarki (pre_s) örnekler (t, sinyal, değer); kayda geriye dönük yazılır."""
        return [x for x in self._buf if self.fired_at is None or x[0] <= self.fired_at]

    def should_stop(self, t: float) -> bool:
        return self.fired is not None and self.fired_at is not None and t - self.fired_at >= self.post_s
