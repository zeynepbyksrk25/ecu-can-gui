"""Ölçüm turu istatistiği (Qt'siz): gerçek okuma hızı, geciken turlar ve başarısız okumalar.

``tick`` her tur başında çağrılır; önceki turdan bu yana geçen süre ``eşik × periyot``'u aşarsa tur *gecikmiş* sayılır
(arayüz / ECU yetişemedi). ``read(False)`` ECU'dan okunamayan her değeri sayar. Hiçbir değer tahmin edilmez.
"""
from __future__ import annotations

from collections import deque

LATE_FACTOR = 1.5
MEASURE_INTERVAL_MS = 250          # varsayılan ölçüm periyodu
INTERVAL_CHOICES_MS = (50, 100, 250, 500, 1000, 2000)


class MeasureStats:
    def __init__(self, window: int = 20):
        self._stamps: deque = deque(maxlen=window)
        self.late = 0
        self.failed = 0
        self.reads = 0

    def reset(self) -> None:
        self._stamps.clear()
        self.late = self.failed = self.reads = 0

    def tick(self, now: float, interval_s: float) -> None:
        if self._stamps and now - self._stamps[-1] > LATE_FACTOR * interval_s:
            self.late += 1
        self._stamps.append(now)

    def read(self, ok: bool) -> None:
        self.reads += 1
        if not ok:
            self.failed += 1

    @property
    def rate_hz(self) -> float | None:
        """Son turlardan ölçülen gerçek tur hızı; en az iki tur yoksa ``None``."""
        if len(self._stamps) < 2:
            return None
        span = self._stamps[-1] - self._stamps[0]
        return (len(self._stamps) - 1) / span if span > 0 else None

    @property
    def skipped(self) -> int:
        """Atlanan okuma: geciken turlar + okunamayan değerler."""
        return self.late + self.failed
