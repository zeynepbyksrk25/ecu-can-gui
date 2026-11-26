"""Modas Sport tarzı değişken türü simgeleri (Variable list).

Modas'taki dört simge çizimle taklit edilir (bitmap dosyası gerekmez, ölçek/tema dostu):

* ``value`` — mavi "≡": tekil ayar değeri (kalibrasyon, düzenlenebilir)
* ``meas``  — kırmızı yukarı ok: ölçüm (salt okunur)
* ``curve`` — eksenli çizgi grafiği: eğri (1B)
* ``map``   — eğik ızgara yüzey: harita (2B)
* ``text``  — turuncu "T": metin alanı
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

from app import theme

SIZE = 16
_BLUE = "#2F6FB5"
_RED = "#D2362B"
_NAVY = "#1F3A66"
_cache: dict[str, QIcon] = {}


def _draw_value(p: QPainter):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_BLUE))
    for y in (3.5, 7.0, 10.5):                       # üç yatay çubuk (≡)
        p.drawRoundedRect(QRectF(2, y, 12, 2.2), 0.8, 0.8)
    p.setBrush(QColor(_NAVY))
    p.drawRect(QRectF(2, 14, 12, 1.2))               # taban çizgisi


def _draw_meas(p: QPainter):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(_RED))
    p.drawPolygon(QPolygonF([QPointF(8, 1.5), QPointF(13, 7.5), QPointF(9.6, 7.5),
                             QPointF(9.6, 11.5), QPointF(6.4, 11.5), QPointF(6.4, 7.5), QPointF(3, 7.5)]))
    p.setBrush(QColor(_NAVY))
    p.drawRect(QRectF(3, 13.4, 10, 1.4))             # taban (ölçüm "çubuğu")


def _draw_curve(p: QPainter):
    p.setPen(QPen(QColor(_NAVY), 1.2))
    p.drawLine(QPointF(2.5, 2), QPointF(2.5, 13.5))   # eksenler
    p.drawLine(QPointF(2.5, 13.5), QPointF(14, 13.5))
    p.setPen(QPen(QColor(_BLUE), 1.8, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline(QPolygonF([QPointF(4, 11.5), QPointF(7, 8.5), QPointF(9.5, 9.5), QPointF(13.5, 3.5)]))


def _draw_map(p: QPainter):
    p.setPen(QPen(QColor(_NAVY), 1.0))
    p.setBrush(QColor("#9DB9E3"))
    p.drawPolygon(QPolygonF([QPointF(1.5, 11), QPointF(10, 14.5), QPointF(14.5, 8), QPointF(6, 4.5)]))   # yüzey
    p.setPen(QPen(QColor(_BLUE), 0.9))
    for t in (0.33, 0.66):                           # ızgara çizgileri
        a, b = QPointF(1.5 + 8.5 * t, 11 + 3.5 * t), QPointF(6 + 8.5 * t, 4.5 + 3.5 * t)
        p.drawLine(a, b)
        c, d = QPointF(1.5 + 4.5 * t, 11 - 6.5 * t), QPointF(10 + 4.5 * t, 14.5 - 6.5 * t)
        p.drawLine(c, d)
    p.setPen(QPen(QColor(_NAVY), 1.2))
    p.drawLine(QPointF(1.5, 11), QPointF(1.5, 2))     # Z ekseni


def _draw_text(p: QPainter):
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(theme.ORANGE))
    p.drawRect(QRectF(2.5, 2.5, 11, 2.6))             # "T"
    p.drawRect(QRectF(6.7, 2.5, 2.6, 11.5))


_DRAWERS = {"value": _draw_value, "meas": _draw_meas, "curve": _draw_curve, "map": _draw_map, "text": _draw_text}


def kind_icon(kind: str) -> QIcon:
    """``classify()`` türü için (meas|value|curve|map|text) simge; önbelleğe alınır. QApplication gerekir."""
    kind = kind if kind in _DRAWERS else "meas"
    if kind not in _cache:
        scale = 2                                      # yüksek DPI'da keskin kalsın
        pm = QPixmap(SIZE * scale, SIZE * scale)
        pm.setDevicePixelRatio(scale)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        _DRAWERS[kind](p)
        p.end()
        _cache[kind] = QIcon(pm)
    return _cache[kind]
