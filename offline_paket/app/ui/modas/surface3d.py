"""Harita / eğri için 3B yüzey görünümü (salt okunur): sürükleyerek döndürülür, tekerlekle yakınlaştırılır.

Yalnızca QPainter kullanır (OpenGL / ek kütüphane yok). Yüzey, ``TableWindow`` tablosunun o anki değerlerinden çizilir;
ECU'ya hiçbir şey yazılmaz. Renk, ısı haritasıyla aynıdır. Eksen değerleri A2L'de biliniyorsa eksen uçları yazılır,
bilinmiyorsa hücre indeksi kullanılır (değer uydurulmaz).
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout, QWidget

from app import theme
from app.ui.modas.windows import format_phys, heat_color


def project(x: float, y: float, z: float, yaw: float, pitch: float) -> tuple[float, float, float]:
    """Birim küp koordinatını (-0.5..0.5) döndürüp ekrana izdüşürür: (sx, sy, derinlik). Derinlik büyük = uzak."""
    cy, sy_ = math.cos(yaw), math.sin(yaw)
    x1, y1 = x * cy - y * sy_, x * sy_ + y * cy
    cp, sp = math.cos(pitch), math.sin(pitch)
    return x1, -(z * cp - y1 * sp), y1 * cp + z * sp


def finite_range(grid: list) -> tuple[float, float] | None:
    vals = [v for row in grid for v in row if v is not None and math.isfinite(v)]
    return (min(vals), max(vals)) if vals else None


def quads(grid: list, yaw: float, pitch: float) -> list:
    """Yüzey dörtgenleri, uzaktan yakına sıralı: ``[(derinlik, [(sx, sy)*4], ortalama değer)]``. Eksik (None) hücreli
    dörtgenler atlanır."""
    rng = finite_range(grid)
    rows = len(grid)
    cols = len(grid[0]) if rows else 0
    if rng is None or rows < 2 or cols < 2:
        return []
    lo, hi = rng
    span = (hi - lo) or 1.0
    pts = {}
    for r in range(rows):
        for c in range(cols):
            v = grid[r][c]
            if v is None or not math.isfinite(v):
                continue
            pts[(r, c)] = project(c / (cols - 1) - 0.5, r / (rows - 1) - 0.5, (v - lo) / span - 0.5, yaw, pitch)
    out = []
    for r in range(rows - 1):
        for c in range(cols - 1):
            cell = [pts.get(k) for k in ((r, c), (r, c + 1), (r + 1, c + 1), (r + 1, c))]
            if any(p is None for p in cell):
                continue
            avg = sum(grid[r + dr][c + dc] for dr, dc in ((0, 0), (0, 1), (1, 1), (1, 0))) / 4
            out.append((sum(p[2] for p in cell) / 4, [(p[0], p[1]) for p in cell], avg))
    out.sort(key=lambda q: -q[0])                  # ressam algoritması: uzak olan önce
    return out


class _Canvas(QWidget):
    def __init__(self):
        super().__init__()
        self.grid: list = []
        self.axis_labels: tuple = ("X", "Y", None, None)   # (x adı, y adı, x uçları, y uçları); uçlar yalnızca A2L'de biliniyorsa
        self.yaw, self.pitch, self.zoom = -0.6, 0.9, 1.0
        self._last = None
        self.setMinimumSize(420, 320)

    def mousePressEvent(self, ev):  # noqa: N802
        self._last = ev.position()

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self._last is not None and ev.buttons() & Qt.LeftButton:
            d = ev.position() - self._last
            self._last = ev.position()
            self.yaw += d.x() * 0.01
            self.pitch = min(1.5, max(-0.2, self.pitch + d.y() * 0.01))
            self.update()

    def wheelEvent(self, ev):  # noqa: N802
        self.zoom = min(4.0, max(0.4, self.zoom * (1.1 if ev.angleDelta().y() > 0 else 1 / 1.1)))
        self.update()

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(theme.MODAS_RIBBON_BG))
        rng = finite_range(self.grid)
        if rng is None or len(self.grid) < 2 or len(self.grid[0]) < 2:
            p.setPen(QColor("#555"))
            p.drawText(self.rect(), Qt.AlignCenter, "3B görünüm için en az 2×2 dolu hücre gerekir")
            return
        scale = min(self.width(), self.height()) * 0.55 * self.zoom
        cx, cy = self.width() / 2, self.height() / 2
        p.setPen(QPen(QColor(60, 60, 60, 120), 0.6))
        for _d, poly, avg in quads(self.grid, self.yaw, self.pitch):
            p.setBrush(heat_color(avg, *rng))
            p.drawPolygon(QPolygonF([QPointF(cx + x * scale, cy + y * scale) for x, y in poly]))
        p.setPen(QColor("#333"))
        p.drawText(8, 16, f"Z: {format_phys(rng[0])} … {format_phys(rng[1])}")
        xn, yn, xr, yr = self.axis_labels
        p.drawText(8, 32, f"X: {xn}" + (f" {format_phys(xr[0])} … {format_phys(xr[1])}" if xr else " (indeks)"))
        if len(self.grid) > 1:
            p.drawText(8, 48, f"Y: {yn}" + (f" {format_phys(yr[0])} … {format_phys(yr[1])}" if yr else " (indeks)"))
        for name, (px, py, pz) in (("x₀", (-0.5, -0.5, -0.5)), ("x₁", (0.5, -0.5, -0.5)), ("y₁", (-0.5, 0.5, -0.5))):
            sx, sy, _d = project(px, py, pz, self.yaw, self.pitch)
            p.drawText(QPointF(cx + sx * scale + 4, cy + sy * scale + 12), name)


class Surface3DDialog(QDialog):
    """``TableWindow`` için yüzey penceresi; tablo değişince kendiliğinden güncellenir."""

    def __init__(self, table_window, parent=None):
        super().__init__(parent)
        self.tw = table_window
        self.setWindowTitle(f"3B görünüm — {table_window.label}")
        self.canvas = _Canvas()
        self.canvas.axis_labels = self._axis_labels()
        self.hint = QLabel("Sürükle: döndür · Tekerlek: yakınlaştır · Salt okunur")
        self.hint.setObjectName("modasWinUnit")
        reset = QPushButton("Görünümü sıfırla")
        reset.clicked.connect(self.reset_view)
        lay = QVBoxLayout(self)
        lay.addWidget(self.canvas, 1)
        lay.addWidget(self.hint)
        lay.addWidget(reset)
        self.resize(560, 460)
        self.refresh()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    def _axis_labels(self) -> tuple:
        ch = self.tw.characteristic
        axes = list(getattr(ch, "axes", None) or [])

        def ends(ax):
            vals = getattr(ax, "values", None)
            return (min(vals), max(vals)) if vals else None

        def name(ax, default):
            return f"{getattr(ax, 'attribute', '') or default} [{getattr(ax, 'unit', '') or '-'}]" if ax is not None else default
        x_ax = axes[0] if axes else None
        y_ax = axes[1] if len(axes) > 1 else None
        return (name(x_ax, "X"), name(y_ax, "Y"), ends(x_ax), ends(y_ax))

    def reset_view(self):
        self.canvas.yaw, self.canvas.pitch, self.canvas.zoom = -0.6, 0.9, 1.0
        self.canvas.update()

    def refresh(self):
        grid = self.tw.current_grid()
        if grid != self.canvas.grid:
            self.canvas.grid = [list(r) for r in grid]
            self.canvas.update()

    def closeEvent(self, ev):  # noqa: N802
        self._timer.stop()
        super().closeEvent(ev)
