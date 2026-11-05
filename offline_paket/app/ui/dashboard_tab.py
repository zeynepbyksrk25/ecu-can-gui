"""Ana Sayfa (Dashboard) sekmesi — "kokpit" düzeni (kullanıcının onayladığı
mockup'a göre): üstte ince bir "annunciator" (ikaz lambası) şeridi, altında
3 sütun:

  A) Motor Komutları + Ortam Koşulları (dar sütun)
  B) Motor Parametreleri (8 ibre/gösterge) + Sensör Durumu/Arıza Tablosu
     (geniş/esnek sütun)
  C) Canlı Grafik + Eyleyiciler (manuel override kontrolleri) (dar sütun)

Her şey TEK ekranda, dikey kaydırma OLMADAN sığacak şekilde kompakttır
(kullanıcının önceki tasarımın "çok uzun" olduğu yönündeki açık isteği).

Bu widget, önceki sürümdeki TÜM plumbing'i korur:
  - DashboardConfig / DashboardConfigStore (app/dashboard_config.py)
  - "Ayarlar" öz-hizmet DBC/A2L eşleme paneli
  - tick/update mekanizması (tick sinyali -> MainWindow -> CCP okuma ->
    set_measurement_value()/set_ambient_value() geri çağrısı)
  - MainWindow'un zaten bağlandığı sinyaller: motor_start_requested,
    motor_stop_requested, estop_requested, config_saved, tick.

YENİ eklenenler: GaugeWidget (yarım daire ibre), annunciator lambaları,
Sensör Durumu tablosu (placeholder durum mantığıyla,
get_sensor_status() üzerinden) ve Eyleyiciler panelindeki gerçek manuel
override kontrolleri (bkz. aşağıdaki ActuatorRow / actuator_command
sinyali — gerçek CAN gönderimini yine MainWindow yapar).

Bu widget de, diğer sekmeler gibi, gerçek CAN gönderimini / CCP okumasını
YAPMAZ — sinyal olarak dışarı bildirir, MainWindow gerçek işlemi yapar.
"""

import math
import time
from datetime import datetime

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QBoxLayout, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QFrame, QGraphicsDropShadowEffect,
    QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSpinBox, QVBoxLayout, QWidget,
)

import pyqtgraph as pg

from app.dashboard_config import (
    ACTUATOR_KEYS, ACTUATOR_KINDS, ACTUATOR_LABELS, AMBIENT_KEYS,
    AMBIENT_LABELS, AMBIENT_UNITS, GAUGE_KEYS, ActuatorCommand,
    DashboardConfig, MotorCommand,
)
from app.theme import ACCENT_INK, BORDER, INK, INK_2, INK_3, SURFACE
from app.user_roles import Role, can_override_actuator

TICK_INTERVAL_MS = 500
GRAPH_POLL_MS = 1000

# ---- Gösterge (gauge) aralıkları: (min, max, birim) ------------------------
# Kullanıcının referans mockup'ına göre KESİN ölçek değerleri (bkz. görev
# tanımındaki 8 göstergenin min/max listesi). Artık 8 göstergenin TAMAMI
# aynı boyutta, tek tip 4x2 ızgarada çizilir (eski "primary/secondary"
# boyut ayrımı kaldırıldı).
GAUGE_RANGES = {
    "RPM": (0.0, 6000.0, "rpm"),
    "İtki": (0.0, 100.0, "%"),
    "PLA": (0.0, 100.0, "%"),
    "Tt5": (0.0, 800.0, "°C"),
    "FP": (0.0, 10.0, "bar"),
    "FT": (0.0, 500.0, "°C"),
    "Ps2": (0.0, 5.0, "bar"),
    "Tt2": (0.0, 120.0, "°C"),
}
# Göstergenin İÇ anahtarı (GAUGE_KEYS, DashboardConfig vb. ile uyumlu
# olması için "FP"/"FT" büyük harfle kalır) ile EKRANDA gösterilen
# etiket metni farklı olabilir (referans mockup "Fp"/"Ft" yazıyor).
GAUGE_DISPLAY_LABELS = {key: key for key in GAUGE_KEYS}
GAUGE_DISPLAY_LABELS["FP"] = "Fp"
GAUGE_DISPLAY_LABELS["FT"] = "Ft"


def _apply_card_shadow(widget: QWidget, blur: float = 22, dy: float = 3, alpha: int = 45):
    """Her panele/karta tutarlı, yumuşak bir "card" gölgesi uygular
    (referans mockup'taki hafif derinlik hissi için)."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setOffset(0, dy)
    effect.setColor(QColor(20, 30, 40, alpha))
    widget.setGraphicsEffect(effect)


def _card_title(text: str) -> QLabel:
    """Kartın içindeki başlık (sol panel başlığıyla tutarlı)."""
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color:{INK}; font-size:13px; font-weight:800; background:transparent;")
    return lbl


def _style_card_group(box: QGroupBox):
    """QGroupBox'ı, görünür kenarlığı olmayan, beyaz/yuvarlak köşeli bir
    "kart" gibi stillendirir; gerçek derinlik ayrı bir drop-shadow efekti
    ile sağlanır (bkz. _apply_card_shadow)."""
    box.setStyleSheet(
        f"QGroupBox {{ background: {SURFACE}; border: 1px solid #EDF1F5; "
        f"border-radius: 10px; margin-top: 0px; padding: 10px; "
        f"font-weight: 700; color: {INK}; }} "
        f"QGroupBox::title {{ subcontrol-origin: margin; left: 12px; "
        f"padding: 0 4px; color: {INK}; }}"
    )
    _apply_card_shadow(box)

class ReflowGrid(QWidget):
    """Genişliğe göre sütun sayısını değiştiren ızgara: pencere genişken
    öğeler tek sırada, daralınca otomatik alt satıra iner. `options`
    azalan sütun sayıları (ör. [8, 4, 2]); en büyük uygun olan seçilir."""

    def __init__(self, options, min_cell_width: int, spacing: int = 10, parent=None, stretch_rows: bool = False):
        super().__init__(parent)
        self._stretch_rows = stretch_rows
        self._options = sorted(options, reverse=True)
        self._min_cell = min_cell_width
        self._items: list[QWidget] = []
        self._cols = 0
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(spacing)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding if stretch_rows else QSizePolicy.Preferred)

    def add_item(self, w: QWidget):
        self._items.append(w)
        self._relayout(force=True)

    def _pick(self) -> int:
        width = max(self.width(), 1)
        for n in self._options:
            if width / n >= self._min_cell:
                return min(n, max(len(self._items), 1))
        return min(self._options[-1], max(len(self._items), 1))

    def _relayout(self, force: bool = False):
        cols = self._pick() if self.width() > 1 else self._options[-1]
        if cols == self._cols and not force:
            return
        self._cols = cols
        while self._grid.count():
            self._grid.takeAt(0)
        for i, w in enumerate(self._items):
            alone = self._stretch_rows and cols > 1 and i == len(self._items) - 1 and i % cols == 0
            self._grid.addWidget(w, i // cols, i % cols, 1, cols if alone else 1)
        for c in range(max(cols, 8)):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        for r in range(12):
            self._grid.setRowStretch(r, 1 if self._stretch_rows and r < (len(self._items) + cols - 1) // cols else 0)
        self.updateGeometry()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self._relayout()


# Sensör Durumu ve Arıza Tablosu satır sırası + sütunlar.
_SENSOR_ROWS = ["FP", "FT", "RPM", "Tt5", "Ps2", "Tt2"]
_SENSOR_CHECKS = ["Elektriksel", "Tutarlılık", "Minimum", "Maksimum"]

# Canlı Grafik'te çizilen seriler artık kullanıcı tarafından seçilir
# (DashboardConfig.graph_signals); renkler sırayla bu paletten verilir.
_GRAPH_PALETTE = ["#0E6E8C", "#C22A1D", "#1B8A4C", "#7C3AED", "#B45309",
                  "#0E7490", "#BE185D", "#4D7C0F", "#1D4ED8", "#9A3412"]
_GRAPH_MAX_POINTS = 120  # ~60 saniye (GRAPH_POLL_MS=500ms * 120)

# Annunciator (ikaz) lambaları — sırasıyla.
_LAMP_KEYS = [
    ("red_stop", "RED STOP LAMP"),
    ("mil", "MIL LAMP"),
    ("start_inhibit", "BAŞLATMA ENGELLEME"),
    ("fault_code", "HATA KODU"),
    ("fadec_action", "FADEC AKSİYONU"),
]


def _format_scale_number(value: float) -> str:
    """Gösterge köşelerindeki min/maks etiketleri için kompakt sayı
    biçimi: tam sayıysa ondalık nokta olmadan ("0", "6000"), değilse
    kısa ondalık ("2.5")."""
    if float(value).is_integer():
        return str(int(value))
    return f"{value:g}"


# Gerçek sensör arıza kaynağı bağlanana dek False: arayüz "Arıza yok" (yeşil)
# demek yerine "izlenmiyor" (gri) gösterir — sahte güvence vermemek için.
SENSOR_MONITORING_AVAILABLE = False


def get_sensor_status(sensor_name: str, check_name: str) -> tuple:
    """Sensör Durumu ve Arıza Tablosu'ndaki TEK bir hücrenin durumunu
    döndürür: (ok: bool, text: str).

    YER TUTUCU (placeholder) UYGULAMA: CCP/DBC katmanında şu an
    sensör-bazlı elektriksel arıza / tutarlılık / min-maks aşım biti
    kavramı YOKTUR (bkz. app/ccp/, app/ui/errors_tab.py,
    app/ui/diagnostics_tab.py — hiçbiri bu granülaritede bir arıza
    bayrağı sunmuyor). Bu yüzden her hücre burada sabit olarak OK/yeşil
    döner. Gerçek arıza bitleri DBC/A2L'de tanımlandığında, bu TEK
    fonksiyonun içini (sensor_name, check_name) ikilisine göre gerçek
    bir arıza kaynağına (örn. DashboardTab'a iletilmiş bir "fault_bits"
    sözlüğü) bakacak şekilde değiştirmek yeterlidir; çağıran tablo kodu
    hiç değişmeyecektir.
    """
    return True, "OK"


class GaugeWidget(QWidget):
    """Yarım daire (yay) ibreli gösterge: arka plan yayı, 3 bölgeli
    (yeşil %0-70, amber %70-90, kırmızı %90-100) renkli yay, yay uçlarının
    hemen altında küçük gri min/maks ölçek etiketleri, bir ibre ve altında
    sırasıyla büyük kalın değer / küçük gri birim / kalın isim etiketi.
    Değer, configured min/max aralığına göre normalize edilip çizilir.

    Referans mockup'a göre ARTIK TÜM göstergeler aynı boyuttadır — eski
    "primary" (büyük/küçük) ayrımı kaldırıldı."""

    def __init__(self, label: str, minimum: float, maximum: float, unit: str = "",
                 parent=None):
        super().__init__(parent)
        self._label = label
        self._minimum = minimum
        self._maximum = maximum
        self._unit = unit
        self._value: float | None = None
        self.setMinimumSize(110, 120)
        self.setMaximumHeight(168)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def sizeHint(self):  # noqa: N802 (Qt override)
        from PySide6.QtCore import QSize
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

    # Gösterge, sabit bir "tasarım" koordinat uzayında (180x170) çizilir ve
    # pencere boyutuna göre TEK bir oranla (en-boy korunarak) ölçeklenir:
    # yay her zaman gerçek yarım daire, yazılar yayla orantılı kalır; pencere
    # büyüyünce/küçülünce bileşenler birbirinin üstüne binmez.
    _DESIGN_W = 180.0
    _DESIGN_H = 180.0
    ZONES = [(0.0, 0.70, "#1B8A4C"), (0.70, 0.90, "#B9790F"), (0.90, 1.0, "#C22A1D")]

    def paintEvent(self, event):  # noqa: N802 (Qt override)
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

        # Arka plan yayı
        pen_bg = QPen(QColor("#D6DEE6"), pen_w)
        pen_bg.setCapStyle(Qt.FlatCap)
        painter.setPen(pen_bg)
        painter.drawArc(rect, 180 * 16, -180 * 16)

        # 3 bölgeli renkli yay: yeşil 0-70%, amber 70-90%, kırmızı 90-100%
        zones = self.ZONES
        for z_start, z_end, color in zones:
            pen = QPen(QColor(color), pen_w)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            painter.drawArc(rect, 180 * 16 - int(z_start * 180 * 16),
                            -int((z_end - z_start) * 180 * 16))

        # İnce ölçek çizgileri (yayın iç tarafında, 11 adet)
        tick_pen = QPen(QColor("#9AA8B5"), 1.4)
        painter.setPen(tick_pen)
        r_out = radius - pen_w / 2 - 3
        for i in range(11):
            a = math.radians(180 - 18 * i)
            r_in = r_out - (8 if i % 5 == 0 else 4)
            painter.drawLine(QPointF(cx + r_out * math.cos(a), cy - r_out * math.sin(a)),
                             QPointF(cx + r_in * math.cos(a), cy - r_in * math.sin(a)))

        # İbre
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

        # Yay uçlarının altında küçük gri min/maks etiketleri
        painter.setFont(font(12, bold=True))
        painter.setPen(QColor(INK_3))
        painter.drawText(QRectF(cx - radius - pen_w / 2, cy + 5, 56, 15),
                         Qt.AlignLeft | Qt.AlignVCenter, _format_scale_number(self._minimum))
        painter.drawText(QRectF(cx + radius + pen_w / 2 - 56, cy + 5, 56, 15),
                         Qt.AlignRight | Qt.AlignVCenter, _format_scale_number(self._maximum))

        # Altında sırayla: büyük kalın DEĞER -> küçük gri BİRİM -> kalın İSİM
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


class _ClockAxisItem(pg.AxisItem):
    """Canlı Grafik'in alt ekseni: şimdiye göre geçen süre (−60 … 0 sn).
    Veri hâlâ gerçek epoch zaman damgasıyla tutulur; yalnız etiket göreli."""

    def tickStrings(self, values, scale, spacing):
        now = time.time()
        out = []
        for v in values:
            d = round(v - now)
            out.append("şimdi" if d >= -1 else f"{d} sn")
        return out


class _CheckBadge(QWidget):
    """Sensör tablosundaki "OK" hücresi için yeşil daire içinde onay
    işareti rozeti (referans mockup'taki check-circle rozetlerine göre)."""

    def __init__(self, text: str = "OK", ok: bool = True, parent=None):
        super().__init__(parent)
        self._text = text
        self._ok = ok
        self.setMinimumHeight(18)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self._ok is None:  # arıza kaynağı yok: nötr gri çizgi
            painter.setPen(QPen(QColor("#9AA8B5"), 1.6))
            painter.drawLine(QPointF(4, self.height() / 2), QPointF(14, self.height() / 2))
            return
        color = QColor("#1B8A4C") if self._ok else QColor("#B9790F")
        d = 14
        cy = self.height() / 2
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(QPointF(d / 2 + 2, cy), d / 2, d / 2)
        check_pen = QPen(QColor("#FFFFFF"), 1.6)
        check_pen.setCapStyle(Qt.RoundCap)
        check_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(check_pen)
        # basit onay işareti
        cx = d / 2 + 2
        painter.drawLine(QPointF(cx - 3.2, cy), QPointF(cx - 0.8, cy + 2.6))
        painter.drawLine(QPointF(cx - 0.8, cy + 2.6), QPointF(cx + 3.4, cy - 3.0))
        font = QFont()
        font.setPointSizeF(10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(color)
        painter.drawText(
            QRectF(d + 6, 0, self.width() - d - 8, self.height()),
            Qt.AlignVCenter | Qt.AlignLeft, self._text,
        )

    def sizeHint(self):
        from PySide6.QtCore import QSize
        return QSize(52, 18)


class ToggleSwitch(QPushButton):
    """Basit bir açma/kapama anahtarı (pil/knob switch). QPushButton'ın
    checkable modunu kullanır; görünümü QSS'ten bağımsız, doğrudan burada
    çizilir ki tema değişse de anahtar okunaklı kalsın."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(56, 28)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        on = self.isChecked()
        track_color = QColor("#1B8A4C") if on else QColor("#D6DEE6")
        painter.setPen(Qt.NoPen)
        painter.setBrush(track_color)
        painter.drawRoundedRect(self.rect(), 14, 14)
        knob_d = 22
        x = self.width() - knob_d - 3 if on else 3
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(x, 3, knob_d, knob_d)


class _LampCell(QLabel):
    """Annunciator şeridindeki tek bir ikaz lambası hücresi."""

    def __init__(self, title: str):
        super().__init__()
        self._title = title
        self.setAlignment(Qt.AlignCenter)
        self.setWordWrap(True)
        self.setMinimumHeight(34)
        self.set_state(active=False, placeholder=True)

    def set_state(self, active: bool, placeholder: bool = False, text: str | None = None):
        shown = text if text else self._title
        self.setText(shown)
        if active:
            bg, fg, border = "#B9790F", "#241A02", "#B9790F"
        else:
            bg, fg, border = "#1B2630", ("#58D88C" if placeholder is False else "#7E8E9C"), "#2A3744"
        self.setStyleSheet(
            f"background: {bg}; color: {fg}; border: 1px solid {border}; "
            f"border-radius: 4px; font-size: 10px; font-weight: 700; padding: 4px;"
        )


class DashboardTab(QWidget):
    motor_start_requested = Signal()
    motor_stop_requested = Signal()
    estop_requested = Signal()
    config_saved = Signal(object)        # DashboardConfig
    tick = Signal(list)                  # o an yapılandırılmış A2L Measurement adları
    open_graph_requested = Signal()
    actuator_command = Signal(str, bool, float)  # actuator_key, enable, value
    gauge_sample = Signal(str, float)            # gösterge anahtarı, değer (Çalışma Alanı için)

    def __init__(self, sim_config=None):
        super().__init__()
        self.config = DashboardConfig()
        self._role = Role.OPERATOR
        self._override_confirmed_session = False
        self._actuator_armed: dict[str, bool] = {k: False for k in ACTUATOR_KEYS}
        self._actuator_last_value: dict[str, float] = {k: 0.0 for k in ACTUATOR_KEYS}
        self._gauge_widgets: dict[str, GaugeWidget] = {}
        self._tile_value_labels: dict[str, QLabel] = {}
        self._graph_series: dict[str, dict] = {}   # sinyal kimliği -> {x, y, curve}
        self._graph_t = 0.0
        self._measurement_names: list[str] = []     # yüklü A2L ölçüm adları
        self._measurement_limits: dict[str, tuple] = {}  # ad -> (min, max)

        # NOT: Annunciator (ikaz lambası) şeridi ve eski "Motor Komutları /
        # Ortam Koşulları" dar sütunu, referans mockup'ta Ana Sayfa'nın bu
        # konumunda HİÇ görünmüyor (bkz. görev tanımı madde 3-4). Alttaki
        # veri/mantık (self._lamps, motor komutu düğmeleri, ortam
        # etiketleri) KORUNUR — yalnızca bu widget'lar artık görünür
        # düzene eklenmiyor; düğmeler bunun yerine MainWindow'un üst
        # "Motoru Başlat / Durdur / Acil Durdurma + durum" satırına monte
        # edilir (bkz. app/ui/main_window.py _build_action_status_row).
        self._build_annunciator_strip()  # self._lamps'i doldurur, gösterilmez
        self._build_motor_group()        # start/stop/estop düğmelerini oluşturur
        self._build_ambient_group()      # ortam etiketlerini oluşturur (gizli)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Yerleşim: SOL = "gönderdiklerim" (Simülasyon Girişleri + Eyleyiciler),
        # SAĞ = "izlediklerim": üstte Motor Parametreleri (4x2) yanında Sensör
        # tablosu, altta kalan tüm alanı dolduran Canlı Grafik. Sayfa küçük
        # ekranda ezilmek yerine dikey kayar. DBC/A2L eşlemeleri "⚙ Eşlemeler"
        # penceresinde.
        from app.ui.sim_inputs import SimInputsPanel
        self.sim_inputs = SimInputsPanel(sim_config)
        content = QWidget()
        content.setMinimumHeight(820)
        columns = QHBoxLayout(content)
        columns.setContentsMargins(12, 10, 12, 12)
        columns.setSpacing(10)
        left = QVBoxLayout()
        left.setSpacing(10)
        left.setContentsMargins(0, 0, 0, 0)
        self.sim_inputs.setMinimumWidth(320)
        self.sim_inputs.setMaximumWidth(360)
        left.addWidget(self.sim_inputs, 0)
        left.addWidget(self._build_actuators_group(), 1)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(350)
        right = QVBoxLayout()
        right.setSpacing(10)
        right.setContentsMargins(0, 0, 0, 0)
        self._top_row = QBoxLayout(QBoxLayout.LeftToRight)
        self._top_row.setSpacing(10)
        self._top_row.addWidget(self._build_gauges_group(), 11)
        right.addLayout(self._top_row, 0)
        right.addWidget(self._build_graph_group(), 1)
        right_w = QWidget()
        right_w.setLayout(right)
        columns.addWidget(left_w, 0)
        columns.addWidget(right_w, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self._build_settings_dialog()

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_INTERVAL_MS)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start()

    # ======================================================================
    # Annunciator şeridi
    # ======================================================================
    def _build_annunciator_strip(self) -> QWidget:
        strip = QWidget()
        strip.setStyleSheet("background: #101820; border-radius: 6px;")
        strip.setFixedHeight(48)
        layout = QHBoxLayout(strip)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(6)
        self._lamps: dict[str, _LampCell] = {}
        for key, title in _LAMP_KEYS:
            cell = _LampCell(title)
            self._lamps[key] = cell
            layout.addWidget(cell, stretch=1)
        return strip

    def set_lamp(self, key: str, active: bool, text: str | None = None):
        """Gerçek DBC/CCP sinyali bağlandığında MainWindow bunu çağırır.
        Şu an hiçbir lamba gerçek bir sinyale bağlı değil (DBC'de henüz
        karşılığı netleşmedi); varsayılan durumları pasif/dim'dir."""
        lamp = self._lamps.get(key)
        if lamp is not None:
            lamp.set_state(active=active, placeholder=False, text=text)

    # ======================================================================
    # Motor komutu düğmeleri + Ortam etiketleri.
    #
    # Referans mockup'ta bunlar artık Ana Sayfa'nın ayrı bir "Motor
    # Komutları" sütununda GÖRÜNMÜYOR: start/stop/estop düğmeleri,
    # MainWindow'un üst "buton + durum" satırına monte edilir (bkz.
    # app/ui/main_window.py), bu yüzden burada widget'lar oluşturulur
    # ama hiçbir yerel layout'a eklenmez — MainWindow onları alıp kendi
    # satırına yerleştirir. Ortam etiketleri de aynı şekilde yalnızca
    # veri taşıyıcı olarak var olur (set_ambient_value hâlâ çalışır).
    # ======================================================================
    def _build_motor_group(self):
        self.power_on_button = QPushButton("Sistemi Aç")
        self.start_button = QPushButton("Motoru Başlat")
        self.start_button.setProperty("primary", True)
        self.stop_button = QPushButton("Motoru Durdur")
        self.estop_button = QPushButton("ACİL SUSTURMA")
        self.estop_button.setProperty("danger", True)
        self.estop_button.setMinimumHeight(40)

        self.power_on_button.clicked.connect(lambda: None)  # henüz ayrı bir DBC komutu yok
        self.start_button.clicked.connect(self._on_start_clicked)
        self.stop_button.clicked.connect(self._on_stop_clicked)
        self.estop_button.clicked.connect(self._on_estop_clicked)

    def _on_start_clicked(self):
        self.motor_start_requested.emit()

    def _on_stop_clicked(self):
        self.motor_stop_requested.emit()

    def _on_estop_clicked(self):
        confirm = QMessageBox.warning(
            self, "ACİL SUSTURMA gönderilsin mi?",
            "Motoru derhal durdurmak üzere ACİL SUSTURMA komutu gönderilecek. Devam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if confirm == QMessageBox.Yes:
            self.estop_requested.emit()

    def _build_ambient_group(self):
        """Ortam değeri etiketlerini oluşturur (bkz. yukarıdaki sınıf
        yorumu) — referans mockup'ta Ana Sayfa'da AYRI bir "Ortam
        Koşulları" paneli olarak görünmüyor; etiketler yalnızca veri
        taşıyıcı olarak tutulur, hiçbir layout'a eklenmez."""
        self._ambient_labels: dict[str, QLabel] = {}
        for key in AMBIENT_KEYS:
            value_label = QLabel("—")
            self._ambient_labels[key] = value_label

    def set_ambient_value(self, key: str, text: str):
        label = self._ambient_labels.get(key)
        if label is not None:
            label.setText(text)

    # ======================================================================
    # SOL sütun (~%65): Motor Parametreleri (8 eşit boyutlu gösterge, 4x2
    # ızgara) üstte, Sensör Durumu ve Arıza Tablosu altta — dikey istiflenmiş.
    # ======================================================================
    def _build_column_left(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_gauges_group(), stretch=0)
        return col

    def _build_gauges_group(self) -> QGroupBox:
        box = QGroupBox()
        _style_card_group(box)
        lay = QVBoxLayout()
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(_card_title("Motor Parametreleri"))
        head.addStretch(1)
        self.map_warn_label = QLabel("")
        self.map_warn_label.setStyleSheet("color:#B9790F; font-size:11px; font-weight:700;")
        self.settings_button = QPushButton("⚙ Eşlemeler")
        self.settings_button.setFixedHeight(26)
        self.settings_button.setToolTip("Göstergelerin A2L ölçümlerine ve komutların DBC sinyallerine bağlanması "
                                        "(bir kerelik kurulum)")
        self.settings_button.clicked.connect(lambda: self.settings_dialog.exec())
        head.addWidget(self.map_warn_label)
        head.addWidget(self.settings_button)
        lay.addLayout(head)
        lay.addWidget(self._build_sensor_table_group())
        self.gauge_grid = ReflowGrid([4, 2], 118, spacing=8)
        for key in GAUGE_KEYS:
            minimum, maximum, unit = GAUGE_RANGES[key]
            display_label = GAUGE_DISPLAY_LABELS.get(key, key)
            gauge = GaugeWidget(display_label, minimum, maximum, unit)
            self._gauge_widgets[key] = gauge
            self.gauge_grid.add_item(self._wrap_gauge_card(gauge))
        lay.addWidget(self.gauge_grid)
        box.setLayout(lay)
        return box

    def _update_map_warning(self):
        miss = [k for k in GAUGE_KEYS if not self.config.gauge_measurement_map().get(k)]
        self.map_warn_label.setText(f"⚠ {len(miss)} gösterge bağlı değil" if miss else "")

    def _build_settings_dialog(self):
        from PySide6.QtWidgets import QDialog
        box = self._build_settings_group()
        box.setCheckable(False)
        dlg = QDialog(self)
        dlg.setWindowTitle("Eşleme ayarları — DBC / A2L")
        dlg.resize(1100, 760)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        sc.setWidget(box)
        lay = QVBoxLayout(dlg)
        lay.addWidget(sc)
        self.save_button.clicked.connect(dlg.accept)
        self.settings_dialog = dlg
        self.settings_box = box

    def _wrap_gauge_card(self, gauge: GaugeWidget) -> QFrame:
        """Tek bir gösterge ibresini, beyaz zeminli/yuvarlak köşeli ve
        hafif gölgeli bir "kart" çerçevesi içine sarar (görev tanımı
        madde 5: her gösterge karosu da diğer paneller gibi kart
        görünümünde olmalı)."""
        card = QFrame()
        card.setObjectName("gaugeCard")
        card.setStyleSheet(
            f"QFrame#gaugeCard {{ background: {SURFACE}; border: 1px solid #EEF2F6; "
            f"border-radius: 10px; }}"
        )
        _apply_card_shadow(card, blur=14, dy=2, alpha=30)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(2, 4, 2, 4)
        layout.addWidget(gauge)
        return card

    def _build_sensor_table_group(self) -> QWidget:
        """İnce sensör sağlığı şeridi (kart değil): "Sensör sağlığı [Arıza yok]".
        Yalnızca ARIZALI sensörler, şeridin yanında kırmızı etiketlerle listelenir."""
        from PySide6.QtCore import QTimer

        strip = QWidget()
        strip.setStyleSheet("background:transparent;")
        row = QHBoxLayout(strip)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        cap = QLabel("Sensör sağlığı")
        cap.setStyleSheet("color:#5B6B79; font-size:12px; font-weight:700;")
        row.addWidget(cap)
        self._sensor_pill = QLabel("İzlenmiyor")
        row.addWidget(self._sensor_pill)
        self._sensor_fault_box = row
        row.addStretch(1)
        self._sensor_fault_labels = []
        self.refresh_sensor_health()
        self._sensor_timer = QTimer(self)
        self._sensor_timer.timeout.connect(self.refresh_sensor_health)
        self._sensor_timer.start(1000)
        return strip

    def refresh_sensor_health(self):
        """Arızalı (ok is False) sensör/kontrol çiftlerini yeniden listeler."""
        faults = {}
        for sensor in _SENSOR_ROWS:
            bad = [c for c in _SENSOR_CHECKS if get_sensor_status(sensor, c)[0] is False]
            if bad:
                faults[sensor] = bad
        for w in self._sensor_fault_labels:
            self._sensor_fault_box.removeWidget(w)
            w.deleteLater()
        self._sensor_fault_labels = []
        if faults:
            self._sensor_pill.setText(f"{len(faults)} arıza")
            self._sensor_pill.setStyleSheet(
                "background:#FBE9E7; color:#B3261E; border-radius:8px; padding:1px 8px;"
                " font-size:11px; font-weight:700;")
            for sensor, bad in faults.items():
                lbl = QLabel(f"<b>{sensor}</b> — {', '.join(bad)}")
                lbl.setStyleSheet("color:#B3261E; font-size:12px; background:transparent;")
                self._sensor_fault_box.insertWidget(self._sensor_fault_box.count() - 1, lbl)
                self._sensor_fault_labels.append(lbl)
        elif not SENSOR_MONITORING_AVAILABLE:
            self._sensor_pill.setText("İzlenmiyor")
            self._sensor_pill.setToolTip("Sensör arıza bitleri henüz bir DBC/A2L kaynağına bağlı değil.")
            self._sensor_pill.setStyleSheet(
                "background:#ECEFF1; color:#5F6B76; border-radius:8px; padding:1px 8px;"
                " font-size:11px; font-weight:700;")
        else:
            self._sensor_pill.setText("Arıza yok")
            self._sensor_pill.setStyleSheet(
                "background:#E3F4EA; color:#1B8A4C; border-radius:8px; padding:1px 8px;"
                " font-size:11px; font-weight:700;")

    def set_gauge_value(self, key: str, value):
        gauge = self._gauge_widgets.get(key)
        if gauge is not None:
            gauge.set_value(value)
        if isinstance(value, (int, float)):
            self._append_graph_sample(f"g:{key}", value)
            self.gauge_sample.emit(key, float(value))

    # ======================================================================
    # SAĞ sütun (~%35): Canlı Grafik üstte, Eyleyiciler altta.
    # ======================================================================
    def _build_column_right(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_graph_group(), stretch=1)
        layout.addWidget(self._build_actuators_group(), stretch=0)
        return col

    def _build_graph_group(self) -> QGroupBox:
        box = QGroupBox()
        _style_card_group(box)
        layout = QVBoxLayout()

        title_row = QHBoxLayout()
        title_row.addWidget(_card_title("Canlı Grafik (son ~60 sn)"))
        title_row.addStretch()
        self.graph_normalize = QCheckBox("Normalize (0–1)")
        self.graph_normalize.setToolTip("Her seri kendi aralığına göre 0–1'e ölçeklenir "
                                        "(farklı birimleri tek eksende karşılaştırmak için).")
        self.graph_normalize.toggled.connect(lambda _v: self._redraw_graph())
        title_row.addWidget(self.graph_normalize)
        self.graph_pick_button = QPushButton("Sinyalleri seç")
        self.graph_pick_button.setToolTip("Grafikte çizilecek sinyalleri seç (sayı ve tür serbest).")
        self.graph_pick_button.clicked.connect(self._on_pick_graph_signals)
        title_row.addWidget(self.graph_pick_button)
        layout.addLayout(title_row)

        pg.setConfigOptions(antialias=True)
        # Alt eksen göreli saniye (−60 … şimdi) gösterir; x değerleri GERÇEK
        # epoch zaman damgasıdır (bkz. _ClockAxisItem).
        clock_axis = _ClockAxisItem(orientation="bottom")
        self.graph_widget = pg.PlotWidget(background="#FFFFFF", axisItems={"bottom": clock_axis})
        self.graph_widget.showGrid(x=True, y=True, alpha=0.2)
        self.graph_widget.setMinimumHeight(200)
        self.graph_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.graph_widget.setMaximumHeight(16777215)  # pyqtgraph'ın büyük varsayılan
        # sizeHint'i yüzünden sınırlanmazsa panel aşırı uzuyor.
        self._graph_legend = self.graph_widget.addLegend(
            offset=(8, 6), labelTextColor=INK, labelTextSize="10pt",
            brush=pg.mkBrush(255, 255, 255, 215), pen=pg.mkPen("#E3EAF1"))
        self.graph_widget.setXRange(time.time() - 60.0, time.time(), padding=0)
        layout.addWidget(self.graph_widget, stretch=1)

        box.setLayout(layout)
        self._rebuild_graph_series()
        return box

    # ---- Sinyal seçimi ---------------------------------------------------
    def set_measurements(self, measurements):
        """Yüklü A2L'deki ölçümleri (MeasurementInfo listesi) bildirir."""
        self._measurement_names = [m.name for m in measurements]
        self._measurement_limits = {
            m.name: (m.minimum, m.maximum) for m in measurements
            if m.minimum is not None and m.maximum is not None and m.maximum > m.minimum
        }

    def graph_measurement_names(self) -> list:
        """Grafik için seçilmiş A2L ölçüm adları (gösterge eşlemesinden bağımsız)."""
        return [sid[2:] for sid in self.config.graph_signals if sid.startswith("m:")]

    def _on_pick_graph_signals(self):
        from app.ui.graph_signal_dialog import GraphSignalDialog
        dlg = GraphSignalDialog(GAUGE_KEYS, self._measurement_names,
                                self.config.graph_signals, self)
        if dlg.exec() != GraphSignalDialog.Accepted:
            return
        self.set_graph_signals(dlg.selected_ids(), persist=True)

    def set_graph_signals(self, ids: list, persist: bool = False):
        self.config.graph_signals = list(ids)
        self._rebuild_graph_series()
        if persist:
            self.config_saved.emit(self.config)

    def _rebuild_graph_series(self):
        """Seçime göre eğrileri yeniden kurar; ortak sinyallerin geçmişi korunur."""
        from app.ui.graph_signal_dialog import signal_label
        old = self._graph_series
        for sid, ser in old.items():
            self.graph_widget.removeItem(ser["curve"])
        if getattr(self, "_graph_legend", None) is not None:
            self._graph_legend.clear()
        self._graph_series = {}
        for i, sid in enumerate(self.config.graph_signals):
            color = _GRAPH_PALETTE[i % len(_GRAPH_PALETTE)]
            name = signal_label(sid)
            if sid.startswith("g:") and name in GAUGE_RANGES:
                name = f"{name} [{GAUGE_RANGES[name][2]}]"
            curve = self.graph_widget.plot([], [], pen=pg.mkPen(color, width=2), name=name)
            prev = old.get(sid)
            self._graph_series[sid] = {"x": prev["x"] if prev else [],
                                       "y": prev["y"] if prev else [], "curve": curve}
        self._redraw_graph()
        if hasattr(self, "graph_pick_button"):
            n = len(self._graph_series)
            self.graph_pick_button.setText(f"Sinyalleri seç ({n})")

    def add_measurement_sample(self, name: str, value: float):
        """Seçili bir A2L ölçümünün okunan değerini grafiğe ekler."""
        if isinstance(value, (int, float)):
            self._append_graph_sample(f"m:{name}", float(value))

    def _append_graph_sample(self, key: str, value: float):
        series = self._graph_series.get(key)
        if series is None:
            return
        now = time.time()
        series["x"].append(now)
        series["y"].append(value)
        # Kayan ~60 saniyelik pencere: hem nokta sayısına (emniyet üst
        # sınırı) hem de gerçek zamana göre kırpılır.
        cutoff = now - 60.0
        while series["x"] and series["x"][0] < cutoff:
            series["x"].pop(0)
            series["y"].pop(0)
        if len(series["x"]) > _GRAPH_MAX_POINTS:
            series["x"] = series["x"][-_GRAPH_MAX_POINTS:]
            series["y"] = series["y"][-_GRAPH_MAX_POINTS:]
        self._redraw_graph(key)

    def _graph_ys(self, key: str, ys: list) -> list:
        if getattr(self, "graph_normalize", None) is None or not self.graph_normalize.isChecked():
            return ys
        lo = hi = None
        if key.startswith("g:") and key[2:] in GAUGE_RANGES:
            lo, hi, _u = GAUGE_RANGES[key[2:]]
        elif key.startswith("m:") and key[2:] in self._measurement_limits:
            lo, hi = self._measurement_limits[key[2:]]
        if lo is None or hi is None:           # aralık yoksa: penceredeki min/max
            if not ys:
                return ys
            lo, hi = min(ys), max(ys)
        span = (hi - lo) or 1.0
        return [(y - lo) / span for y in ys]

    def _redraw_graph(self, only: str | None = None):
        for k, series in self._graph_series.items():
            if only is not None and k != only:
                continue
            series["curve"].setData(series["x"], self._graph_ys(k, series["y"]))
        norm = self.graph_normalize.isChecked()
        self.graph_widget.getAxis("left").setLabel("normalize (0–1)" if norm else "")
        now = time.time()
        self.graph_widget.setXRange(now - 60.0, now, padding=0)

    def _build_actuators_group(self) -> QGroupBox:
        box = QGroupBox()
        _style_card_group(box)
        lay = QVBoxLayout()
        lay.setSpacing(6)
        lay.addWidget(_card_title("Eyleyiciler (manuel override)"))
        warn = QLabel("⚠  Override: ECU kendi kararını kullanmaz")
        warn.setWordWrap(True)
        warn.setStyleSheet("color:#B9790F; font-size:12px; font-weight:600;")
        lay.addWidget(warn)
        self.actuator_rows: dict[str, dict] = {}
        self._actuator_labels: dict[str, QLabel] = {}
        self._actuator_channel_boxes: dict[str, QComboBox] = {}
        grid = ReflowGrid([2], 120, spacing=8, stretch_rows=True)

        for key in ACTUATOR_KEYS:
            chip = QFrame()
            chip.setObjectName("actChip")
            chip.setStyleSheet("QFrame#actChip { background:#F5F8FA; border:1px solid #E3EAF1; border-radius:8px; }"
                               "QFrame#actChip QLabel { background:transparent; }")
            cl = QVBoxLayout(chip)
            cl.setContentsMargins(12, 6, 12, 6)
            cl.setSpacing(4)
            label = QLabel(ACTUATOR_LABELS[key])
            label.setStyleSheet("font-size: 13px; font-weight:700;")
            self._actuator_labels[key] = label
            feedback = QLabel("—")
            feedback.setStyleSheet("color: #5B6B79; font-size: 12px; font-weight:600;")
            feedback.setToolTip("Son bilinen gerçek durum (geri besleme) — komut edilen değerden ayrıdır.")
            label.setWordWrap(True)
            kind = ACTUATOR_KINDS[key]
            chan = QComboBox()
            chan.addItem("CAN", "can")
            chan.addItem("A2L", "a2l")
            chan.setFixedWidth(56)
            chan.setToolTip("Komutun gönderileceği kanal: CAN (DBC mesajı) veya A2L (CCP ile değişken yazımı).")
            chan.setStyleSheet("QComboBox { font-size:11px; font-weight:700; padding:1px 4px; }")
            cur = self.config.actuators.get(key, ActuatorCommand()).channel
            chan.setCurrentIndex(1 if cur == "a2l" else 0)
            chan.currentIndexChanged.connect(lambda _i, k=key, c=chan: self._on_actuator_channel(k, c.currentData()))
            self._actuator_channel_boxes[key] = chan
            cl.addWidget(label)
            row = QHBoxLayout()
            row.setSpacing(6)
            if kind == "toggle":
                switch = ToggleSwitch()
                switch.toggled.connect(lambda checked, k=key: self._on_actuator_toggle(k, checked))
                row.addWidget(switch)
                row.addWidget(feedback, 1)
                row.addWidget(chan)
                self.actuator_rows[key] = {"kind": kind, "control": switch, "feedback": feedback,
                                            "override_checkbox": None}
                cl.addLayout(row)
            else:
                spin = QDoubleSpinBox()
                spin.setRange(0.0, 100.0)
                spin.setSuffix(" %")
                spin.setEnabled(False)
                override_checkbox = QCheckBox("Manuel")
                override_checkbox.setStyleSheet("font-size: 12px; font-weight:600;")
                override_checkbox.toggled.connect(lambda checked, k=key: self._on_actuator_toggle(k, checked))
                spin.valueChanged.connect(lambda v, k=key: self._on_actuator_value_changed(k, v))
                row.addWidget(override_checkbox)
                row.addWidget(feedback, 1)
                row.addWidget(chan)
                self.actuator_rows[key] = {"kind": kind, "control": spin, "feedback": feedback,
                                            "override_checkbox": override_checkbox}
                cl.addLayout(row)
                cl.addWidget(spin)
            grid.add_item(chip)
        lay.addWidget(grid)
        box.setLayout(lay)
        return box

    def _on_actuator_channel(self, key: str, channel: str):
        """Eyleyicinin kanalını (CAN/A2L) değiştirir ve kalıcı kaydeder."""
        cmd = self.config.actuators.setdefault(key, ActuatorCommand())
        if cmd.channel == channel:
            return
        if self._actuator_armed.get(key):
            # Açıkken kanal değişirse eski kanalda override açık kalmasın.
            row = self.actuator_rows[key]
            ctl = row["override_checkbox"] or row["control"]
            if hasattr(ctl, "setChecked"):
                (row["override_checkbox"] or row["control"]).setChecked(False)
        cmd.channel = channel
        self.config_saved.emit(self.config)

    def reset_actuators_unknown(self):
        """Bağlantı kapandı: ECU'daki override durumu BİLİNMİYOR. Anahtarları
        komut göndermeden kapalıya çeker ve 'Bilinmiyor' gösterir; böylece UI
        'KAPALI' diyerek yanlış güvence vermez, tekrar açmak yeni onay ister."""
        for key, row in self.actuator_rows.items():
            widget = row["override_checkbox"] if ACTUATOR_KINDS[key] == "valve" else row["control"]
            if hasattr(widget, "setChecked"):
                widget.blockSignals(True)
                widget.setChecked(False)
                widget.blockSignals(False)
            if ACTUATOR_KINDS[key] == "valve":
                row["control"].setEnabled(False)
            was_armed = self._actuator_armed.get(key)
            self._actuator_armed[key] = False
            self._mark_actuator_armed(key, False)
            if was_armed:
                self.set_actuator_feedback(key, "Bilinmiyor (bağlantı kapandı)")
        self._override_confirmed_session = False

    def _mark_actuator_armed(self, key: str, armed: bool):
        lbl = self._actuator_labels.get(key)
        if lbl is not None:
            lbl.setStyleSheet("font-size:11px; font-weight:700; color:#8A5A00; background:#FFF1D6; "
                              "border-radius:4px; padding:2px 6px;" if armed else "font-size:11px;")

    # ---- Eyleyici override mantığı (gating + güvenlik) --------------------
    def set_role(self, role: Role):
        self._role = role

    def _commanded_value(self, key: str) -> float:
        kind = ACTUATOR_KINDS[key]
        row = self.actuator_rows[key]
        if kind == "toggle":
            return 1.0
        return float(row["control"].value())

    def _on_actuator_toggle(self, key: str, checked: bool):
        """Hem toggle anahtarları HEM DE valf satırındaki 'Override'
        onay kutusu buraya bağlıdır: ikisi de 'override aç/kapat'
        anlamına gelir."""
        if checked:
            if not can_override_actuator(self._role):
                QMessageBox.warning(
                    self, "Yetki yok",
                    f"{ACTUATOR_LABELS[key]} override'ını açmak için Mühendis veya "
                    "Yönetici rolü gerekir (Kullanıcı / Profil sekmesinden rol seçin).",
                )
                self._revert_actuator_control(key, False)
                return
            if not self._override_confirmed_session:
                confirm = QMessageBox.warning(
                    self, "EYLEYİCİ OVERRIDE — devam edilsin mi?",
                    "Bu kontrol, GERÇEK donanımı (veya MATLAB/Simulink override "
                    "anahtar bloğunu) doğrudan sürer. Yalnızca motor ÇALIŞMIYORKEN,"
                    " bileşen/HIL testi amacıyla kullanılmalıdır.\n\n"
                    "Yanlış bir değer gönderimi donanıma zarar verebilir. "
                    "Gerçekten devam etmek istediğinizden emin misiniz?",
                    QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
                )
                if confirm != QMessageBox.Yes:
                    self._revert_actuator_control(key, False)
                    return
                self._override_confirmed_session = True

            self._actuator_armed[key] = True
            self._mark_actuator_armed(key, True)
            value = self._commanded_value(key)
            self._actuator_last_value[key] = value
            if ACTUATOR_KINDS[key] == "valve":
                self.actuator_rows[key]["control"].setEnabled(True)
            self.actuator_command.emit(key, True, value)
        else:
            self._actuator_armed[key] = False
            self._mark_actuator_armed(key, False)
            self.actuator_command.emit(key, False, self._actuator_last_value.get(key, 0.0))
            if ACTUATOR_KINDS[key] == "valve":
                self.actuator_rows[key]["control"].setEnabled(False)

    def _revert_actuator_control(self, key: str, checked: bool):
        kind = ACTUATOR_KINDS[key]
        row = self.actuator_rows[key]
        widget = row["override_checkbox"] if kind == "valve" else row["control"]
        widget.blockSignals(True)
        widget.setChecked(checked)
        widget.blockSignals(False)

    def _on_actuator_value_changed(self, key: str, value: float):
        """Yalnızca override ZATEN açıkken (valf satırı etkinken) bir
        gönderim tetikler; override kapalıyken değer sadece yerelde
        arabelleğe alınır, HİÇBİR ŞEY gönderilmez (bkz. CRITICAL
        override-gating gereksinimi)."""
        self._actuator_last_value[key] = value
        if self._actuator_armed.get(key):
            self.actuator_command.emit(key, True, value)

    def set_actuator_feedback(self, key: str, text: str):
        row = self.actuator_rows.get(key)
        if row is not None:
            row["feedback"].setText(text)

    # ======================================================================
    # Ayarlar (DBC / A2L eşlemeleri) — Motor komutları + 8 gösterge +
    # 4 ortam değeri + 5 eyleyici override komutu.
    # ======================================================================
    def _build_settings_group(self) -> QGroupBox:
        box = QGroupBox("Ayarlar — DBC / A2L eşlemeleri (bir kere girilip kaydedilir)")
        box.setCheckable(True)
        box.setChecked(True)  # referans mockup'ta açık/dolu görünüyor — varsayılan açık
        _style_card_group(box)

        # ---- Ölçüm eşlemeleri: 8 gösterge + 4 ortam değeri, İKİ sütun
        # halinde yan yana (referans mockup'taki düzen) — tek sütunda
        # alt alta istiflemek yerine, bu dikey alanı yaklaşık yarıya
        # indirir ve QFormLayout satırlarının sıkışıp üst üste binmesini
        # önler (bkz. bu metodun docstring'indeki hata açıklaması).
        self.meas_edits: dict[str, QLineEdit] = {}
        self.ambient_edits: dict[str, QLineEdit] = {}

        meas_left_form = QFormLayout()
        meas_left_form.setSpacing(4)
        meas_right_form = QFormLayout()
        meas_right_form.setSpacing(4)

        for key in GAUGE_KEYS:
            edit = QLineEdit()
            edit.setPlaceholderText("A2L Measurement ismi, örn: N_RPM")
            self.meas_edits[key] = edit
            meas_left_form.addRow(f"{key} → Ölçüm:", edit)

        for key in AMBIENT_KEYS:
            edit = QLineEdit()
            edit.setPlaceholderText("A2L Measurement ismi")
            self.ambient_edits[key] = edit
            meas_right_form.addRow(f"{AMBIENT_LABELS[key]} → Measurement:", edit)
        meas_right_form.addRow(QLabel(""))  # sağ sütunu sola görsel olarak hizalar

        meas_columns = QHBoxLayout()
        meas_columns.setSpacing(18)
        meas_columns.addLayout(meas_left_form, 1)
        meas_columns.addLayout(meas_right_form, 1)

        # ---- Motor / sistem komutları: iki sütun halinde kompakt satırlar.
        self.motor_edits: dict[str, dict[str, QLineEdit]] = {}
        self.actuator_edits: dict[str, dict[str, QLineEdit]] = {}

        cmd_left_form = QFormLayout()
        cmd_left_form.setSpacing(4)
        cmd_right_form = QFormLayout()
        cmd_right_form.setSpacing(4)

        motor_rows = (("Motor Başlat", "motor_start"), ("Motor Durdur", "motor_stop"),
                      ("Acil Susturma", "estop"))
        for label, cmd_key in motor_rows:
            msg_edit = QLineEdit()
            msg_edit.setPlaceholderText("DBC mesaj ismi")
            sig_edit = QLineEdit()
            sig_edit.setPlaceholderText("DBC sinyal ismi")
            val_edit = QLineEdit()
            val_edit.setPlaceholderText("değer, örn: 1")
            val_edit.setMaximumWidth(60)
            self.motor_edits[cmd_key] = {"message": msg_edit, "signal": sig_edit, "value": val_edit}
            row = QHBoxLayout()
            row.addWidget(msg_edit)
            row.addWidget(sig_edit)
            row.addWidget(val_edit)
            cmd_left_form.addRow(f"{label}:", row)

        for key in ACTUATOR_KEYS:
            msg_edit = QLineEdit()
            msg_edit.setPlaceholderText("DBC mesaj ismi")
            en_edit = QLineEdit()
            en_edit.setPlaceholderText("override enable sinyali")
            val_edit = QLineEdit()
            val_edit.setPlaceholderText("komut değeri sinyali")
            a_en = QLineEdit()
            a_en.setPlaceholderText("A2L enable değişkeni")
            a_val = QLineEdit()
            a_val.setPlaceholderText("A2L değer değişkeni")
            self.actuator_edits[key] = {"message": msg_edit, "enable_signal": en_edit, "value_signal": val_edit,
                                        "a2l_enable": a_en, "a2l_value": a_val}
            row = QHBoxLayout()
            row.addWidget(msg_edit)
            row.addWidget(en_edit)
            row.addWidget(val_edit)
            row2 = QHBoxLayout()
            row2.addWidget(a_en)
            row2.addWidget(a_val)
            vb = QVBoxLayout()
            vb.setSpacing(2)
            vb.addLayout(row)
            vb.addLayout(row2)
            cmd_right_form.addRow(f"{ACTUATOR_LABELS[key]}:", vb)

        cmd_columns = QHBoxLayout()
        cmd_columns.setSpacing(18)
        cmd_columns.addLayout(cmd_left_form, 1)
        cmd_columns.addLayout(cmd_right_form, 1)

        self.save_button = QPushButton("Ayarları Kaydet")
        self.save_button.setProperty("primary", True)
        self.save_button.clicked.connect(self._on_save_clicked)

        info = QLabel(
            "Motor/eyleyici komutu satırları: Mesaj ismi / Sinyal ismi / Değer. "
            "Gönderim, Gönderim sekmesinde yüklü olan aynı DBC dosyasını kullanır."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #5B6B79;")

        # Onaylanan tasarıma göre: panel İÇ KAYDIRMA içermez — tüm alanlar
        # (ölçüm eşlemeleri + motor/eyleyici komutları) tek seferde, kendi
        # doğal yüksekliğince görünür. Üst üste binme riski zaten 2 sütunlu
        # ızgara + kompakt satır yüksekliğiyle (görev: "Ayarlar panelinin
        # üst üste binmesi" düzeltmesi) ortadan kaldırıldı; artık ayrıca
        # bir QScrollArea'ya da gerek yok (kullanıcı: "aşağı sürüklenme
        # şeklinde olmasın, tam o sayfaya sığacak hale getir").
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 2, 2)
        content_layout.setSpacing(10)
        content_layout.addLayout(meas_columns)
        content_layout.addLayout(cmd_columns)
        content_layout.addWidget(info)
        content_layout.addWidget(self.save_button)

        layout = QVBoxLayout()
        layout.addWidget(content)
        box.setLayout(layout)
        content.setVisible(box.isChecked())
        box.toggled.connect(content.setVisible)
        return box

    def _on_save_clicked(self):
        cfg = DashboardConfig()
        gauge_attr = {
            "RPM": "measurement_rpm", "İtki": "measurement_itki", "PLA": "measurement_pla",
            "Tt5": "measurement_tt5", "FP": "measurement_fp", "FT": "measurement_ft",
            "Ps2": "measurement_ps2", "Tt2": "measurement_tt2",
        }
        for key, attr in gauge_attr.items():
            setattr(cfg, attr, self.meas_edits[key].text().strip())
        ambient_attr = {
            "BataryaV": "measurement_batarya", "OrtamBasinc": "measurement_ortam_basinc",
            "AtmSicaklik": "measurement_atm_sicaklik", "Tt0": "measurement_tt0",
        }
        for key, attr in ambient_attr.items():
            setattr(cfg, attr, self.ambient_edits[key].text().strip())
        for cmd_key in ("motor_start", "motor_stop", "estop"):
            edits = self.motor_edits[cmd_key]
            try:
                value = float(edits["value"].text().strip().replace(",", ".") or "1")
            except ValueError:
                value = 1.0
            setattr(cfg, cmd_key, MotorCommand(
                message=edits["message"].text().strip(),
                signal=edits["signal"].text().strip(),
                value=value,
            ))
        actuators = {}
        for key in ACTUATOR_KEYS:
            edits = self.actuator_edits[key]
            actuators[key] = ActuatorCommand(
                message=edits["message"].text().strip(),
                enable_signal=edits["enable_signal"].text().strip(),
                value_signal=edits["value_signal"].text().strip(),
                channel=self.config.actuators.get(key, ActuatorCommand()).channel,
                a2l_enable=edits["a2l_enable"].text().strip(),
                a2l_value=edits["a2l_value"].text().strip(),
            )
        cfg.actuators = actuators
        cfg.graph_signals = list(self.config.graph_signals)
        self.set_config(cfg)
        self.config_saved.emit(cfg)

    def set_config(self, cfg: DashboardConfig):
        self.config = cfg
        if hasattr(self, "graph_widget"):
            self._rebuild_graph_series()
        self._update_map_warning()
        gauge_attr = {
            "RPM": "measurement_rpm", "İtki": "measurement_itki", "PLA": "measurement_pla",
            "Tt5": "measurement_tt5", "FP": "measurement_fp", "FT": "measurement_ft",
            "Ps2": "measurement_ps2", "Tt2": "measurement_tt2",
        }
        for key, attr in gauge_attr.items():
            self.meas_edits[key].setText(getattr(cfg, attr, ""))
        ambient_attr = {
            "BataryaV": "measurement_batarya", "OrtamBasinc": "measurement_ortam_basinc",
            "AtmSicaklik": "measurement_atm_sicaklik", "Tt0": "measurement_tt0",
        }
        for key, attr in ambient_attr.items():
            self.ambient_edits[key].setText(getattr(cfg, attr, ""))
        for cmd_key in ("motor_start", "motor_stop", "estop"):
            cmd: MotorCommand = getattr(cfg, cmd_key)
            edits = self.motor_edits[cmd_key]
            edits["message"].setText(cmd.message)
            edits["signal"].setText(cmd.signal)
            edits["value"].setText(f"{cmd.value:g}")
        for key in ACTUATOR_KEYS:
            cmd: ActuatorCommand = cfg.actuators.get(key, ActuatorCommand())
            edits = self.actuator_edits[key]
            edits["message"].setText(cmd.message)
            edits["enable_signal"].setText(cmd.enable_signal)
            edits["value_signal"].setText(cmd.value_signal)
            edits["a2l_enable"].setText(cmd.a2l_enable)
            edits["a2l_value"].setText(cmd.a2l_value)
            box = getattr(self, "_actuator_channel_boxes", {}).get(key)
            if box is not None:
                box.blockSignals(True)
                box.setCurrentIndex(1 if cmd.channel == "a2l" else 0)
                box.blockSignals(False)

        self.start_button.setEnabled(bool(cfg.motor_start.message and cfg.motor_start.signal))
        self.stop_button.setEnabled(bool(cfg.motor_stop.message and cfg.motor_stop.signal))
        self.estop_button.setEnabled(bool(cfg.estop.message and cfg.estop.signal))
        for btn, cmd, label in ((self.start_button, cfg.motor_start, "Motoru Başlat"),
                                 (self.stop_button, cfg.motor_stop, "Motoru Durdur"),
                                 (self.estop_button, cfg.estop, "Acil Susturma")):
            if not btn.isEnabled():
                btn.setToolTip(f"{label} için DBC mesaj/sinyal ismi Ayarlar panelinden girilmedi.")
            else:
                btn.setToolTip("")

        if not cfg.measurement_map():
            for key in GAUGE_KEYS:
                self.set_gauge_value(key, None)
            for key in AMBIENT_KEYS:
                self.set_ambient_value(key, "—")

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        # Dar ekranda sensör tablosu göstergelerin yanına sığmaz: altına iner.
        wide = self.width() - 350 - 36 >= 820
        want = QBoxLayout.LeftToRight if wide else QBoxLayout.TopToBottom
        if self._top_row.direction() != want:
            self._top_row.setDirection(want)

    def _on_tick(self):
        now = time.time()
        self.graph_widget.setXRange(now - 60.0, now, padding=0)
        names = list(dict.fromkeys(list(self.config.measurement_map().values())
                                   + self.graph_measurement_names()))
        if names:
            self._graph_t += TICK_INTERVAL_MS / 1000.0
            self.tick.emit(names)
