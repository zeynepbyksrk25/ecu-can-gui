"""Modas "Gösterge" penceresi: bir A2L ölçümünü ibreli gösterge olarak gösterir (Test Tezgâhı göstergeleriyle aynı ``DashGauge``).

Ölçüm turu (F9) değeri ``set_value`` ile besler; pencere ECU ile konuşmaz. Kadran aralığı A2L'deki alt/üst sınırdan alınır;
A2L'de sınır yoksa aralık UYDURULMAZ: görülen değerlere göre kendiliğinden genişler (kullanıcı bunu başlıkta görür)."""
from __future__ import annotations

import math

from app import theme
from app.ui.dash_widgets import DashGauge
from app.ui.modas.windows import ModasSub


class GaugeWindow(ModasSub):
    def __init__(self, obj):
        super().__init__(obj.name, theme.ACCENT)
        self.obj = obj
        lo, hi = getattr(obj, "minimum", None), getattr(obj, "maximum", None)
        self.fixed_range = lo is not None and hi is not None and hi > lo
        self.gauge = DashGauge(float(lo) if self.fixed_range else 0.0, float(hi) if self.fixed_range else 1.0,
                               getattr(obj, "unit", "") or "", label=obj.name)
        self._seen: list = []
        self.setWidget(self.gauge)
        self.resize(240, 230)
        self.setToolTip(obj.name + ("" if self.fixed_range else "\nA2L'de sınır yok: aralık görülen değerlere göre genişler"))

    def set_value(self, value):
        """Ölçüm değeri (sayı değilse / sonlu değilse gösterge boş kalır)."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            v = None
        if v is None or not math.isfinite(v):
            self.gauge.set_value(None)
            return
        if not self.fixed_range:
            self._seen.append(v)
            lo, hi = min(min(self._seen), 0.0), max(self._seen)
            if hi <= lo:
                hi = lo + 1.0
            self.gauge.set_range(lo, hi)
        self.gauge.set_value(v)

    @property
    def value(self):
        return self.gauge._value

    def state(self) -> dict:
        return {"kind": "gauge", "name": self.label, "geom": self.geometry_state()}
