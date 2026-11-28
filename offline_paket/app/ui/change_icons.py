"""Değişiklik göstergesi için kırmızı yön okları (artış ↑ / azalış ↓). Renk her iki yönde kırmızı;
yön yalnızca ok biçimiyle ayrılır (bkz. docs/GOREV.md 2.1)."""
from app import theme
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

ARROW_COLOR = QColor(theme.DANGER)
PENDING_COLOR = QColor(theme.WARN_INK)
_cache: dict[tuple[bool, int, bool], QIcon] = {}


def arrow_icon(up: bool, size: int = 14, hollow: bool = False) -> QIcon:
    """Dolu kırmızı ok: değişiklik ECU'ya UYGULANDI. ``hollow=True``: içi boş (konturlu) amber ok: düzenlendi ama
    HENÜZ yazılmadı (bekleyen); iki durum şekilden de ayırt edilir (renk körlüğü)."""
    key = (up, size, hollow)
    icon = _cache.get(key)
    if icon is not None:
        return icon
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if hollow:
        p.setPen(QPen(PENDING_COLOR, max(1.0, size / 12)))
        p.setBrush(Qt.NoBrush)
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(ARROW_COLOR)
    m = size * 0.12
    w = size - 2 * m
    cx = size / 2
    if up:
        pts = [QPointF(cx, m), QPointF(m + w, m + w * 0.55), QPointF(cx + w * 0.18, m + w * 0.55),
               QPointF(cx + w * 0.18, size - m), QPointF(cx - w * 0.18, size - m),
               QPointF(cx - w * 0.18, m + w * 0.55), QPointF(m, m + w * 0.55)]
    else:
        pts = [QPointF(cx, size - m), QPointF(m + w, size - m - w * 0.55), QPointF(cx + w * 0.18, size - m - w * 0.55),
               QPointF(cx + w * 0.18, m), QPointF(cx - w * 0.18, m),
               QPointF(cx - w * 0.18, size - m - w * 0.55), QPointF(m, size - m - w * 0.55)]
    p.drawPolygon(QPolygonF(pts))
    p.end()
    icon = QIcon(pm)
    _cache[key] = icon
    return icon
