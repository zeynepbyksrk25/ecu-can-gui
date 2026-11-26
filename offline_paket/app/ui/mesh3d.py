"""Harita Editörü için 3B yüzey (Mesh) çizimi — MATLAB "Lookup Table Editor"
penceresindeki "Plot - Mesh" paneline karşılık gelir.

PyOpenGL / OpenGL gerektirmez (çevrimdışı pakete yeni bağımlılık eklenmez):
yüzey QPainter ile çizilir (painter algoritması: uzaktan yakına dolu dörtgen
+ renkli kenar çizgileri).

Eksenler:  X = sütun ekseni, Y = satır ekseni, Z = tablo değeri.

Etkileşim
  * Sol tuşla boş yerden sürükle : döndür (azimut/yükseklik)
  * Sol tuşla bir DÜĞÜM üstünden sürükle : o hücrenin Z değerini yukarı/aşağı
    değiştir (3B kalibrasyon). Bırakınca TEK geri-al adımı oluşur.
  * Sağ/orta tuşla sürükle : her zaman döndür
  * Tekerlek : yakınlaştır / uzaklaştır;  çift tık : görünümü sıfırla
"""

import math

from app import theme
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QToolTip, QWidget

# MATLAB "parula" benzeri renk geçişi (düşük -> yüksek)
_PARULA = [
    (0.2422, 0.1504, 0.6603), (0.2810, 0.3228, 0.9579), (0.1786, 0.5289, 0.9682),
    (0.0689, 0.6948, 0.8394), (0.2161, 0.7843, 0.5923), (0.6720, 0.7793, 0.2227),
    (0.9970, 0.7659, 0.2199), (0.9769, 0.9839, 0.0805),
]


def parula(t: float) -> QColor:
    """0..1 -> renk."""
    t = 0.0 if t != t else min(1.0, max(0.0, t))
    pos = t * (len(_PARULA) - 1)
    i = min(int(pos), len(_PARULA) - 2)
    f = pos - i
    a, b = _PARULA[i], _PARULA[i + 1]
    return QColor.fromRgbF(*(a[k] + (b[k] - a[k]) * f for k in range(3)))


def parula_lut(n: int = 256) -> list:
    """pyqtgraph ImageItem için (n, 3) uint8 tablo."""
    out = []
    for i in range(n):
        c = parula(i / (n - 1))
        out.append((c.red(), c.green(), c.blue()))
    return out


BOX_H = 0.7          # kutunun yüksekliği (taban 1 x 1)
PICK_RADIUS = 10     # düğüm yakalama yarıçapı (px)


class Mesh3DWidget(QWidget):
    cellPicked = Signal(int, int, bool)     # satır, sütun, ekle (Ctrl)
    cellDragged = Signal(int, int, float)   # satır, sütun, yeni Z değeri
    dragFinished = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(220, 170)
        self.setMouseTracking(True)
        self.xs = [0.0]
        self.ys = [0.0]
        self.z = [[None]]
        self.selected = set()
        self.labels = ("X", "Y", "Z")
        self.editable = True
        self.az = -37.5
        self.el = 30.0
        self.zoom = 1.0
        self._zrange = (0.0, 1.0)
        self._frozen = False
        self._drag = None          # ("rot", x, y) | ("vtx", r, c, y0, v0)
        self._bg = QColor(theme.SURFACE)
        self._ink = QColor(theme.HEAD)

    # ---- veri ----------------------------------------------------------------
    def set_theme(self, bg: str, ink: str):
        self._bg, self._ink = QColor(bg), QColor(ink)
        self.update()

    def set_data(self, xs, ys, z, selected=(), labels=None, editable=True):
        self.xs = list(xs) or [0.0]
        self.ys = list(ys) or [0.0]
        self.z = z
        self.selected = set(selected)
        if labels:
            self.labels = labels
        self.editable = editable
        if not self._frozen:
            self._zrange = self._compute_zrange()
        self.update()

    def reset_view(self):
        self.az, self.el, self.zoom = -37.5, 30.0, 1.0
        self.update()

    def _compute_zrange(self):
        flat = [v for row in self.z for v in row if v is not None]
        if not flat:
            return (0.0, 1.0)
        lo, hi = min(flat), max(flat)
        if hi - lo < 1e-12:
            return (lo - 1.0, hi + 1.0)
        pad = (hi - lo) * 0.08          # sürüklerken tepe/taban için pay
        return (lo - pad, hi + pad)

    # ---- projeksiyon -----------------------------------------------------------
    @staticmethod
    def _norm(v, lo, hi):
        return 0.0 if hi - lo < 1e-12 else (v - lo) / (hi - lo) - 0.5

    def _project(self, u, v, w):
        a, e = math.radians(self.az), math.radians(self.el)
        x1 = u * math.cos(a) - v * math.sin(a)
        y1 = u * math.sin(a) + v * math.cos(a)
        return x1, w * math.cos(e) + y1 * math.sin(e), y1 * math.cos(e) - w * math.sin(e)

    def _transform(self):
        """(u,v,w) -> (ekran x, ekran y, derinlik) ve ölçek döner."""
        pts = [self._project(u, v, w) for u in (-.5, .5) for v in (-.5, .5) for w in (0, BOX_H)]
        minx, maxx = min(p[0] for p in pts), max(p[0] for p in pts)
        miny, maxy = min(p[1] for p in pts), max(p[1] for p in pts)
        left, right, top, bottom = 50, 24, 22, 42
        aw = max(40, self.width() - left - right)
        ah = max(40, self.height() - top - bottom)
        sc = min(aw / max(1e-9, maxx - minx), ah / max(1e-9, maxy - miny)) * self.zoom
        cx, cy = left + aw / 2, top + ah / 2
        mx, my = (minx + maxx) / 2, (miny + maxy) / 2

        def tf(u, v, w):
            sx, sy, d = self._project(u, v, w)
            return cx + (sx - mx) * sc, cy - (sy - my) * sc, d
        return tf, sc

    def _uvw(self, r, c, val):
        xlo, xhi = min(self.xs), max(self.xs)
        ylo, yhi = min(self.ys), max(self.ys)
        zlo, zhi = self._zrange
        u = self._norm(self.xs[c], xlo, xhi) if len(self.xs) > 1 else 0.0
        v = self._norm(self.ys[r], ylo, yhi) if len(self.ys) > 1 else 0.0
        w = (val - zlo) / (zhi - zlo) * BOX_H
        return u, v, w

    def _vertices(self, tf):
        out = []
        for r, row in enumerate(self.z):
            for c, val in enumerate(row):
                if val is None or r >= len(self.ys) or c >= len(self.xs):
                    continue
                sx, sy, d = tf(*self._uvw(r, c, val))
                out.append((sx, sy, d, r, c, val))
        return out

    # ---- çizim -----------------------------------------------------------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), self._bg)
        tf, _sc = self._transform()
        zlo, zhi = self._zrange

        def pt(u, v, w):
            x, y, _d = tf(u, v, w)
            return QPointF(x, y)

        corners = [(-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)]
        depths = [tf(u, v, 0)[2] for u, v in corners]
        far = max(range(4), key=lambda i: depths[i])
        near = min(range(4), key=lambda i: depths[i])

        # arka duvarlar + ızgara
        grid_pen = QPen(QColor("#D5DCE3"), 1)
        wall_fill = QBrush(QColor("#F3F6F9"))
        for adj in ((far + 1) % 4, (far - 1) % 4):
            (u0, v0), (u1, v1) = corners[far], corners[adj]
            poly = QPolygonF([pt(u0, v0, 0), pt(u1, v1, 0), pt(u1, v1, BOX_H), pt(u0, v0, BOX_H)])
            p.setPen(QPen(QColor("#B8C3CD"), 1))
            p.setBrush(wall_fill)
            p.drawPolygon(poly)
            p.setPen(grid_pen)
            for k in range(1, 4):
                w = BOX_H * k / 4
                p.drawLine(pt(u0, v0, w), pt(u1, v1, w))
        p.setPen(QPen(QColor("#B8C3CD"), 1))
        p.setBrush(QBrush(QColor("#FBFCFD")))
        p.drawPolygon(QPolygonF([pt(u, v, 0) for u, v in corners]))

        # yüzey
        rows, cols = len(self.z), (len(self.z[0]) if self.z else 0)
        span = (zhi - zlo) or 1.0
        if rows >= 2 and cols >= 2:
            quads = []
            for r in range(rows - 1):
                for c in range(cols - 1):
                    vals = (self.z[r][c], self.z[r][c + 1], self.z[r + 1][c + 1], self.z[r + 1][c])
                    if any(v is None for v in vals) or r + 1 >= len(self.ys) or c + 1 >= len(self.xs):
                        continue
                    ps = [tf(*self._uvw(rr, cc, self.z[rr][cc]))
                          for rr, cc in ((r, c), (r, c + 1), (r + 1, c + 1), (r + 1, c))]
                    quads.append((sum(q[2] for q in ps) / 4, ps, sum(vals) / 4))
            quads.sort(key=lambda q: -q[0])      # uzaktan yakına
            p.setBrush(QBrush(self._bg))
            for _d, ps, mean in quads:
                p.setPen(QPen(parula((mean - zlo) / span), 1.3))
                p.drawPolygon(QPolygonF([QPointF(q[0], q[1]) for q in ps]))
        elif rows >= 1:
            # tek satır (eğri / 1xN dizi): çizgi + tabana düşen ince çizgiler
            row = self.z[0]
            pts = [(self._uvw(0, c, v), v) for c, v in enumerate(row) if v is not None and c < len(self.xs)]
            p.setPen(QPen(QColor("#C9D2DB"), 1, Qt.DashLine))
            for (u, v, w), _val in pts:
                p.drawLine(pt(u, v, 0), pt(u, v, w))
            p.setPen(QPen(parula(0.15), 2))
            p.drawPolyline(QPolygonF([pt(*uvw) for uvw, _ in pts]))

        verts = self._vertices(tf)
        # düğümler: küçük noktalar; seçili olanlar kırmızı
        if rows * cols <= 900:
            for sx, sy, _d, r, c, val in sorted(verts, key=lambda t: -t[2]):
                if (r, c) in self.selected:
                    continue
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(parula((val - zlo) / span).darker(115)))
                p.drawEllipse(QPointF(sx, sy), 2.2, 2.2)
        for sx, sy, _d, r, c, _val in verts:
            if (r, c) in self.selected:
                p.setPen(QPen(QColor("#7A0000"), 1))
                p.setBrush(QBrush(QColor("#FF0000")))
                p.drawEllipse(QPointF(sx, sy), 4.5, 4.5)

        # eksen yazıları
        p.setPen(QPen(self._ink))
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1))
        p.setFont(f)
        cu, cv = corners[near]
        centre = pt(0, 0, 0)

        def put_text(point, text, dx=0, dy=0, align=Qt.AlignCenter):
            v_out = QPointF(point.x() - centre.x(), point.y() - centre.y())
            n = math.hypot(v_out.x(), v_out.y()) or 1.0
            x = point.x() + v_out.x() / n * dx
            y = point.y() + v_out.y() / n * dy
            r = QRectF(x - 40, y - 8, 80, 16)
            p.drawText(r, int(align), text)

        xlo, xhi = min(self.xs), max(self.xs)
        ylo, yhi = min(self.ys), max(self.ys)
        # X ekseni: near köşesinden v sabit kenar (u değişir)
        u_other = -cu
        left_i = min(range(4), key=lambda i: tf(*corners[i], 0)[0])
        near_is_left = (left_i == near)       # Z ekseni etiketleriyle çakışmasın
        if not near_is_left:
            put_text(pt(cu, cv, 0), f"{(xlo if cu < 0 else xhi):g}", 14, 20)
        put_text(pt(u_other, cv, 0), f"{(xlo if u_other < 0 else xhi):g}", 12, 12)
        mid = pt((cu + u_other) / 2, cv, 0)
        put_text(mid, self.labels[0], 30, 30)
        # Y ekseni: near köşesinden u sabit kenar (v değişir)
        v_other = -cv
        put_text(pt(cu, v_other, 0), f"{(ylo if v_other < 0 else yhi):g}", 12, 12)
        mid = pt(cu, (cv + v_other) / 2, 0)
        put_text(mid, self.labels[1], 30, 30)

        # Z ekseni: ekranda en solda kalan taban köşesinin dikey kenarı
        lu, lv = corners[left_i]
        for k in range(5):
            w = BOX_H * k / 4
            val = zlo + (zhi - zlo) * k / 4
            q = pt(lu, lv, w)
            p.drawText(QRectF(q.x() - 54, q.y() - 8, 46, 16), int(Qt.AlignRight | Qt.AlignVCenter), f"{val:.4g}")
        top = pt(lu, lv, BOX_H)
        p.drawText(QRectF(top.x() - 50, top.y() - 24, 70, 16), int(Qt.AlignLeft | Qt.AlignVCenter), self.labels[2])
        p.end()

    # ---- etkileşim -------------------------------------------------------------
    def _nearest_vertex(self, pos):
        tf, _ = self._transform()
        best, bd = None, PICK_RADIUS ** 2
        for sx, sy, d, r, c, val in self._vertices(tf):
            dist = (sx - pos.x()) ** 2 + (sy - pos.y()) ** 2
            # eşitlikte öndeki (daha küçük derinlik) düğüm kazanır
            if dist < bd or (dist == bd and best is not None and d < best[2]):
                best, bd = (r, c, d, val), dist
        return best

    def mousePressEvent(self, ev):
        pos = ev.position()
        if ev.button() == Qt.LeftButton:
            hit = self._nearest_vertex(pos)
            if hit is not None:
                r, c, _d, val = hit
                self.cellPicked.emit(r, c, bool(ev.modifiers() & Qt.ControlModifier))
                if self.editable:
                    self._frozen = True            # sürüklerken Z aralığı sabit kalsın
                    self._drag = ("vtx", r, c, pos.y(), val)
                    self.setCursor(Qt.SizeVerCursor)
                return
        if ev.button() in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
            self._drag = ("rot", pos.x(), pos.y())
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, ev):
        pos = ev.position()
        if self._drag is None:
            hit = self._nearest_vertex(pos)
            if hit is not None:
                r, c, _d, val = hit
                QToolTip.showText(ev.globalPosition().toPoint(),
                                  f"[{r}][{c}]  {self.labels[0]}={self.xs[c]:g}  "
                                  f"{self.labels[1]}={self.ys[r]:g}  {self.labels[2]}={val:.6g}", self)
                self.setCursor(Qt.SizeVerCursor if self.editable else Qt.PointingHandCursor)
            else:
                self.setCursor(Qt.OpenHandCursor)
            return
        if self._drag[0] == "rot":
            _, x0, y0 = self._drag
            self.az += (pos.x() - x0) * 0.5
            self.el = min(89.0, max(3.0, self.el + (pos.y() - y0) * 0.5))
            self._drag = ("rot", pos.x(), pos.y())
            self.update()
        else:
            _, r, c, y0, v0 = self._drag
            _tf, sc = self._transform()
            zlo, zhi = self._zrange
            px_per_val = sc * max(0.2, math.cos(math.radians(self.el))) * BOX_H / (zhi - zlo)
            new = v0 + (y0 - pos.y()) / px_per_val
            new = min(zhi, max(zlo, new))
            self.cellDragged.emit(r, c, float(f"{new:.6g}"))

    def mouseReleaseEvent(self, _ev):
        was_vertex = self._drag is not None and self._drag[0] == "vtx"
        self._drag = None
        self._frozen = False
        self.setCursor(Qt.OpenHandCursor)
        if was_vertex:
            self.dragFinished.emit()

    def mouseDoubleClickEvent(self, _ev):
        self.reset_view()

    def wheelEvent(self, ev):
        self.zoom = min(3.0, max(0.5, self.zoom * (1.12 if ev.angleDelta().y() > 0 else 1 / 1.12)))
        self.update()
