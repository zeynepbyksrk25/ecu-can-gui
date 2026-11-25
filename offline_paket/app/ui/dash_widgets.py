"""Ana Sayfa'nın ortak (koyu tema) widget'ları: simgeler, anahtar, kilit
düğmesi ve yarım daire gösterge (``DashGauge``). Ana Sayfa, Performans ve Çalışma Alanı
aynı göstergeyi kullanır."""

import math

from PySide6.QtCore import QByteArray, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from app import theme

# ---- Koyu tema renkleri (Ana Sayfa) ---------------------------------------
DK_BG = theme.BG
DK_CARD = theme.SURFACE
DK_CARD2 = theme.SURFACE_ALT
DK_LINE = theme.BORDER
DK_LINE2 = theme.LINE_STRONG
DK_INK = theme.INK
DK_MUT = theme.MUTED
DK_DIM = theme.DIM
DK_BLUE = theme.BLUE
DK_CYAN = theme.ACCENT
DK_GREEN = theme.OK
DK_AMBER = theme.WARN
DK_RED = theme.DANGER
DK_PURPLE = theme.PURPLE

# Kart/kadran vurgu renkleri: her bölüm ayrı bir renkle ayırt edilir (Ana Sayfa "renksiz" görünmesin).
ACCENTS = {"blue": theme.BLUE, "green": theme.OK, "orange": theme.ORANGE, "teal": theme.ACCENT,
           "purple": theme.PURPLE, "slate": theme.MUTED}
# Her gösterge kendi renginde: Canlı Trend'deki seri renkleriyle uyumlu (RPM teal, Tt5 turuncu, FP mor ...).
GAUGE_ACCENT = {"RPM": theme.ACCENT, "İtki": theme.BLUE, "PLA": theme.OK, "Tt5": theme.ORANGE,
                "FP": theme.PURPLE, "FT": theme.WARN, "Ps2": "#0E8C7C", "Ps3": "#D6336C"}
DK_ORANGE = theme.ORANGE
# Büyük göstergelerde renk geçişli yay (yalnızca görünüm).
GAUGE_GRADIENT = {"RPM": [(0.0, theme.OK), (0.5, theme.WARN), (0.85, theme.DANGER), (1.0, theme.DANGER)],
                  "İtki": [(0.0, "#38A6F0"), (1.0, theme.BLUE)]}

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
    "detach": "M11 3h6v6M17 3l-8 8M8 5H4v11h11v-4",
    "fit": "M3 8V3h5M17 8V3h-5M3 12v5h5M17 12v5h-5",
    # Gösterge rozetleri (Motor Parametreleri)
    "g_rpm": "M8 10a2 2 0 1 0 4 0a2 2 0 1 0-4 0M10 8c0-3 1-5 3-5 1 2 0 4-3 5zM12 10c3 0 5 1 5 3-2 1-4 0-5-3zM10 12c0 3-1 5-3 5-1-2 0-4 3-5zM8 10c-3 0-5-1-5-3 2-1 4 0 5 3z",
    "g_thrust": "M10 17V4M5.5 8.5L10 4l4.5 4.5M5 17h10",
    "g_pla": "M4 16h12M7 16l5-11M12 5l3 1M10.6 5a1.4 1.4 0 1 0 2.8 0a1.4 1.4 0 1 0-2.8 0",
    "g_tt5": "M8 3.5a2 2 0 0 1 4 0v7a4 4 0 1 1-4 0zM10 8v6M15 4c1 1.5 1 3 0 4",
    "g_fp": "M10 2.5c3 3.5 5 6 5 8.5a5 5 0 0 1-10 0c0-2.5 2-5 5-8.5zM8 12.5a2.2 2.2 0 0 0 2 2",
    "g_ft": "M6 3.5a1.8 1.8 0 0 1 3.6 0v6.5a3.4 3.4 0 1 1-3.6 0zM13.5 6c2 2.5 3 4 3 5.5a3 3 0 0 1-6 0",
    "g_ps2": "M3 10a7 7 0 1 0 14 0a7 7 0 1 0-14 0M10 10l3-3M6 12.5h8",
    "g_ps3": "M3 10a7 7 0 1 0 14 0a7 7 0 1 0-14 0M10 10l3-3M6 12.5h8M10 3v2",
}
GAUGE_ICON = {"RPM": "g_rpm", "İtki": "g_thrust", "PLA": "g_pla", "Tt5": "g_tt5", "FP": "g_fp", "FT": "g_ft",
              "Ps2": "g_ps2", "Ps3": "g_ps3"}

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
        fill = QColor(theme.SURFACE)
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
        super().__init__("lock", size, DK_MUT, theme.WARN_INK, parent)
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
        painter.setBrush(QColor(self._on_color) if on else QColor(theme.LINE_STRONG))
        painter.drawRoundedRect(self.rect(), 11, 11)
        d = 16
        x = self.width() - d - 3 if on else 3
        painter.setBrush(QColor(theme.SURFACE) if on else QColor(theme.SURFACE))
        painter.drawEllipse(x, 3, d, d)


class MotorToggle(QWidget):
    """Komut şeridi toggle'ı: başlık + ON/OFF anahtarı; altında sinyalin o anki 1/0 değeri.

    ``switch`` (ToggleSwitch) tıklanabilir kısımdır; DashboardTab ``start_button`` vb. adlarla bunu dışarı verir."""

    def __init__(self, title: str, on_color: str = DK_BLUE, parent=None):
        super().__init__(parent)
        self.setObjectName("motorToggle")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(1)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.title = QLabel(title)
        self.title.setObjectName("motorToggleTitle")
        self.switch = ToggleSwitch(on_color=on_color)
        self.switch.setObjectName("motorSwitch")
        top.addWidget(self.title)
        top.addWidget(self.switch)
        self.value = QLabel("–")
        self.value.setObjectName("motorToggleValue")
        self.value.setAlignment(Qt.AlignCenter)
        v.addLayout(top)
        v.addWidget(self.value)
        self.setMinimumWidth(150)
        self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Preferred)

    def set_readout(self, value, source: str = ""):
        """``value`` None ise "–"; aksi halde 1/0 (ya da sayı) ve kaynak ipucu ("ECU" / "gönderilen")."""
        if value is None:
            self.value.setText("–")
            self.value.setToolTip("Değer okunamadı ve henüz gönderilmedi")
            return
        text = f"{float(value):g}"
        self.value.setText(f"{text}  ·  {source}" if source else text)
        self.value.setToolTip("ECU'dan okunan güncel değer" if source == "ECU" else "ECU'dan okunamadı: son gönderilen değer")


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
    if abs(value) >= 1000:
        return f"{value / 1000:g}k"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


# ===========================================================================
# Ana Sayfa koyu gösterge
# ===========================================================================
def _gauge_number(v) -> str:
    """Gösterge değeri: 10.000 ve üstü binlik noktalı (127.300), diğerleri ``format_value``."""
    if v is not None and math.isfinite(v) and abs(v) >= 10000:
        return f"{int(round(v)):,}".replace(",", ".")
    return format_value(v)


class DashGauge(QWidget):
    """Koyu temalı 240° gösterge: değere kadar dolan yay, ibre, değer + birim. İsteğe bağlı kırmızı sınır
    (``set_red_limit``): sınırın üstü yayda soluk kırmızı bölge olarak görünür, değer sınırı geçince dolgu
    kırmızıya döner. Sınır değeri yazılmaz. Değer yoksa/bayatsa ibre başa yatar, değer "—" gösterir. İsteğe
    bağlı ``label`` (Performans / Çalışma Alanı) birimin altına bir başlık çizer."""

    _DW, _DH = 200.0, 150.0
    _LABEL_H = 24.0
    _A0, _SWEEP = 210.0, 240.0          # başlangıç açısı (matematik, derece) ve saat yönünde tarama

    def __init__(self, minimum: float, maximum: float, unit: str = "", parent=None, label: str = ""):
        super().__init__(parent)
        self._min, self._max, self._unit = minimum, maximum, unit
        self._label = label
        self._value: float | None = None
        self._dim = False
        self._alert = False
        self._red: float | None = None
        self._accent = DK_CYAN
        self._big = False
        self._scale_labels = False
        self._grad: list | None = None
        self.setMinimumSize(90, 62)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_label(self, text: str):
        self._label = text or ""
        self.update()

    def set_style(self, big: bool = False, scale_labels: bool = False, gradient=None):
        """Büyük kart görünümü: kalın yay, ara skala etiketleri, renk geçişli dolgu ([(0..1, '#rrggbb'), ...])."""
        self._big, self._scale_labels, self._grad = big, scale_labels, gradient
        self.update()

    def _grad_color(self, f: float) -> QColor:
        st = self._grad or []
        if not st:
            return QColor(self._accent)
        if f <= st[0][0]:
            return QColor(st[0][1])
        for (f0, c0), (f1, c1) in zip(st, st[1:]):
            if f <= f1:
                t = (f - f0) / ((f1 - f0) or 1.0)
                a, b = QColor(c0), QColor(c1)
                return QColor(int(a.red() + (b.red() - a.red()) * t), int(a.green() + (b.green() - a.green()) * t),
                              int(a.blue() + (b.blue() - a.blue()) * t))
        return QColor(st[-1][1])

    @property
    def label(self) -> str:
        return self._label

    def _design_h(self) -> float:
        return self._DH + (self._LABEL_H if self._label else 0.0)

    def set_range(self, minimum: float, maximum: float, unit: str | None = None):
        if maximum <= minimum:
            maximum = minimum + 1.0
        self._min, self._max = minimum, maximum
        if unit is not None:
            self._unit = unit
        self.update()

    def set_red_limit(self, limit: float | None):
        """Bu değerin ÜSTÜ kırmızı bölgedir (None: bölge yok)."""
        self._red = None if limit is None else float(limit)
        self.update()

    @property
    def red_limit(self):
        return self._red

    @property
    def is_over_limit(self) -> bool:
        return self._red is not None and self._value is not None and self._value > self._red

    def set_value(self, value, dim: bool = False):
        try:
            self._value = None if value is None else float(value)
        except (TypeError, ValueError):
            self._value = None
        self._dim = dim
        self.update()

    def set_accent(self, color: str):
        """Yayın dolgu rengi (boş durumda aynı rengin açık tonu iz olarak görünür)."""
        self._accent = color
        self.update()

    def set_alert(self, alert: bool):
        """Arıza durumunda yay dolgusu kırmızı çizilir."""
        if alert != self._alert:
            self._alert = alert
            self.update()

    @property
    def value(self):
        return self._value

    def _frac_of(self, v: float) -> float:
        return max(0.0, min(1.0, (v - self._min) / ((self._max - self._min) or 1.0)))

    def fraction(self) -> float:
        if self._value is None:
            return 0.0
        return self._frac_of(self._value)

    def sizeHint(self):  # noqa: N802
        return QSize(220, 150 + (int(self._LABEL_H) if self._label else 0))

    def _pt(self, f: float, r: float, cx: float = 100.0, cy: float = 96.0) -> QPointF:
        ang = math.radians(self._A0 - self._SWEEP * f)
        return QPointF(cx + r * math.cos(ang), cy - r * math.sin(ang))

    def _arc(self, p: QPainter, rect: QRectF, f0: float, f1: float):
        if f1 > f0:
            p.drawArc(rect, int(round((self._A0 - self._SWEEP * f0) * 16)), -int(round(self._SWEEP * (f1 - f0) * 16)))

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        dh = self._design_h()
        s = min(self.width() / self._DW, self.height() / dh)
        if s <= 0:
            return
        p.translate((self.width() - self._DW * s) / 2, (self.height() - dh * s) / 2)
        p.scale(s, s)
        cx, cy, r, w = 100.0, 96.0, 70.0, (13.0 if self._big else 9.0)
        rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
        p.setOpacity(0.8 if self._dim or self._value is None else 1.0)
        over = self.is_over_limit

        def stroke(color: QColor):
            pen = QPen(color, w)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)

        track = QColor(self._accent)
        track.setAlpha(46)                     # vurgu renginin açık tonu: veri yokken de renkli görünür
        stroke(track)
        self._arc(p, rect, 0.0, 1.0)
        rf = None if self._red is None else self._frac_of(self._red)
        if rf is not None and rf < 1.0:        # kırmızı bölge: sınırdan skalanın sonuna
            zone = QColor(DK_RED)
            zone.setAlpha(115)
            stroke(zone)
            self._arc(p, rect, rf, 1.0)
        frac = self.fraction()
        if self._value is not None and frac > 0:
            if self._grad and not (self._alert or over):
                n = max(2, int(frac * 48))
                for i in range(n):
                    f0, f1 = frac * i / n, frac * (i + 1) / n
                    stroke(self._grad_color((f0 + f1) / 2))
                    self._arc(p, rect, f0, f1 + 0.002)
            else:
                stroke(QColor(DK_RED if (self._alert or over) else self._accent))
                self._arc(p, rect, 0.0, frac)
        p.setPen(QPen(QColor("#9AA8B5"), 1.3))
        for i in range(21):
            f = i / 20
            p.drawLine(self._pt(f, r - 9), self._pt(f, r - (18 if i % 5 == 0 else 14)))
        if rf is not None and rf < 1.0:        # sınır işareti (değer yazılmaz)
            mk = QPen(QColor(DK_RED), 2.0)
            p.setPen(mk)
            p.drawLine(self._pt(rf, r - 12), self._pt(rf, r + 8))
        tip = self._pt(frac, r - 14)
        npen = QPen(QColor(DK_INK), 2.4)
        npen.setCapStyle(Qt.RoundCap)
        p.setPen(npen)
        p.drawLine(QPointF(cx, cy), tip)
        p.setPen(QPen(QColor(DK_INK), 2.0))
        p.setBrush(QColor(DK_CARD))
        p.drawEllipse(QPointF(cx, cy), 5.0, 5.0)
        p.setOpacity(1.0)

        def font(px, bold=False):
            f = QFont()
            f.setPixelSize(int(px))
            f.setBold(bold)
            return f

        p.setFont(font(11, True))
        p.setPen(QColor("#6B7C8A"))
        lo, hi = self._pt(0.0, r + 1), self._pt(1.0, r + 1)
        p.drawText(QRectF(lo.x() - 22, lo.y() + 3, 44, 14), Qt.AlignHCenter | Qt.AlignVCenter, _format_scale_number(self._min))
        p.drawText(QRectF(hi.x() - 22, hi.y() + 3, 44, 14), Qt.AlignHCenter | Qt.AlignVCenter, _format_scale_number(self._max))
        if self._scale_labels:
            p.setFont(font(10, True))
            p.setPen(QColor("#6B7C8A"))
            for f in (0.25, 0.5, 0.75):
                q = self._pt(f, r - 27)
                p.drawText(QRectF(q.x() - 22, q.y() - 7, 44, 14), Qt.AlignHCenter | Qt.AlignVCenter,
                           _format_scale_number(self._min + f * (self._max - self._min)))
        p.setFont(font(26 if self._big else 22, True))
        bad = self._value is not None and (self._alert or over)
        p.setPen(QColor(DK_RED if bad else (DK_INK if self._value is not None and not self._dim else DK_DIM)))
        p.drawText(QRectF(0, 108, self._DW, 28), Qt.AlignHCenter | Qt.AlignVCenter, _gauge_number(self._value))
        p.setFont(font(12))
        p.setPen(QColor(DK_MUT))
        p.drawText(QRectF(0, 134, self._DW, 14), Qt.AlignHCenter | Qt.AlignVCenter, self._unit)
        if self._label:
            p.setFont(font(15, True))
            p.setPen(QColor(theme.HEAD))
            p.drawText(QRectF(0, 152, self._DW, 20), Qt.AlignHCenter | Qt.AlignVCenter, self._label)


class RingGauge(QWidget):
    """PLA için tam daire halka: değer kadar dolan yay, ortada değer ve birim. ``DashGauge`` ile aynı API."""

    def __init__(self, minimum: float, maximum: float, unit: str = "", parent=None, label: str = ""):
        super().__init__(parent)
        self._min, self._max, self._unit = minimum, maximum, unit
        self._value: float | None = None
        self._dim = False
        self._alert = False
        self._red: float | None = None
        self._accent = DK_CYAN
        self.setMinimumSize(90, 80)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_label(self, text: str):
        pass

    def set_style(self, **_kw):
        pass

    def set_range(self, minimum: float, maximum: float, unit: str | None = None):
        if maximum <= minimum:
            maximum = minimum + 1.0
        self._min, self._max = minimum, maximum
        if unit is not None:
            self._unit = unit
        self.update()

    def set_red_limit(self, limit):
        self._red = None if limit is None else float(limit)
        self.update()

    @property
    def red_limit(self):
        return self._red

    @property
    def is_over_limit(self) -> bool:
        return self._red is not None and self._value is not None and self._value > self._red

    def set_value(self, value, dim: bool = False):
        try:
            self._value = None if value is None else float(value)
        except (TypeError, ValueError):
            self._value = None
        self._dim = dim
        self.update()

    def set_accent(self, color: str):
        self._accent = color
        self.update()

    def set_alert(self, alert: bool):
        if alert != self._alert:
            self._alert = alert
            self.update()

    @property
    def value(self):
        return self._value

    def fraction(self) -> float:
        if self._value is None:
            return 0.0
        return max(0.0, min(1.0, (self._value - self._min) / ((self._max - self._min) or 1.0)))

    def sizeHint(self):  # noqa: N802
        return QSize(150, 150)

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        side = min(self.width(), self.height())
        s = side / 160.0
        if s <= 0:
            return
        p.translate((self.width() - side) / 2, (self.height() - side) / 2)
        p.scale(s, s)
        p.setOpacity(0.8 if self._dim or self._value is None else 1.0)
        w, r = 13.0, 62.0
        rect = QRectF(80 - r, 80 - r, 2 * r, 2 * r)
        track = QColor(self._accent)
        track.setAlpha(46)
        pen = QPen(track, w)
        pen.setCapStyle(Qt.FlatCap)
        p.setPen(pen)
        p.drawEllipse(rect)
        frac = self.fraction()
        if self._value is not None and frac > 0:
            pen = QPen(QColor(DK_RED if (self._alert or self.is_over_limit) else self._accent), w)
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.drawArc(rect, 90 * 16, -int(round(360 * frac * 16)))
        p.setOpacity(1.0)
        f = QFont()
        f.setPixelSize(34)
        f.setBold(True)
        p.setFont(f)
        bad = self._value is not None and (self._alert or self.is_over_limit)
        p.setPen(QColor(DK_RED if bad else (DK_INK if self._value is not None and not self._dim else DK_DIM)))
        p.drawText(QRectF(0, 54, 160, 40), Qt.AlignHCenter | Qt.AlignVCenter, _gauge_number(self._value))
        f2 = QFont()
        f2.setPixelSize(14)
        p.setFont(f2)
        p.setPen(QColor(DK_MUT))
        p.drawText(QRectF(0, 92, 160, 18), Qt.AlignHCenter | Qt.AlignVCenter, self._unit)


class GaugeCard(QFrame):
    """İkon rozeti + ad + durum etiketi + kilit düğmesi + gösterge. Kırmızı sınır aşılınca kart kırmızıya döner
    ve ``limit_text`` etiketi çıkar; arıza (ARIZA) her zaman önceliklidir."""

    lock_requested = Signal(str, bool)   # anahtar, kilidi aç mı
    value_requested = Signal(str)        # göstergeye tıklandı (manuel değer girişi)

    def __init__(self, key: str, label: str, minimum: float, maximum: float, unit: str, parent=None,
                 red_limit: float | None = None, limit_text: str = "LİMİT", variant: str = "normal"):
        super().__init__(parent)
        self.key = key
        self.variant = variant
        self._accent = GAUGE_ACCENT.get(key, DK_CYAN)
        self._limit_text = limit_text
        self._fault = ("", "")
        self.setObjectName("gaugeCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 7, 10, 5)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(7)
        self.badge = QLabel()
        self.badge.setFixedSize(26, 26)
        self.badge.setAlignment(Qt.AlignCenter)
        tint, edge = QColor(self._accent), QColor(self._accent)
        tint.setAlpha(36)
        edge.setAlpha(80)
        self.badge.setStyleSheet(
            f"background:rgba({tint.red()},{tint.green()},{tint.blue()},{tint.alpha()}); "
            f"border:1px solid rgba({edge.red()},{edge.green()},{edge.blue()},{edge.alpha()}); border-radius:7px;")
        icon = GAUGE_ICON.get(key)
        if icon:
            self.badge.setPixmap(icon_pixmap(icon, self._accent, 16))
        self.title = QLabel(label)
        self.title.setObjectName("gaugeTitle")
        self.tag = QLabel("")
        self.tag.setVisible(False)
        self.lock = LockButton(22)
        self.lock.lock_requested.connect(lambda want: self.lock_requested.emit(self.key, want))
        head.addWidget(self.badge)
        head.addWidget(self.title)
        head.addStretch(1)
        head.addWidget(self.tag)
        head.addWidget(self.lock)
        lay.addLayout(head)
        if variant == "ring":
            self.gauge = RingGauge(minimum, maximum, unit)
        else:
            self.gauge = DashGauge(minimum, maximum, unit)
            if variant == "big":
                self.gauge.set_style(big=True, scale_labels=True, gradient=GAUGE_GRADIENT.get(key))
        self.gauge.set_accent(self._accent)
        self.gauge.set_red_limit(red_limit)
        lay.addWidget(self.gauge, 1)
        self.status = QLabel("")
        self.status.setObjectName("gaugeStatus")
        self.status.setAlignment(Qt.AlignHCenter)
        self.status.setVisible(False)
        lay.addWidget(self.status)
        self._state = ""
        self.setCursor(Qt.ArrowCursor)

    def set_value(self, value, dim: bool = False):
        """Gösterge değerini ayarlar ve kırmızı sınır durumunu karta yansıtır."""
        self.gauge.set_value(value, dim=dim)
        self._apply_tag()

    def set_tag(self, text: str, kind: str = ""):
        """Arıza etiketi: kind '' | 'manual' | 'fault'"""
        self._fault = (text, kind)
        self._apply_tag()

    def _apply_tag(self):
        text, kind = self._fault
        over = self.gauge.is_over_limit and not (text and kind == "fault")
        if over:
            text, kind = self._limit_text, "fault"
        self.tag.setVisible(bool(text))
        self.tag.setText(text)
        if kind == "fault":
            css = f"background:{theme.DANGER_BG}; color:{theme.DANGER}; border:1px solid {theme.DANGER_LINE};"
            if over:
                css = f"background:{theme.DANGER}; color:{theme.SURFACE}; border:1px solid {theme.DANGER};"
        else:
            css = f"background:{theme.WARN_BG}; color:{theme.WARN_INK}; border:1px solid {theme.WARN_LINE};"
        self.tag.setStyleSheet(f"{css} border-radius:8px; padding:0 6px; font-size:11px; font-weight:700;")
        self.gauge.set_alert(kind == "fault" and not over)
        state = "alarm" if over else kind
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
