"""Ana Sayfa'nın ortak (koyu tema) widget'ları: simgeler, anahtar, kilit
düğmesi, gösterge. Eski açık temalı ``GaugeWidget`` Performans ve Çalışma
Alanı sayfaları tarafından kullanıldığı için burada AYNEN korunur."""

import math

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app.theme import INK, INK_2, INK_3

# ---- Koyu tema renkleri (Ana Sayfa) ---------------------------------------
DK_BG = "#08121f"
DK_CARD = "#0f2034"
DK_CARD2 = "#12263d"
DK_LINE = "#1f3853"
DK_LINE2 = "#2a4a6b"
DK_INK = "#e8f0f8"
DK_MUT = "#8fa6bd"
DK_DIM = "#5d7893"
DK_BLUE = "#2f8cff"
DK_CYAN = "#35c6f4"
DK_GREEN = "#22c55e"
DK_AMBER = "#f59e0b"
DK_RED = "#ef4444"
DK_PURPLE = "#a45cf0"
DK_ORANGE = "#f08a1c"

# ---- Çizgi simgeleri (20x20) ----------------------------------------------
ICONS = {
    "plane": "M2 11l16-6-6 12-2-5z",
    "alt": "M2 17l5-8 3 4 3-6 5 10z",
    "mach": "M3 15a7 7 0 0 1 14 0M10 15l4-5",
    "alpha": "M3 17h14M3 17L15 6M8 17a5 5 0 0 0-1.5-3.5",
    "beta": "M3 4l14 6-14 6M3 10h9",
    "cloud": "M5.5 16a3.5 3.5 0 0 1 0-7 4.8 4.8 0 0 1 9-1 3.5 3.5 0 0 1 .5 8z",
    "temp": "M8 3.5a2 2 0 0 1 4 0v8a4 4 0 1 1-4 0z",
    "pin": "M3 15a7 7 0 0 1 14 0M10 15l3-6",
    "power": "M10 3v7M5.5 6a7 7 0 1 0 9 0",
    "spark": "M11 2L5 11h5l-1 7 6-9h-5z",
    "throttle": "M3 16l9-11M12 5l5 2",
    "fuel": "M10 2c3 4 5 6.5 5 9a5 5 0 0 1-10 0c0-2.5 2-5 5-9z",
    "sliders": "M4 4v12M10 8v8M16 3v13M2 8h4M8 5h4M14 11h4",
    "pump": "M4 17V4h7v13M4 9h7M11 7l3 2v6a1.5 1.5 0 0 0 3 0V8l-2-2",
    "valve": "M3 6l7 4-7 4zM17 6l-7 4 7 4zM10 10V4M7 4h6",
    "starter": "M5 6h10v8H5zM2 10h3M15 10h3M8 9v2M12 9v2",
    "glow": "M8 2h4v4H8zM9 6v7M11 6v7M10 13v5",
    "actuator": "M10 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM10 2v3M10 15v3M2 10h3M15 10h3",
    "trend": "M2 16l5-6 4 3 7-9",
    "gauge": "M3 15a7 7 0 0 1 14 0M10 15l4-5",
    "lock": "M5 9h10v8H5zM7 9V6a3 3 0 0 1 6 0v3",
    "unlock": "M5 9h10v8H5zM7 9V6a3 3 0 0 1 5.6-1.5",
    "play": "M6 4l10 6-10 6z",
    "stop": "M5 5h10v10H5z",
    "warn": "M10 3l8 14H2zM10 8v4M10 14.5v.2",
    "flag": "M5 17V3M5 4h10l-2 3 2 3H5",
    "zoom_in": "M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM13 13l4 4M7 9h4M9 7v4",
    "zoom_out": "M9 3.5a5.5 5.5 0 1 0 0 11 5.5 5.5 0 0 0 0-11zM13 13l4 4M7 9h4",
    "cursor": "M10 2v16M2 10h16",
    "download": "M10 3v10M6 9l4 4 4-4M4 17h12",
    "settings": "M10 7.4a2.6 2.6 0 1 0 0 5.2 2.6 2.6 0 0 0 0-5.2zM10 2.5v2.2M10 15.3v2.2M2.5 10h2.2M15.3 10h2.2M4.7 4.7l1.6 1.6M13.7 13.7l1.6 1.6M4.7 15.3l1.6-1.6M13.7 6.3l1.6-1.6",
    "compare": "M3 7h12M12 4l3 3-3 3M17 13H5M8 10l-3 3 3 3",
    "fit": "M3 8V3h5M17 8V3h-5M3 12v5h5M17 12v5h-5",
}

_pix_cache: dict = {}


def icon_pixmap(name: str, color: str = DK_MUT, size: int = 20, dpr: float = 2.0) -> QPixmap:
    key = (name, color, size, dpr)
    pm = _pix_cache.get(key)
    if pm is not None:
        return pm
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="none" stroke="{color}" '
           f'stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="{ICONS[name]}"/></svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    renderer.render(p)
    p.end()
    pm.setDevicePixelRatio(dpr)
    _pix_cache[key] = pm
    return pm


class IconLabel(QLabel):
    def __init__(self, name: str, color: str = DK_MUT, size: int = 20, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setPixmap(icon_pixmap(name, color, size))
        self.setStyleSheet("background:transparent;")


class IconButton(QPushButton):
    """Kenarlıklı küçük, simgeli düğme (checkable olabilir)."""

    def __init__(self, name: str, size: int = 28, color: str = DK_MUT, checked_color: str = DK_CYAN,
                 parent=None):
        super().__init__(parent)
        self._name, self._color, self._checked_color = name, color, checked_color
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setFlat(True)

    def set_icon_name(self, name: str):
        self._name = name
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        enabled = self.isEnabled()
        col = self._checked_color if on else self._color
        border = QColor(col if on else DK_LINE2)
        border.setAlpha(150 if on else 255)
        fill = QColor("#0a1828")
        if on:
            fill = QColor(col)
            fill.setAlpha(36)
        p.setOpacity(1.0 if enabled else 0.4)
        p.setPen(QPen(border, 1))
        p.setBrush(fill)
        p.drawRoundedRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1), 7, 7)
        s = 16 if self.width() >= 26 else 13
        p.drawPixmap(int((self.width() - s) / 2), int((self.height() - s) / 2),
                     icon_pixmap(self._name, col, s))


class LockButton(IconButton):
    """Anahtar (_sw) kilidi: kapalı = sw 0 (değer değiştirilemez), açık =
    sw 1 (manuel değer verilebilir). ``toggled`` yerine ``lock_requested``
    sinyali kullanılır: gerçek durumu çağıran taraf onay/rol kontrolünden
    sonra ``set_open`` ile ayarlar."""

    lock_requested = Signal(bool)   # True: kilidi aç (sw=1), False: kilitle (sw=0)

    def __init__(self, size: int = 28, parent=None):
        super().__init__("lock", size, DK_MUT, "#ffcb6b", parent)
        self.setCheckable(True)
        self.setToolTip("Kilitli: değer değiştirilemez (anahtar=0). Tıkla: manuel değer (anahtar=1)")
        self.clicked.connect(self._clicked)

    def _clicked(self, _checked=False):
        want_open = not self._open
        self.setChecked(self._open)       # görünümü gerçek duruma geri al
        self.lock_requested.emit(want_open)

    _open = False

    def set_open(self, opened: bool):
        self._open = opened
        self.setChecked(opened)
        self.set_icon_name("unlock" if opened else "lock")
        self.setToolTip("Manuel: değer değiştirilebilir (anahtar=1). Tıkla: kilitle (anahtar=0)" if opened
                        else "Kilitli: değer değiştirilemez (anahtar=0). Tıkla: manuel değer (anahtar=1)")

    @property
    def is_open(self) -> bool:
        return self._open


class ToggleSwitch(QPushButton):
    """Açma/kapama anahtarı. Koyu temada okunur; ``color`` ile açık rengi değişir."""

    def __init__(self, parent=None, on_color: str = DK_BLUE):
        super().__init__(parent)
        self.setCheckable(True)
        self._on_color = on_color
        self.setFixedSize(42, 22)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        painter.setOpacity(1.0 if self.isEnabled() else 0.4)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(self._on_color) if on else QColor("#2a3d52"))
        painter.drawRoundedRect(self.rect(), 11, 11)
        d = 16
        x = self.width() - d - 3 if on else 3
        painter.setBrush(QColor("#FFFFFF") if on else QColor("#cbd8e6"))
        painter.drawEllipse(x, 3, d, d)


def format_value(v, unit: str = "") -> str:
    """Gösterge/etiket değer biçimi: büyük sayılar ondalıksız, küçükler 1-2 ondalık."""
    if v is None:
        return "—"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(f):
        return "—"
    a = abs(f)
    if a >= 1000:
        return f"{f:.0f}"
    if a >= 100:
        return f"{f:.1f}".rstrip("0").rstrip(".")
    if a >= 10:
        return f"{f:.1f}".rstrip("0").rstrip(".") if f != int(f) else f"{int(f)}"
    return f"{f:.2f}".rstrip("0").rstrip(".") if f != int(f) else f"{int(f)}"


def _format_scale_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


# ===========================================================================
# Eski açık temalı gösterge (Performans / Çalışma Alanı kullanır) — DEĞİŞMEDİ
# ===========================================================================
class GaugeWidget(QWidget):
    """Yarım daire (yay) ibreli gösterge (açık tema). Performans ve
    Çalışma Alanı sayfalarında kullanılır."""

    def __init__(self, label: str, minimum: float, maximum: float, unit: str = "", parent=None):
        super().__init__(parent)
        self._label = label
        self._minimum = minimum
        self._maximum = maximum
        self._unit = unit
        self._value: float | None = None
        self.setMinimumSize(110, 120)
        self.setMaximumHeight(168)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def sizeHint(self):  # noqa: N802
        return QSize(160, 172)

    def set_range(self, minimum: float, maximum: float):
        self._minimum = minimum
        self._maximum = maximum
        self.update()

    def set_value(self, value: float | None):
        self._value = value
        self.update()

    def _fraction(self) -> float:
        if self._value is None:
            return 0.0
        span = (self._maximum - self._minimum) or 1.0
        frac = (self._value - self._minimum) / span
        return max(0.0, min(1.0, frac))

    _DESIGN_W = 180.0
    _DESIGN_H = 180.0
    ZONES = [(0.0, 0.70, "#1B8A4C"), (0.70, 0.90, "#B9790F"), (0.90, 1.0, "#C22A1D")]

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        scale = min(self.width() / self._DESIGN_W, self.height() / self._DESIGN_H)
        if scale <= 0:
            return
        painter.translate((self.width() - self._DESIGN_W * scale) / 2,
                          (self.height() - self._DESIGN_H * scale) / 2)
        painter.scale(scale, scale)

        cx, cy, radius, pen_w = 90.0, 84.0, 74.0, 12.0
        rect = QRectF(cx - radius, cy - radius, 2 * radius, 2 * radius)

        pen_bg = QPen(QColor("#D6DEE6"), pen_w)
        pen_bg.setCapStyle(Qt.FlatCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 180 * 16, -180 * 16)

        for z_start, z_end, color in self.ZONES:
            pen = QPen(QColor(color), pen_w)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, 180 * 16 - int(z_start * 180 * 16), -int((z_end - z_start) * 180 * 16))

        tick_pen = QPen(QColor("#9AA8B5"), 1.4)
        painter.setPen(tick_pen)
        r_out = radius - pen_w / 2 - 3
        for i in range(11):
            a = math.radians(180 - 18 * i)
            r_in = r_out - (8 if i % 5 == 0 else 4)
            painter.drawLine(QPointF(cx + r_out * math.cos(a), cy - r_out * math.sin(a)),
                             QPointF(cx + r_in * math.cos(a), cy - r_in * math.sin(a)))

        angle_rad = math.radians(180 - 180 * self._fraction())
        needle_len = (radius - pen_w / 2) * 0.95
        tip = QPointF(cx + needle_len * math.cos(angle_rad), cy - needle_len * math.sin(angle_rad))
        needle_pen = QPen(QColor("#121A22"), 3.2)
        needle_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(needle_pen)
        painter.drawLine(QPointF(cx, cy), tip)
        painter.setBrush(QColor("#121A22"))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(cx, cy), 5.0, 5.0)

        def font(px: float, bold: bool = False, mono: bool = False) -> QFont:
            f = QFont("IBM Plex Mono") if mono else QFont()
            if mono:
                f.setStyleHint(QFont.Monospace)
            f.setPixelSize(max(1, int(round(px))))
            f.setBold(bold)
            return f

        painter.setFont(font(12, bold=True))
        painter.setPen(QColor(INK_3))
        painter.drawText(QRectF(cx - radius - pen_w / 2, cy + 5, 56, 15),
                         Qt.AlignLeft | Qt.AlignVCenter, _format_scale_number(self._minimum))
        painter.drawText(QRectF(cx + radius + pen_w / 2 - 56, cy + 5, 56, 15),
                         Qt.AlignRight | Qt.AlignVCenter, _format_scale_number(self._maximum))

        value_text = f"{self._value:.4g}" if isinstance(self._value, (int, float)) else "—"
        pill = QRectF((self._DESIGN_W - 84) / 2, cy + 22, 84, 30)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#13324A"))
        painter.drawRoundedRect(pill, 6, 6)
        painter.setFont(font(20, bold=True, mono=True))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(pill, Qt.AlignHCenter | Qt.AlignVCenter, value_text)

        if self._unit:
            painter.setFont(font(12))
            painter.setPen(QColor(INK_2))
            painter.drawText(QRectF(0, cy + 54, self._DESIGN_W, 16), Qt.AlignHCenter | Qt.AlignVCenter, self._unit)

        painter.setFont(font(15, bold=True))
        painter.setPen(QColor(INK))
        painter.drawText(QRectF(0, cy + 70, self._DESIGN_W, 20), Qt.AlignHCenter | Qt.AlignVCenter, self._label)


# ===========================================================================
# Ana Sayfa koyu gösterge
# ===========================================================================
class DashGauge(QWidget):
    """Koyu temalı yarım daire gösterge: gradyan bölgeli yay, ibre, değer + birim.
    Değer yoksa/bayatsa ibre başa yatar, değer "—" gösterilir."""

    ZONES = [(0.0, 0.60, DK_GREEN), (0.60, 0.78, "#eab308"), (0.78, 0.90, DK_ORANGE), (0.90, 1.0, DK_RED)]
    _DW, _DH = 200.0, 140.0

    def __init__(self, minimum: float, maximum: float, unit: str = "", parent=None):
        super().__init__(parent)
        self._min, self._max, self._unit = minimum, maximum, unit
        self._value: float | None = None
        self._dim = False
        self.setMinimumSize(90, 62)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_range(self, minimum: float, maximum: float, unit: str | None = None):
        if maximum <= minimum:
            maximum = minimum + 1.0
        self._min, self._max = minimum, maximum
        if unit is not None:
            self._unit = unit
        self.update()

    def set_value(self, value, dim: bool = False):
        try:
            self._value = None if value is None else float(value)
        except (TypeError, ValueError):
            self._value = None
        self._dim = dim
        self.update()

    @property
    def value(self):
        return self._value

    def fraction(self) -> float:
        if self._value is None:
            return 0.0
        return max(0.0, min(1.0, (self._value - self._min) / ((self._max - self._min) or 1.0)))

    def sizeHint(self):  # noqa: N802
        return QSize(220, 150)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        s = min(self.width() / self._DW, self.height() / self._DH)
        if s <= 0:
            return
        p.translate((self.width() - self._DW * s) / 2, (self.height() - self._DH * s) / 2)
        p.scale(s, s)
        cx, cy, r, w = 100.0, 80.0, 68.0, 9.0
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setOpacity(0.45 if self._dim or self._value is None else 1.0)
        pen = QPen(QColor("#1d3550"), w + 4)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawArc(rect, 180 * 16, -180 * 16)
        for a, b, col in self.ZONES:
            pen = QPen(QColor(col), w)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            p.drawArc(rect, 180 * 16 - int(a * 180 * 16), -int((b - a) * 180 * 16))
        p.setPen(QPen(QColor("#6b86a1"), 1.2))
        for i in range(11):
            ang = math.radians(180 - 18 * i)
            r1 = r - 9
            r2 = r - (18 if i % 5 == 0 else 14)
            p.drawLine(QPointF(cx + r1 * math.cos(ang), cy - r1 * math.sin(ang)),
                       QPointF(cx + r2 * math.cos(ang), cy - r2 * math.sin(ang)))
        ang = math.radians(180 - 180 * self.fraction())
        tip = QPointF(cx + (r - 6) * math.cos(ang), cy - (r - 6) * math.sin(ang))
        npen = QPen(QColor(DK_INK), 2.6)
        npen.setCapStyle(Qt.RoundCap)
        p.setPen(npen)
        p.drawLine(QPointF(cx, cy), tip)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(DK_INK))
        p.drawEllipse(QPointF(cx, cy), 4.5, 4.5)
        p.setOpacity(1.0)

        def font(px, bold=False):
            f = QFont()
            f.setPixelSize(int(px))
            f.setBold(bold)
            return f

        p.setFont(font(11, True))
        p.setPen(QColor("#7f97ae"))
        p.drawText(QRectF(cx - r - 14, cy + 4, 44, 14), Qt.AlignLeft | Qt.AlignVCenter, _format_scale_number(self._min))
        p.drawText(QRectF(cx + r - 30, cy + 4, 44, 14), Qt.AlignRight | Qt.AlignVCenter, _format_scale_number(self._max))
        p.setFont(font(25, True))
        p.setPen(QColor(DK_INK if self._value is not None and not self._dim else DK_DIM))
        p.drawText(QRectF(0, cy + 14, self._DW, 32), Qt.AlignHCenter | Qt.AlignVCenter,
                   format_value(self._value))
        p.setFont(font(11.5))
        p.setPen(QColor(DK_MUT))
        p.drawText(QRectF(0, cy + 46, self._DW, 16), Qt.AlignHCenter | Qt.AlignVCenter, self._unit)


class GaugeCard(QFrame):
    """Başlık + (etiket) + kilit düğmesi + gösterge. Kilit isteği ve tıklama dışarı bildirilir."""

    lock_requested = Signal(str, bool)   # anahtar, kilidi aç mı
    value_requested = Signal(str)        # göstergeye tıklandı (manuel değer girişi)

    def __init__(self, key: str, label: str, minimum: float, maximum: float, unit: str, parent=None):
        super().__init__(parent)
        self.key = key
        self.setObjectName("gaugeCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 5, 8, 3)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel(label)
        self.title.setObjectName("gaugeTitle")
        self.tag = QLabel("")
        self.tag.setVisible(False)
        self.lock = LockButton(22)
        self.lock.lock_requested.connect(lambda want: self.lock_requested.emit(self.key, want))
        head.addWidget(self.title)
        head.addWidget(self.tag)
        head.addStretch(1)
        head.addWidget(self.lock)
        lay.addLayout(head)
        self.gauge = DashGauge(minimum, maximum, unit)
        lay.addWidget(self.gauge, 1)
        self.status = QLabel("")
        self.status.setObjectName("gaugeStatus")
        self.status.setAlignment(Qt.AlignHCenter)
        self.status.setVisible(False)
        lay.addWidget(self.status)
        self._state = ""
        self.setCursor(Qt.ArrowCursor)

    def set_tag(self, text: str, kind: str = ""):
        """kind: '' | 'manual' | 'fault'"""
        self.tag.setVisible(bool(text))
        self.tag.setText(text)
        if kind == "fault":
            css = "background:#3a1416; color:#ff9a9a; border:1px solid #7a2a2a;"
        else:
            css = "background:#2a210c; color:#ffcb6b; border:1px solid #8a6a1e;"
        self.tag.setStyleSheet(f"{css} border-radius:8px; padding:0 6px; font-size:10px; font-weight:700;")
        state = kind
        if state != self._state:
            self._state = state
            self.setProperty("state", state)
            self.style().unpolish(self)
            self.style().polish(self)

    _debug = ""

    def set_status(self, text: str):
        """Değer yokken NEDEN yok olduğunu kartın altında gösterir."""
        self.status.setText(text)
        self.status.setVisible(bool(text))
        self.setToolTip(text or self._debug)

    def set_debug(self, text: str):
        """Tanılama: kaynak, ham ve fiziksel değer (fare üstüne gelince görünür)."""
        self._debug = text
        if not self.status.isVisible():
            self.setToolTip(text)

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.lock.is_open:
            self.value_requested.emit(self.key)
        super().mousePressEvent(event)


def make_card(title: str, icon: str):
    """Koyu tema kartı: (QFrame#card, içerik QVBoxLayout, başlık QHBoxLayout). Başlığın sağına
    ``head.addWidget(...)`` ile düğme/çip eklenebilir."""
    from PySide6.QtWidgets import QHBoxLayout
    card = QFrame()
    card.setObjectName("card")
    v = QVBoxLayout(card)
    v.setContentsMargins(14, 10, 14, 12)
    v.setSpacing(8)
    head = QHBoxLayout()
    head.setSpacing(8)
    head.addWidget(IconLabel(icon, DK_CYAN, 18))
    t = QLabel(title.upper())
    t.setObjectName("cardTitle")
    head.addWidget(t)
    head.addStretch(1)
    v.addLayout(head)
    return card, v, head
