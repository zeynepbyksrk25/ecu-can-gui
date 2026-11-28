"""WP / RP (Work page / Reference page) modeli — SAF mantık, arayüz ve CCP içermez.

Modas'ta WP = ECU'nun RAM veri seti, RP = Flaş (referans) veri seti ve ikisi arasında ``COPY`` vardır. Bu projenin CCP
istemcisinde ``SELECT_CAL_PAGE`` / ``COPY_CAL_PAGE`` komutları YOKTUR ve Flaş yazma gerçek M220'de doğrulanmamıştır;
bu yüzden RP burada **uygulama düzeyinde** modellenir: "ECU'dan veri oku" / ``COPY WP→RP`` ile alınmış, çalışma
alanındaki etiketlerin değerlerinin yerel referans görüntüsüdür. ``Diff`` = WP ile RP arasında farklı etiket sayısı.

Değer türleri: tek değer → ``float``; tablo → ``list[list[float | None]]``.
"""

from __future__ import annotations

import math

TOLERANCE = 1e-9
WP = "WP"
RP = "RP"


def _same(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, list) or isinstance(b, list):
        if not (isinstance(a, list) and isinstance(b, list)) or len(a) != len(b):
            return False
        return all(_same(x, y) for x, y in zip(a, b))
    try:
        return math.isclose(float(a), float(b), rel_tol=1e-9, abs_tol=TOLERANCE)
    except (TypeError, ValueError):
        return a == b


def _copy(value):
    return [list(r) for r in value] if isinstance(value, list) else value


class PageModel:
    """Referans görüntüsü ve fark hesabı."""

    def __init__(self):
        self.active = WP
        self.reference: dict = {}

    def has_reference(self) -> bool:
        return bool(self.reference)

    def set_active(self, page: str) -> bool:
        """WP ↔ RP gösterim geçişi; değiştiyse True."""
        if page not in (WP, RP) or page == self.active:
            return False
        self.active = page
        return True

    def toggle(self) -> str:
        self.active = RP if self.active == WP else WP
        return self.active

    def copy_wp_to_rp(self, wp: dict) -> int:
        """RP'yi verilen WP görüntüsüyle değiştirir; alınan etiket sayısını döner."""
        self.reference = {k: _copy(v) for k, v in wp.items() if v is not None}
        return len(self.reference)

    def adopt_missing(self, wp: dict) -> int:
        """RP'de olmayan etiketleri (yeni eklenen) mevcut WP değeriyle tamamlar — mevcut referanslara dokunmaz."""
        added = 0
        for k, v in wp.items():
            if v is not None and k not in self.reference:
                self.reference[k] = _copy(v)
                added += 1
        return added

    def diff_names(self, wp: dict) -> list:
        """Hem WP'de hem RP'de bulunup değeri farklı olan etiketler (sıralı)."""
        return sorted(k for k, ref in self.reference.items() if k in wp and wp[k] is not None and not _same(wp[k], ref))

    def diff_count(self, wp: dict) -> int:
        return len(self.diff_names(wp))

    def restore_plan(self, wp: dict) -> dict:
        """RP→WP için yazılacak {etiket: referans değeri} (yalnızca farklı olanlar)."""
        return {k: _copy(self.reference[k]) for k in self.diff_names(wp)}

    def forget(self, name: str):
        self.reference.pop(name, None)

    def clear(self):
        self.reference.clear()
