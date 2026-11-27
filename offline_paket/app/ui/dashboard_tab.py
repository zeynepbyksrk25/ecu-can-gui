"""Ana Sayfa (Dashboard) — sidebar'sız, kaydırmasız, tek ekran (16" laptop) düzeni.

Sol sütun : Uçuş Koşulları + Motor Kontrol (``SimInputsPanel``) + Eyleyiciler
Sağ sütun : Motor Parametreleri (8 gösterge = 8 sensör) + Canlı Trendler

Sensörlerin ve eyleyicilerin her biri için iki değişken vardır: değer ve anahtar
(``_sw``). Anahtar 0 iken değer arayüzden DEĞİŞTİRİLEMEZ; kilit düğmesiyle anahtar
1 yapılınca (rol + onay kontrolünden sonra) değer yazılabilir. Hem değer hem
anahtar CAN (DBC) ya da A2L (CCP) kaynağından seçilir (bkz. app/dashboard_config.py,
app/ui/mapping_dialog.py).

Bu widget gerçek CAN/CCP işlemini kendisi yapmaz: ``writer`` geri çağrısı
(MainWindow) ve sinyaller aracılığıyla dışarı bildirir.
"""

import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)
from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QPainter, QPen, QRegularExpressionValidator
from PySide6.QtWidgets import QLineEdit

from app import theme
from app.dashboard_config import (
    ACTUATOR_KEYS, ACTUATOR_KINDS, CONTROL_KEYS, EYLEYICI_KEYS, GAUGE_KEYS, MODE_KEY, MOTOR_COMMAND_KEYS, SUB_MODE_KEYS,
    SENSOR_LABELS, SUB_MODE_TITLES, ACTIVE_SUB_MODES, SOURCE_A2L, Binding, DashboardConfig, mode_name, motor_mode_name,
)
from app.ui.dash_widgets import (  # noqa: F401  (ToggleSwitch: eski import yolu)
    ACCENTS, DK_CYAN, DK_MUT, DashGauge, GaugeCard, IconLabel, LockButton, MotorToggle, ToggleSwitch,
    format_value,
)
from app.ui.dark_theme import dark_qss
from app.ui.trend_panel import TrendPanel
from app.user_roles import Role, can_override_actuator

TICK_INTERVAL_MS = 500
STALE_S = 3.0

# Göstergelerin ölçekleri: (min, max, birim). Ekranda gösterilen DEĞER her zaman
# gerçek değerdir; ölçek yalnızca ibre/yay çizimi içindir.
GAUGE_RANGES = {
    "RPM": (0.0, 140000.0, "rpm", 118000.0),
    "İtki": (0.0, 270.0, "N", 255.0),
    "PLA": (0.0, 100.0, "%", None),
    "Tt5": (-40.0, 1200.0, "°C", 900.0),
    "FP_start": (0.0, 10.0, "bar", 5.0),
    "FP_main": (0.0, 10.0, "bar", 5.0),
    "FT": (-30.0, 40.0, "°C", None),
    "Ps2": (0.0, 2.5, "bar", 1.6),
    "Ps3": (0.0, 5.0, "bar", None),
}
# Kırmızı sınır aşılınca kartta yazan etiket (varsayılan "LİMİT").
# Motor Modu rengi (A2L EN_MODE_* sırası: 0 POWER ON ... 6 STOP)
MODE_COLORS = {0: theme.SLATE, 1: theme.BLUE, 2: theme.WARN, 3: theme.ACCENT, 4: theme.OK, 5: "#2A8FBD", 6: theme.DANGER}
# Alt mod adı -> renk (listede olmayan ad ACCENT; bilinmeyen sayı WARN).
SUB_MODE_COLORS = {"OFF": theme.SLATE, "ON": theme.OK, "COOLDOWN": "#2A8FBD", "SUCCESS": theme.OK,
                   "ABORT": theme.DANGER, "MAX": theme.WARN}
GAUGE_LIMIT_TEXT = {"RPM": "OVERSPEED", "Tt5": "AŞIRI SICAK"}

# Motor Parametreleri ızgarası (12 sütun): üst satır RPM (5) + İtki (5) + PLA (2); alt satır 6 küçük kart x 2 sütun.


def _gauge_cell(i: int) -> tuple:
    """i. göstergenin (satır, sütun, sütun sayısı) hücresi."""
    if i < 3:
        col, span = ((0, 5), (5, 5), (10, 2))[i]
        return 0, col, span
    return 1, (i - 3) * 2, 2
GAUGE_DISPLAY_LABELS = {key: key for key in GAUGE_KEYS}
# Kısa başlık: "Fp Başlangıç" kartı 142 px asgari genişlik ister, diğerleri 112 px; 6 kart yan yana sığsın diye kısa.
# Tam ad kartın başlığında fare üstüne gelince görünür (SENSOR_LABELS).
GAUGE_DISPLAY_LABELS["FP_start"] = "Fp Başl."
GAUGE_DISPLAY_LABELS["FP_main"] = "Fp Ana"
GAUGE_DISPLAY_LABELS["FT"] = "Ft"
THROTTLE_SEND_MS = 100      # PLA sürgüsü sürüklenirken en fazla 10 Hz komut

ACTUATOR_SHORT = {
    "pompa_start": "Yakıt Pompası Start",
    "pompa_fuel": "Yakıt Pompası Fuel",
    "valf": "Yakıt Debisi Valfi",
    "glow_plug": "Buji Isıtıcı (Glow Plug)",
    "starter": "Başlatma Motoru",
    "start": "Çalıştırma (Start)",
    "throttle": "Gaz Kolu (PLA)",
}
ACTUATOR_ICON = {"pompa_start": "pump", "pompa_fuel": "pump", "valf": "valve",
                 "glow_plug": "glow", "starter": "starter",
                 "start": "power", "throttle": "throttle"}

DASH_QSS = dark_qss("dashBody")

ACT_CMD_W = 112      # Eyleyiciler: KOMUT hücresi genişliği (başlık ve satırlar aynı)
ACT_LOCK_W = 26      # kilit düğmesi
ACT_MAN_W = 68       # Eyleyiciler: MANUEL hücresi genişliği (başlık metni sığsın; kilit ortalanır)


class _ModeChip(QFrame):
    """Yuvarlak uçlu (hap) Motor Modu çipi: zemin modun renginin açık tonu, kenar modun rengi."""

    def __init__(self):
        super().__init__()
        self._col = QColor(theme.DIM)

    def set_color(self, col: str):
        self._col = QColor(col)
        self.update()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        fill = QColor(self._col)
        fill.setAlpha(30)
        p.setPen(QPen(self._col, 1))
        p.setBrush(fill)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)


class _ThrottleSlider(QSlider):
    """Gaz kolu sürgüsü: oluk + yeşil dolgu + tutamaç elle çizilir (QSS oluk/sayfa çizimi sürgü yüksekliğini
    doldurduğu için kullanılmaz)."""

    _HW, _HH, _GH = 26.0, 20.0, 8.0

    # Tutamaç elle çizildiği (QSS'teki 14 px tutamaçla uyuşmadığı) için Qt'nin stil tabanlı isabet denetimi
    # sürüklemeyi başlatmıyordu: fare konumu doğrudan değere çevrilir.
    def _value_at(self, x: float) -> int:
        x0, x1 = self._HW / 2, self.width() - self._HW / 2
        frac = 0.0 if x1 <= x0 else min(1.0, max(0.0, (x - x0) / (x1 - x0)))
        return int(round(self.minimum() + frac * (self.maximum() - self.minimum())))

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton or not self.isEnabled():
            event.ignore()
            return
        self.setSliderDown(True)
        self.sliderPressed.emit()
        self.setValue(self._value_at(event.position().x()))
        event.accept()

    def mouseMoveEvent(self, event):  # noqa: N802
        if not self.isSliderDown():
            event.ignore()
            return
        self.setValue(self._value_at(event.position().x()))
        event.accept()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() != Qt.LeftButton or not self.isSliderDown():
            event.ignore()
            return
        self.setSliderDown(False)
        self.sliderReleased.emit()
        event.accept()

    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on = self.isEnabled()
        span = self.maximum() - self.minimum() or 1
        frac = (self.value() - self.minimum()) / span
        x0, x1 = self._HW / 2, self.width() - self._HW / 2
        cy = self.height() / 2
        x = x0 + (x1 - x0) * frac
        groove = QRectF(x0 - 4, cy - self._GH / 2, (x1 - x0) + 8, self._GH)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#D0DAE3"))
        p.drawRoundedRect(groove, 4, 4)
        fill = QRectF(groove.left(), groove.top(), x - groove.left(), self._GH)
        p.setBrush(QColor(theme.OK if on else theme.LINE_STRONG))
        p.drawRoundedRect(fill, 4, 4)
        hr = QRectF(x - self._HW / 2, cy - self._HH / 2, self._HW, self._HH)
        p.setPen(QPen(QColor(theme.SLATE if on else theme.LINE_STRONG), 1))
        p.setBrush(QColor(theme.SURFACE if on else theme.SURFACE_ALT))
        p.drawRoundedRect(hr, 6, 6)
        p.setPen(QPen(QColor(theme.LINE_MID), 1))                 # tutamaç çizgileri (gaz kolu hissi)
        for dx in (-3, 0, 3):
            p.drawLine(QPointF(x + dx, cy - 5), QPointF(x + dx, cy + 5))


class DashboardTab(QWidget):
    motor_start_requested = Signal()       # Başlat toggle'ı ON  → sinyale 1
    motor_stop_requested = Signal()        # Durdur toggle'ı ON  → sinyale 1
    motor_start_released = Signal()        # Başlat toggle'ı OFF → sinyale 0
    motor_stop_released = Signal()         # Durdur toggle'ı OFF → sinyale 0
    estop_requested = Signal()
    estop_released = Signal()      # kilitli Acil Durdurma 2. basışla açıldı → sistem yeniden başlatılır
    config_saved = Signal(object)        # DashboardConfig
    tick = Signal(list)                  # o an okunması gereken A2L ölçüm adları
    gauge_sample = Signal(str, float)    # gösterge anahtarı, değer (Çalışma Alanı için)
    mappings_requested = Signal()        # "Eşleşmeler" penceresini aç

    def __init__(self, sim_config=None):
        super().__init__()
        self.config = DashboardConfig()
        self._role = Role.OPERATOR
        self._override_confirmed_session = False
        # MainWindow atar: writer(binding, value, label) -> bool
        self.writer = None
        self._dbc = None
        self._a2l_summary = None

        self._values: dict[str, tuple] = {}            # gösterge -> (değer, monotonic)
        self._reasons: dict[str, str] = {}             # gösterge -> değer yoksa neden
        self._faults: dict[str, str] = {}              # gösterge -> arıza nedeni
        self._limits: dict[str, tuple] = {}            # gösterge -> (min, max) (A2L/DBC)
        self._act_open: dict[str, bool] = {k: False for k in ACTUATOR_KEYS}
        self._act_rows: dict[str, dict] = {}
        self._gauge_cards: dict[str, GaugeCard] = {}
        self._measurement_names: list[str] = []
        self._tunable_names: list[str] = []
        self._measurement_units: dict[str, str] = {}
        self._measurement_limits: dict[str, tuple] = {}

        self._build_motor_buttons()

        from app.ui.sim_inputs import SimInputsPanel
        self.sim_inputs = SimInputsPanel(sim_config)

        # Koyu stil YALNIZCA bu iç widget'a uygulanır; QMessageBox/QDialog gibi
        # üst düzey pencereler DashboardTab'ın çocuğu olduğundan etkilenmez.
        body_w = QWidget()
        body_w.setObjectName("dashBody")
        body_w.setStyleSheet(DASH_QSS)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(body_w)
        body = QHBoxLayout(body_w)
        body.setContentsMargins(14, 4, 14, 8)
        body.setSpacing(10)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.role_banner = QLabel("")
        self.role_banner.setObjectName("roleBanner")
        self.role_banner.setWordWrap(True)
        self.role_banner.setVisible(False)
        left.addWidget(self.role_banner, 0)
        left.addWidget(self.sim_inputs, 0)
        # Motor Kontrol: kilitsiz direkt komut (değer + Enter); Eyleyiciler: kilit, rol + onay, değer + _sw
        left.addWidget(self._build_actuators_card("MOTOR KONTROL", "sliders", CONTROL_KEYS), 0)
        left.addWidget(self._build_actuators_card("EYLEYİCİLER", "actuator", EYLEYICI_KEYS), 0)
        # Kalan yükseklik boş bırakılmaz: son olaylar (komut gönderildi / hata) burada görünür
        left.addWidget(self._build_events_card(), 1)
        left_w = QWidget()
        left_w.setLayout(left)
        # Genişlik sabit DEĞİL: alt sınırı içeriğin (yazı tipine göre) asgari genişliği belirler
        # (Uçuş Koşulları etiketleri kırpılmasın); sağ taraf kalan yeri alır.
        left_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)

        right = QVBoxLayout()
        right.setSpacing(10)
        from app.ui.sim_model_panel import SimModelPanel
        self.sim_panel = SimModelPanel()          # yalnızca MIL modunda görünür
        right.addWidget(self.sim_panel, 0)
        right.addWidget(self._build_gauges_card(), 11)
        self.signal_source = "CAN"   # g: sinyallerinin kaynağı (MIL modunda "Simulink MIL"); trend tablosunda gösterilir
        self.trend = TrendPanel()
        self.trend.pick_requested.connect(self._on_pick_graph_signals)
        right.addWidget(self.trend, 10)
        right_w = QWidget()
        right_w.setLayout(right)

        body.addWidget(left_w, 3)             # sol sütun ≈ %30: sensörler (göstergeler) geniş kalır
        body.addWidget(right_w, 7)

        self._rebuild_trend_series()

        self.timer = QTimer(self)
        self.timer.setInterval(TICK_INTERVAL_MS)
        self.timer.timeout.connect(self._on_tick)
        self.timer.start()
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self.refresh_sensor_health)
        self._health_timer.start(1000)

    # ======================================================================
    # Motor komutları (düğmeleri MainWindow üst satıra yerleştirir)
    # ======================================================================
    def _build_motor_buttons(self):
        """Üç komut da toggle: ON → eşlenen sinyale 1, OFF → 0; altında sinyalin o anki değeri (ECU'dan, yoksa
        gönderilen). ``*_button`` adları toggle'ın anahtarıdır (checkable QPushButton): click/isChecked/setEnabled
        eskisi gibi çalışır."""
        self.start_toggle = MotorToggle("Motoru Başlat", on_color=theme.OK)
        self.stop_toggle = MotorToggle("Motoru Durdur", on_color=theme.BLUE)
        self.estop_toggle = MotorToggle("Acil Durdurma", on_color=theme.DANGER)
        self.start_button = self.start_toggle.switch
        self.stop_button = self.stop_toggle.switch
        self.estop_button = self.estop_toggle.switch       # kilitli (ON) / serbest (OFF)
        self._motor_toggles = {"motor_start": self.start_toggle, "motor_stop": self.stop_toggle,
                               "estop": self.estop_toggle}
        self._motor_ecu: dict[str, tuple] = {}              # komut -> (değer, monotonic): ECU'dan okunan
        self._motor_sent: dict[str, float] = {}             # komut -> son gönderilen değer
        self._motor_bind_sig: dict[str, tuple] = {}
        self.start_button.clicked.connect(
            lambda on: (self.motor_start_requested if on else self.motor_start_released).emit())
        self.stop_button.clicked.connect(
            lambda on: (self.motor_stop_requested if on else self.motor_stop_released).emit())
        self.estop_button.clicked.connect(self._on_estop_clicked)
        # Eşleme yokken Acil Durdurma ÇALIŞMAZ; bunu operatör fark etmeli (düğme gri/tıklanamaz bırakılmaz,
        # yanında kalıcı bir uyarı gösterilir).
        self.estop_warn = QPushButton("⚠ Acil Durdurma eşlenmemiş: tanımla")
        self.estop_warn.setObjectName("estopWarn")
        self.estop_warn.setCursor(Qt.PointingHandCursor)
        self.estop_warn.setFlat(True)
        self.estop_warn.clicked.connect(self.open_mappings)
        self.estop_warn.setToolTip("Acil Durdurma için DBC sinyali veya A2L değişkeni tanımlı değil: düğme komut GÖNDEREMEZ. "
                                   "Tıklayın: ⚙ Eşleşmeler > Sinyaller > Motor Komutları > Acil Durdurma satırından "
                                   "CAN ya da A2L seçin. O zamana dek motoru manuel/fiziksel olarak durdurun.")
        self.estop_warn.setVisible(True)

    estop_hint = ""      # "Kısayol: Ctrl+Shift+E" (MainWindow doldurur)

    def update_estop_tooltip(self):
        """Eşleme yoksa uyarı, varsa yalnızca kısayol bilgisi."""
        parts = []
        if not self.config.estop.binding.is_set:
            parts.append("UYARI: Acil Durdurma için eşleme tanımlı DEĞİL; basınca komut gönderilemez. "
                         "⚙ Eşleşmeler penceresinden tanımlayın.")
        if self.estop_hint:
            parts.append(self.estop_hint)
        self.estop_button.setToolTip("\n\n".join(parts))

    def _on_estop_clicked(self, checked: bool = True):
        # 1. basış (checked): ONAY SORULMAZ (acil komutta fazladan tık gecikmedir); Acil Durdurma gönderilir,
        # düğme koyu kırmızıda KİLİTLİ kalır.
        # 2. basış (unchecked): ONAY SORULMAZ; kilit hemen AÇILMAZ, MainWindow sinyali doğrudan 0'a çeker ve
        # ancak başarılıysa ``reset_estop_latch`` ile serbest bırakır (hata: kilitli kalır).
        if checked:
            self.start_button.setEnabled(False)
            self.estop_requested.emit()
        else:
            self.estop_button.blockSignals(True)
            self.estop_button.setChecked(True)
            self.estop_button.blockSignals(False)
            self.estop_released.emit()

    def reset_estop_latch(self):
        """Komut gönderilemediyse düğme kilitli görünmesin."""
        self.estop_button.setChecked(False)
        self.start_button.setEnabled(self.config.motor_start.binding.is_set)

    # ---- toggle durumu ve canlı değer ------------------------------------------------------------------
    def set_motor_toggle(self, key: str, on: bool):
        """Toggle'ı sinyal göndermeden ayarlar (gönderim başarısız olunca eski konuma döndürmek için)."""
        sw = self._motor_toggles[key].switch
        sw.blockSignals(True)
        sw.setChecked(bool(on))
        sw.blockSignals(False)
        sw.update()

    def set_motor_state(self, key: str, value: float, source: str):
        """Komut sinyalinin değeri: ``source`` "ecu" (ECU'dan okundu) ya da "sent" (biz gönderdik)."""
        if key not in self._motor_toggles:
            return
        if source == "ecu":
            self._motor_ecu[key] = (float(value), time.monotonic())
        else:
            self._motor_sent[key] = float(value)
        self._refresh_motor_readout(key)

    def _refresh_motor_readout(self, key: str | None = None):
        now = time.monotonic()
        for k in ([key] if key else list(self._motor_toggles)):
            ecu = self._motor_ecu.get(k)
            if ecu is not None and (now - ecu[1]) <= STALE_S:
                self._motor_toggles[k].set_readout(ecu[0], "ECU")
            elif k in self._motor_sent:
                self._motor_toggles[k].set_readout(self._motor_sent[k], "gönderilen")
            else:
                self._motor_toggles[k].set_readout(None)

    def motor_a2l_names(self) -> list:
        """Değerini ECU'dan okumamız gereken (A2L eşlemeli) komut değişkenleri."""
        out = []
        for k in MOTOR_COMMAND_KEYS:
            b = getattr(self.config, k).binding
            if b.is_set and b.source == SOURCE_A2L and b.a2l_name.strip():
                out.append(b.a2l_name.strip())
        return out

    # ======================================================================
    # Son olaylar (komut gönderildi, hata, bağlantı...): sol sütunun kalan yüksekliğini doldurur
    # ======================================================================
    EVENT_COLORS = {"HATA": theme.DANGER, "MOTOR": theme.OK, "EYLEYICI": theme.ORANGE, "BAGLANTI": theme.ACCENT,
                    "KULLANICI": theme.PURPLE, "SİMÜLASYON": theme.BLUE, "SIMÜLASYON": theme.BLUE, "AYAR": theme.MUTED}
    EVENT_MAX = 60

    def _build_events_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setProperty("accent", "slate")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel("trend", ACCENTS["slate"], 18))
        t = QLabel("SON OLAYLAR")
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        lay.addLayout(head)
        self.events_list = QListWidget()
        self.events_list.setObjectName("eventsList")
        self.events_list.setSelectionMode(QListWidget.NoSelection)
        self.events_list.setFocusPolicy(Qt.NoFocus)
        self.events_list.setFrameShape(QFrame.NoFrame)
        self.events_list.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.events_list.setWordWrap(True)
        self.events_list.setMinimumHeight(60)
        lay.addWidget(self.events_list, 1)
        self.events_empty = QLabel("Henüz olay yok.\nKomutlar (Başlat/Durdur/Acil Durdurma), kilit açma, "
                                   "hatalar ve bağlantı olayları burada görünür.")
        self.events_empty.setObjectName("mutedSmall")
        self.events_empty.setWordWrap(True)
        lay.addWidget(self.events_empty)
        return card

    def add_event(self, entry):
        """Olay günlüğünün yeni bir girişini listenin başına ekler (kategoriye göre renkli)."""
        import time as _t
        text = (f"{_t.strftime('%H:%M:%S', _t.localtime(entry.timestamp))}  "
                f"{entry.category}  ·  {entry.message}")
        item = QListWidgetItem(text)
        item.setForeground(QColor(self.EVENT_COLORS.get(entry.category, theme.MUTED)))
        item.setToolTip(f"{entry.user} / {entry.role}\n{entry.message}")
        self.events_empty.setVisible(False)
        self.events_list.insertItem(0, item)
        while self.events_list.count() > self.EVENT_MAX:
            self.events_list.takeItem(self.events_list.count() - 1)

    # ======================================================================
    # Motor Parametreleri (9 gösterge) + sensör sağlığı
    # ======================================================================
    def _build_gauges_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        card.setProperty("accent", "teal")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel("gauge", ACCENTS["teal"], 18))
        t = QLabel("MOTOR PARAMETRELERİ")
        t.setObjectName("cardTitle")
        t.setMinimumWidth(t.fontMetrics().horizontalAdvance("MOTOR PARAMETRELERİ") + 30)   # başlık kırpılmasın
        head.addWidget(t)
        head.addSpacing(10)
        cap = QLabel("Sensör sağlığı")
        cap.setObjectName("mutedSmall")
        head.addWidget(cap)
        self._health_box = QHBoxLayout()
        self._health_box.setSpacing(6)
        head.addLayout(self._health_box)
        self._health_labels: list = []
        head.addSpacing(6)
        self._build_mode_chip(head)
        head.addStretch(1)
        self.map_warn_label = QLabel("")
        self.map_warn_label.setObjectName("warnSmall")
        head.addWidget(self.map_warn_label)
        self.map_warn_button = QPushButton("Eşleşmeleri yapılandır")
        self.map_warn_button.setObjectName("linkWarn")
        self.map_warn_button.setCursor(Qt.PointingHandCursor)
        self.map_warn_button.setVisible(False)
        self.map_warn_button.clicked.connect(self.open_mappings)
        head.addWidget(self.map_warn_button)
        lay.addLayout(head)
        lay.addLayout(self._build_sub_modes())

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, key in enumerate(GAUGE_KEYS):
            lo, hi, unit, red = GAUGE_RANGES[key]
            variant = "big" if key in ("RPM", "İtki") else "ring" if key == "PLA" else "small"
            gc = GaugeCard(key, GAUGE_DISPLAY_LABELS.get(key, key), lo, hi, unit,
                           red_limit=red, limit_text=GAUGE_LIMIT_TEXT.get(key, "LİMİT"), variant=variant)
            gc.lock.setVisible(False)       # sensörlerde manuel değer / switch yok: yalnızca Eyleyicilerde
            gc.title.setToolTip(SENSOR_LABELS.get(key, key))
            self._gauge_cards[key] = gc
            row, col, span = _gauge_cell(i)
            grid.addWidget(gc, row, col, 1, span)
        for c in range(12):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(0, 3)
        grid.setRowStretch(1, 2)
        lay.addLayout(grid, 1)
        self.refresh_sensor_health()
        return card

    def _build_mode_chip(self, head):
        """Başlıkta "Motor Modu: AD" çipi (yalnız mod adı; sayı gösterilmez)."""
        self.mode_chip = _ModeChip()
        hl = QHBoxLayout(self.mode_chip)
        hl.setContentsMargins(11, 3, 15, 3)
        hl.setSpacing(8)
        self.mode_dot = QLabel()
        self.mode_dot.setFixedSize(10, 10)
        cap = QLabel("Motor Modu:")
        cap.setObjectName("mutedSmall")
        self.mode_name = QLabel("—")
        self.mode_name.setObjectName("modeName")
        hl.addWidget(self.mode_dot)
        hl.addWidget(cap)
        hl.addWidget(self.mode_name)
        head.addWidget(self.mode_chip)
        self._mode: tuple | None = None            # (değer, monotonic)
        self._paint_mode(None)

    def _build_sub_modes(self) -> QHBoxLayout:
        """Gösterge gridinin üstünde ince şerit: STARTER · START · RUN · STOP alt mod çipleri."""
        row = QHBoxLayout()
        row.setSpacing(8)
        cap = QLabel("ALT MODLAR")
        cap.setObjectName("mutedSmall")
        row.addWidget(cap)
        self._sub_chips: dict = {}
        self._sub: dict[str, tuple] = {}            # anahtar -> (değer, monotonic)
        self._sub_shown: dict = {}
        for key in SUB_MODE_KEYS:
            chip = _ModeChip()
            hl = QHBoxLayout(chip)
            hl.setContentsMargins(10, 2, 14, 2)
            hl.setSpacing(7)
            dot = QLabel()
            dot.setFixedSize(8, 8)
            title = QLabel(SUB_MODE_TITLES[key])
            title.setObjectName("mutedSmall")
            name = QLabel("—")
            hl.addWidget(dot)
            hl.addWidget(title)
            hl.addWidget(name)
            row.addWidget(chip)
            self._sub_chips[key] = (chip, dot, name)
            self._paint_sub(key, None, True)
        row.addStretch(1)
        return row

    def _paint_sub(self, key: str, value, active: bool):
        chip, dot, name = self._sub_chips[key]
        text = mode_name(key, value) if value is not None else "—"
        if text == "—":
            col = theme.DIM
        elif text.startswith("BİLİNMİYOR"):
            col = theme.WARN
        else:
            col = SUB_MODE_COLORS.get(text, theme.ACCENT)
        if not active:
            col = theme.DIM                            # ana moda uymayan alt mod: sönük
        name.setText(text)
        chip.set_color(col)
        dot.setStyleSheet(f"background: {col}; border-radius: 4px; border: none;")
        name.setStyleSheet(f"font-size: 13px; font-weight: {800 if active else 600}; letter-spacing: 1px; "
                           f"color: {theme.HEAD if active else theme.MUTED}; background: transparent; border: none;")

    def set_sub_mode(self, key: str, value):
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self._sub[key] = (value, time.monotonic())
        else:
            self._sub.pop(key, None)
        self._refresh_sub_modes()

    def _refresh_sub_modes(self):
        now = time.monotonic()
        m = self._mode
        main = int(m[0]) if m is not None and (now - m[1]) <= STALE_S and float(m[0]) == int(m[0]) else None
        active_keys = ACTIVE_SUB_MODES.get(main) if main is not None else None
        for key in SUB_MODE_KEYS:
            s = self._sub.get(key)
            shown = s[0] if s is not None and (now - s[1]) <= STALE_S else None
            active = active_keys is None or key in active_keys
            if (shown, active) != self._sub_shown.get(key, object()):
                self._sub_shown[key] = (shown, active)
                self._paint_sub(key, shown, active)

    def _paint_mode(self, value):
        """value None/bayat: gri "—"; aksi halde modun adı ve rengi."""
        name = motor_mode_name(value) if value is not None else "—"
        col = MODE_COLORS.get(int(value), theme.WARN) if value is not None and name != "—" else theme.DIM
        self.mode_name.setText(name)
        self.mode_chip.set_color(col)
        self.mode_dot.setStyleSheet(f"background: {col}; border-radius: 5px; border: none;")
        self.mode_name.setStyleSheet(f"font-size: 15px; font-weight: 800; letter-spacing: 1px; color: {theme.HEAD};"
                                     " background: transparent; border: none;")

    def set_motor_mode(self, value):
        """motor_mode sayısı (0-6) gelince çipi günceller; sayı olmayan değer çipi "—" yapar."""
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            self._mode = (value, time.monotonic())
        else:
            self._mode = None
        self._refresh_mode()

    def _refresh_mode(self):
        m = self._mode
        fresh = m is not None and (time.monotonic() - m[1]) <= STALE_S
        shown = m[0] if fresh else None
        if shown != getattr(self, "_mode_shown", object()):
            self._mode_shown = shown
            self._paint_mode(shown)
        self._refresh_sub_modes()

    @property
    def motor_mode_text(self) -> str:
        return self.mode_name.text()

    def refresh_sensor_health(self):
        """Arızalı sensörleri (neden ile birlikte) başlık şeridinde listeler."""
        for w in self._health_labels:
            self._health_box.removeWidget(w)
            w.deleteLater()
        self._health_labels = []
        faults = dict(self._faults)
        if not faults:
            # "Arıza yok" ancak gerçekten taze veri varken söylenir; veri yoksa bilinmiyor.
            now = time.monotonic()
            has_data = any((now - v[1]) <= STALE_S for v in self._values.values())
            w = QLabel("Arıza yok" if has_data else "Sensör verisi yok")
            w.setObjectName("chipGreen" if has_data else "chipMuted")
            if not has_data:
                w.setToolTip("Henüz sensör verisi gelmedi; arıza durumu bilinmiyor.")
            self._health_box.addWidget(w)
            self._health_labels.append(w)
        else:
            w = QLabel(f"{len(faults)} arıza")
            w.setObjectName("chipBad")
            self._health_box.addWidget(w)
            self._health_labels.append(w)
            items = list(faults.items())
            for key, reason in items[:3]:
                c = QLabel(f"{GAUGE_DISPLAY_LABELS.get(key, key)} · {reason}")
                c.setObjectName("chipBad")
                c.setToolTip("\n".join(f"{GAUGE_DISPLAY_LABELS.get(k, k)}: {r}" for k, r in items))
                self._health_box.addWidget(c)
                self._health_labels.append(c)
            if len(items) > 3:
                more = QLabel(f"+{len(items) - 3}")
                more.setObjectName("chipBad")
                more.setToolTip("\n".join(f"{GAUGE_DISPLAY_LABELS.get(k, k)}: {r}" for k, r in items))
                self._health_box.addWidget(more)
                self._health_labels.append(more)
        for key, gc in self._gauge_cards.items():
            if key in self._faults:
                gc.set_tag("ARIZA", "fault")
            else:
                gc.set_tag("")
        self._refresh_gauge_states()

    def _refresh_gauge_states(self):
        self._refresh_mode()
        now = time.monotonic()
        unbound = set(self.config.unbound_gauges())
        for key, gc in self._gauge_cards.items():
            val = self._values.get(key)
            fresh = val is not None and (now - val[1]) <= STALE_S
            if fresh:
                gc.set_value(val[0])
                gc.set_status("")
            else:
                gc.set_value(None if val is None else val[0], dim=val is not None)
                if key in unbound:
                    # hepsi eşlenmemişse başlıktaki tek uyarı yeterli (8 kez tekrarlanmaz)
                    gc.set_status("" if len(unbound) == len(self._gauge_cards) else "Eşleşme yok")
                elif val is not None:
                    gc.set_status(f"Veri yok ({STALE_S:.0f} sn)")
                else:
                    gc.set_status(self._reasons.get(key, "Veri bekleniyor"))

    def set_gauge_value(self, key: str, value):
        if key == MODE_KEY:                       # gösterge değil: başlıktaki Motor Modu çipi
            self.set_motor_mode(value)
            return
        if key in SUB_MODE_KEYS:                  # alt mod çipleri
            self.set_sub_mode(key, value)
            return
        if isinstance(value, (int, float)):
            self._values[key] = (float(value), time.monotonic())
            self._reasons.pop(key, None)
            gc = self._gauge_cards.get(key)
            if gc is not None:
                gc.set_value(value)
                gc.set_status("")
            self.trend.append(f"g:{key}", value)
            self.gauge_sample.emit(key, float(value))
            self._check_limits(key, float(value))
        else:
            self._values.pop(key, None)
            gc = self._gauge_cards.get(key)
            if gc is not None:
                gc.set_value(None)

    def set_gauge_debug(self, key: str, text: str):
        gc = self._gauge_cards.get(key)
        if gc is not None:
            gc.set_debug(text)

    def set_gauge_error(self, key: str, reason: str):
        """Değer okunamıyorsa NEDENİNİ göstergenin altında gösterir."""
        self._reasons[key] = reason
        if key not in self._values:
            gc = self._gauge_cards.get(key)
            if gc is not None:
                gc.set_status(reason)

    def set_sensor_fault(self, key: str, reason: str | None):
        """Arıza bitinden/limit aşımından gelen arıza durumunu bildirir."""
        changed = (key in self._faults) != bool(reason) or self._faults.get(key) != reason
        if reason:
            self._faults[key] = reason
        else:
            self._faults.pop(key, None)
        if changed:
            self.refresh_sensor_health()

    def _check_limits(self, key: str, value: float):
        lim = self._limits.get(key)
        if lim is None or self.config.sensor_map(key).fault.is_set:
            return
        lo, hi = lim
        if value < lo or value > hi:
            self.set_sensor_fault(key, "Aralık dışı")
        elif self._faults.get(key) == "Aralık dışı":
            self.set_sensor_fault(key, None)

    def set_gauge_limits(self, key: str, lo: float | None, hi: float | None):
        if lo is None or hi is None or hi <= lo:
            self._limits.pop(key, None)
        else:
            self._limits[key] = (lo, hi)

    # ======================================================================
    # Eyleyiciler
    # ======================================================================
    def _build_actuators_card(self, title: str = "EYLEYİCİLER", icon: str = "actuator",
                              keys=EYLEYICI_KEYS) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        accent = "green" if keys is CONTROL_KEYS else "orange"
        card.setProperty("accent", accent)
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 8)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel(icon, ACCENTS[accent], 18))
        t = QLabel(title)
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        lay.addLayout(head)

        # Başlıklar satırlarla AYNI sütun genişliklerini ve aralığı kullanır (hizalı)
        cols = QHBoxLayout()
        cols.setContentsMargins(0, 4, 0, 2)
        cols.setSpacing(10)
        spacer = QWidget()
        spacer.setFixedWidth(18)                      # simge sütunu
        cols.addWidget(spacer)
        c0 = QLabel("GİRİŞ" if keys is CONTROL_KEYS else "EYLEYİCİ")
        c0.setObjectName("colHead")
        cols.addWidget(c0, 1)
        self.act_head_cmd = QLabel("KOMUT")
        self.act_head_cmd.setObjectName("colHead")
        self.act_head_cmd.setFixedWidth(ACT_CMD_W)
        self.act_head_cmd.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        cols.addWidget(self.act_head_cmd)
        if keys is not CONTROL_KEYS:                      # Motor Kontrol'de kilit/manuel sütunu yok: direkt komut
            c2 = QLabel("MANUEL")
            c2.setObjectName("colHead")
            c2.setFixedWidth(ACT_MAN_W)
            c2.setAlignment(Qt.AlignCenter)
            cols.addWidget(c2)
        lay.addLayout(cols)

        for key in keys:
            lay.addWidget(self._build_actuator_row(key), 1)
        lay.addStretch(1)       # artan yükseklik başlıkla satırlar arasına DEĞİL, kartın altına gider
        return card

    def _build_actuator_row(self, key: str) -> QFrame:
        kind = ACTUATOR_KINDS[key]          # "valve": değer kutusu (ON/OFF anahtarı yok)
        row = QFrame()
        row.setObjectName("rowFrame")
        row.setMinimumHeight(36)
        row.setMaximumHeight(52)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(10)
        icon = IconLabel(ACTUATOR_ICON[key], DK_CYAN, 18)
        name = QLabel(ACTUATOR_SHORT[key])
        name.setObjectName("rowName")
        hl.addWidget(icon)
        hl.addWidget(name, 1)
        entry = {"kind": kind, "name": name, "icon": icon}
        cell = QWidget()                                # KOMUT hücresi: sabit genişlik, sağa dayalı
        cell.setFixedWidth(ACT_CMD_W)
        cl = QHBoxLayout(cell)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(8)
        cl.addStretch(1)
        # Serbest değer kutusu: boş başlar, aralık/birim sınırı yok; Enter ile gönderilir.
        box = QLineEdit()
        box.setObjectName("actValue")
        box.setPlaceholderText("değer")
        box.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        box.setFixedWidth(ACT_CMD_W)
        # yalnızca sayı: isteğe bağlı eksi, ondalık ayırıcı nokta VEYA virgül (okurken noktaya çevrilir)
        box.setValidator(QRegularExpressionValidator(QRegularExpression(r"^-?\d*[.,]?\d*$"), box))
        box.returnPressed.connect(lambda k=key: self._on_actuator_submit(k))
        box.textEdited.connect(lambda _t, b=box: self._mark_actuator_box(b, False))
        cl.addWidget(box)
        entry.update(control=box)
        hl.addWidget(cell)
        if key in CONTROL_KEYS:
            # Motor Kontrol: kilit YOK. Değer yazılıp Enter'a basılınca komut doğrudan gönderilir.
            entry["lock"] = None
            box.setToolTip("Değeri yazıp Enter'a basın: komut doğrudan gönderilir")
        else:
            lock = LockButton(ACT_LOCK_W)
            lock.lock_requested.connect(lambda want, k=key: self._on_actuator_lock(k, want))
            mcell = QWidget()                            # MANUEL hücresi: kilit ortada
            mcell.setFixedWidth(ACT_MAN_W)
            ml = QHBoxLayout(mcell)
            ml.setContentsMargins(0, 0, 0, 0)
            ml.addWidget(lock, 0, Qt.AlignCenter)
            hl.addWidget(mcell)
            entry["lock"] = lock
            entry["control"].setEnabled(False)
        self._act_rows[key] = entry
        self._style_actuator_row(key)
        if key == "throttle":
            return self._wrap_throttle_slider(row, box)
        return row

    # ---- Gaz kolu (PLA) sürgüsü: değer kutusunun altında, kutuyla çift yönlü --------------------------
    def _wrap_throttle_slider(self, row: QFrame, box: QLineEdit) -> QFrame:
        row.setObjectName("")                              # alt çizgiyi kap çizer
        row.setMaximumHeight(52)
        wrap = QFrame()
        wrap.setObjectName("rowFrame")
        v = QVBoxLayout(wrap)
        v.setContentsMargins(0, 0, 0, 4)
        v.setSpacing(0)
        v.addWidget(row)
        line = QHBoxLayout()
        line.setContentsMargins(28, 0, 0, 0)
        line.setSpacing(10)
        self.throttle_slider = _ThrottleSlider(Qt.Horizontal)
        self.throttle_slider.setObjectName("throttleSlider")
        self.throttle_slider.setRange(0, 100)
        self.throttle_slider.setSingleStep(1)
        self.throttle_slider.setPageStep(5)
        self.throttle_slider.setMinimumHeight(26)
        self.throttle_slider.setCursor(Qt.PointingHandCursor)
        self.throttle_pct = QLabel("0 %")
        self.throttle_pct.setObjectName("rowName")
        self.throttle_pct.setFixedWidth(46)
        self.throttle_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        line.addWidget(self.throttle_slider, 1)
        line.addWidget(self.throttle_pct)
        v.addLayout(line)
        self._throttle_dragging = False
        self._throttle_failed = False
        self._throttle_timer = QTimer(self)                # sürüklerken en fazla 10 Hz komut
        self._throttle_timer.setSingleShot(True)
        self._throttle_timer.setInterval(THROTTLE_SEND_MS)
        self._throttle_timer.timeout.connect(self._on_throttle_tick)
        self._throttle_pending = False
        self.throttle_slider.valueChanged.connect(self._on_throttle_slider)
        self.throttle_slider.sliderPressed.connect(self._on_throttle_pressed)
        self.throttle_slider.sliderReleased.connect(self._on_throttle_released)
        box.textEdited.connect(self._on_throttle_text)
        self._update_throttle_slider()
        return wrap

    def _update_throttle_slider(self):
        """Sürgü yalnız yetkili rolde ve PLA eşleşmesi varken etkindir (sürüklerken diyalog çıkmaması için)."""
        sl = getattr(self, "throttle_slider", None)
        if sl is None:
            return
        allowed = can_override_actuator(self._role)
        mapped = self.config.actuator_map("throttle").value.is_set
        sl.setEnabled(allowed and mapped)
        sl.setToolTip("" if allowed and mapped else
                      "Gaz kolu için Mühendis/Yönetici rolü ve ⚙ Eşleşmeler'de PLA değer eşleşmesi gerekir."
                      if not mapped or not allowed else "")

    def _on_throttle_text(self, _t: str = ""):
        """Kutuya elle yazılan değer sürgüyü taşır (komut Enter ile gider)."""
        v = self._actuator_text_value("throttle")
        if v is None:
            return
        self.throttle_slider.blockSignals(True)
        self.throttle_slider.setValue(int(max(0, min(100, round(v)))))
        self.throttle_slider.blockSignals(False)
        self.throttle_pct.setText(f"{int(max(0, min(100, round(v))))} %")

    def _on_throttle_slider(self, value: int):
        box = self._act_rows["throttle"]["control"]
        box.setText(str(value))
        self._mark_actuator_box(box, False)
        self.throttle_pct.setText(f"{value} %")
        self._queue_throttle()                             # sürükleme / ok tuşu / tekerlek

    def _on_throttle_pressed(self):
        self._throttle_dragging = True
        self._throttle_failed = False

    def _on_throttle_released(self):
        self._throttle_dragging = False
        self._throttle_timer.stop()
        self._throttle_pending = False
        self._send_throttle(force=True)                    # bırakınca SON değer kesin gider

    def _queue_throttle(self):
        if self._throttle_timer.isActive():
            self._throttle_pending = True
            return
        self._send_throttle()
        self._throttle_timer.start()

    def _on_throttle_tick(self):
        if self._throttle_pending:                         # aralıkta biriken son değer
            self._throttle_pending = False
            self._send_throttle()
            self._throttle_timer.start()

    def _send_throttle(self, force: bool = False):
        if self._throttle_failed and not force:
            return                                         # hata: sürükleme boyunca tekrar deneyip diyalog yağdırma
        if not self.throttle_slider.isEnabled():
            return
        box = self._act_rows["throttle"]["control"]
        v = self._actuator_text_value("throttle")
        if v is None:
            return
        ok = self._write(self.config.actuator_map("throttle").value, v, f"{ACTUATOR_SHORT['throttle']} komutu")
        self._throttle_failed = not ok
        self._mark_actuator_box(box, not ok)

    def _style_actuator_row(self, key: str):
        e = self._act_rows[key]
        opened = self._act_open[key] or key in CONTROL_KEYS      # Motor Kontrol her zaman etkin (kilitsiz)
        e["name"].setEnabled(opened)
        e["icon"].setEnabled(opened)
        e["control"].setEnabled(opened)
        e["name"].setStyleSheet("" if opened else theme.paint("color:@@SLATE@@;"))

    def set_role(self, role: Role):
        self._role = role
        self._update_throttle_slider()
        locked = not can_override_actuator(role)
        self.role_banner.setVisible(locked)
        if locked:
            self.role_banner.setText(
                f"🔒 {role.value} rolü: girişler, motor komutları ve manuel (kilit) kontrolleri kapalı. "
                "Açmak için Mühendis veya Yönetici rolü gerekir.")

    def _confirm_override(self, label: str) -> bool:
        if not can_override_actuator(self._role):
            QMessageBox.warning(
                self, "Yetki yok",
                f"{label} için manuel değeri açmak için Mühendis veya Yönetici rolü gerekir "
                "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
            return False
        if not self._override_confirmed_session:
            confirm = QMessageBox.warning(
                self, "MANUEL DEĞER — devam edilsin mi?",
                "Bu kontrol, GERÇEK donanımı (veya MATLAB/Simulink anahtar bloğunu) doğrudan sürer. "
                "Yalnızca motor ÇALIŞMIYORKEN, bileşen/HIL testi amacıyla kullanılmalıdır.\n\n"
                "Yanlış bir değer gönderimi donanıma zarar verebilir. Gerçekten devam etmek "
                "istediğinizden emin misiniz?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if confirm != QMessageBox.Yes:
                return False
            self._override_confirmed_session = True
        return True

    def _write(self, binding: Binding, value: float, label: str) -> bool:
        if self.writer is None:
            return False
        return bool(self.writer(binding, float(value), label))

    def _actuator_text_value(self, key: str):
        """Eyleyici kutusundaki sayı; kutu boş/geçersizse None."""
        text = self._act_rows[key]["control"].text().strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    @staticmethod
    def _mark_actuator_box(box, bad: bool):
        box.setProperty("bad", bad)
        box.style().unpolish(box)
        box.style().polish(box)

    def _on_actuator_submit(self, key: str):
        """Enter: Eyleyicilerde kilit AÇIKSA, Motor Kontrol'de her zaman (rol yeterliyse) kutudaki sayıyı yazar."""
        direct = key in CONTROL_KEYS
        if not direct and not self._act_open[key]:
            return
        v = self._actuator_text_value(key)
        if v is None:
            return
        box = self._act_rows[key]["control"]
        if direct:
            label = ACTUATOR_SHORT[key]
            if not can_override_actuator(self._role):
                QMessageBox.warning(
                    self, "Yetki yok",
                    f"{label} komutu için Mühendis veya Yönetici rolü gerekir "
                    "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
                return
            if not self.config.actuator_map(key).value.is_set:
                QMessageBox.information(
                    self, "Eşleşme yok",
                    f"{label} için değer eşleşmesi tanımlı değil.\n⚙ Eşleşmeler penceresinden tanımlayın.")
                return
        ok = self._write(self.config.actuator_map(key).value, v, f"{ACTUATOR_SHORT[key]} komutu")
        self._mark_actuator_box(box, not ok)

    def _on_actuator_lock(self, key: str, want_open: bool):
        amap = self.config.actuator_map(key)
        label = ACTUATOR_SHORT[key]
        e = self._act_rows[key]
        # Kilit YALNIZCA Eyleyicilerde vardır (Motor Kontrol direkt komuttur); anahtar (_sw) zorunludur.
        if key not in EYLEYICI_KEYS:
            return
        if want_open:
            if not amap.value.is_set or not amap.sw.is_set:
                QMessageBox.information(
                    self, "Eşleşme yok",
                    f"{label} için değer ve anahtar (_sw) eşleşmesi tanımlı değil.\n"
                    "⚙ Eşleşmeler penceresinden tanımlayın.")
                return
            if not self._confirm_override(label):
                return
            # kutuda değer varsa önce değer, sonra anahtar (ECU anahtar açılınca bilinen değeri görür);
            # kutu boşsa yalnızca anahtar (_sw = 1) yazılır
            v = self._actuator_text_value(key)
            if v is not None and not self._write(amap.value, v, f"{label} değeri"):
                return
            if not self._write(amap.sw, 1.0, f"{label} anahtarı"):
                return
            self._act_open[key] = True
            e["lock"].set_open(True)
        else:
            if not self._release_actuator(key, amap, label):
                return
            self._act_open[key] = False
            e["lock"].set_open(False)
        self._style_actuator_row(key)

    def _release_actuator(self, key: str, amap, label: str) -> bool:
        """Kilitlerken: Eyleyicilerde _sw = 0 (anahtar yoksa DEĞER 0'a çekilir). Yazılamazsa False."""
        if amap.sw.is_set:
            return self._write(amap.sw, 0.0, f"{label} anahtarı")
        if not amap.value.is_set:
            return True
        return self._write(amap.value, 0.0, f"{label} değeri (bırakılıyor)")

    def release_all_actuators(self, write: bool = True) -> list:
        """Bağlantı kapanırken: kilidi AÇIK her eyleyicinin anahtarını (_sw) kapatmayı dener
        (write=True), sonra arayüzü kilitli/bilinmiyor duruma çeker ve yeni açma için onayı
        yeniden ister. Döner: ECU'da kapatıldığı DOĞRULANAMAYAN eyleyicilerin adları."""
        unconfirmed = []
        for key in ACTUATOR_KEYS:
            if not self._act_open.get(key):
                continue
            label = ACTUATOR_SHORT[key]
            closed = False
            if write and self.writer is not None:
                try:
                    closed = self._release_actuator(key, self.config.actuator_map(key), label)
                except Exception:  # noqa: BLE001
                    closed = False
            if not closed:
                unconfirmed.append(label)
            self._act_open[key] = False
            e = self._act_rows[key]
            e["lock"].set_open(False)
            self._style_actuator_row(key)
            self.set_actuator_feedback(key, "Bilinmiyor (bağlantı kapandı)" if not closed else "Kapalı")
        self._override_confirmed_session = False
        return unconfirmed

    def set_actuator_feedback(self, key: str, text: str):
        e = self._act_rows.get(key)
        if e is not None:
            e["name"].setToolTip(text)

    # ======================================================================
    # Canlı Trendler: sinyal seçimi ve besleme
    # ======================================================================
    def set_measurements(self, measurements):
        """Yüklü A2L'deki ölçümleri (MeasurementInfo listesi) bildirir."""
        self._measurement_names = [m.name for m in measurements if not hasattr(m, "char_type")]
        self._tunable_names = [m.name for m in measurements if hasattr(m, "char_type")]
        self._measurement_units = {m.name: (m.unit or "") for m in measurements}
        self._measurement_limits = {
            m.name: (m.minimum, m.maximum) for m in measurements
            if m.minimum is not None and m.maximum is not None and m.maximum > m.minimum
        }
        self._rebuild_trend_series()

    def graph_measurement_names(self) -> list:
        return [sid[2:] for sid in self.config.graph_signals if sid.startswith("m:")]

    def _on_pick_graph_signals(self):
        from app.ui.graph_signal_dialog import GraphSignalDialog
        dlg = GraphSignalDialog(GAUGE_KEYS, self._measurement_names, self.config.graph_signals, self,
                                tunable_names=self._tunable_names)
        if dlg.exec() != GraphSignalDialog.Accepted:
            return
        self.set_graph_signals(dlg.selected_ids(), persist=True)

    def set_graph_signals(self, ids: list, persist: bool = False):
        self.config.graph_signals = list(ids)
        self._rebuild_trend_series()
        if persist:
            self.config_saved.emit(self.config)

    def set_signal_source(self, source: str):
        """Gösterge/trend sinyallerinin kaynak etiketi (PCAN, Simulink MIL, Sanal...)."""
        if source != self.signal_source:
            self.signal_source = source
            self._trend_sig = None
            self._rebuild_trend_series()

    def _rebuild_trend_series(self):
        from app.ui.graph_signal_dialog import signal_label
        specs = []
        for sid in self.config.graph_signals:
            if sid.startswith("g:"):
                k = sid[2:]
                unit = GAUGE_RANGES[k][2] if k in GAUGE_RANGES else ""
                specs.append({"key": sid, "label": GAUGE_DISPLAY_LABELS.get(k, k), "unit": unit,
                              "source": self.signal_source})
            elif sid.startswith("m:"):
                specs.append({"key": sid, "label": signal_label(sid), "unit": self._measurement_units.get(sid[2:], ""),
                              "source": "CCP (A2L)"})
        sig = [(s["key"], s["label"], s["unit"], s["source"]) for s in specs]
        if sig == getattr(self, "_trend_sig", None):
            return          # değişmediyse eksenleri/ViewBox'ları yeniden kurma (Kaydet sonrası sağ taraf bozuluyordu)
        self._trend_sig = sig
        self.trend.set_series(specs)

    def add_measurement_sample(self, name: str, value: float):
        self.trend.append(f"m:{name}", value)

    # ======================================================================
    # Kaynaklar, yapılandırma, periyodik tetikleme
    # ======================================================================
    def set_sources(self, dbc, a2l_summary):
        self._dbc = dbc
        self._a2l_summary = a2l_summary

    def set_config(self, cfg: DashboardConfig):
        self.config = cfg
        self._update_throttle_slider()
        self._rebuild_trend_series()
        miss = cfg.unbound_gauges()
        self.map_warn_label.setText(f"⚠ {len(miss)} sensör bağlı değil" if miss else "")
        self.map_warn_button.setVisible(bool(miss))
        self.start_button.setEnabled(cfg.motor_start.binding.is_set and not self.estop_button.isChecked())
        self.stop_button.setEnabled(cfg.motor_stop.binding.is_set)
        # Acil Durdurma HER ZAMAN tıklanabilir kalır: eşleme yoksa basınca açık bir hata verir (gri/sessiz değil).
        self.estop_button.setEnabled(True)
        self.estop_warn.setVisible(not cfg.estop.binding.is_set)
        for btn, cmd, label in ((self.start_button, cfg.motor_start, "Motoru Başlat"),
                                 (self.stop_button, cfg.motor_stop, "Motoru Durdur")):
            btn.setToolTip("" if btn.isEnabled() else f"{label} için ⚙ Eşleşmeler penceresinden DBC sinyali veya A2L değişkeni seçin.")
        self.update_estop_tooltip()
        for k in MOTOR_COMMAND_KEYS:                 # eşleme değiştiyse eski değer yanlış sinyale ait kalmasın
            b = getattr(cfg, k).binding
            sig = (b.source, b.message, b.signal, b.a2l_name)
            if self._motor_bind_sig.get(k, sig) != sig:
                self._motor_ecu.pop(k, None)
                self._motor_sent.pop(k, None)
            self._motor_bind_sig[k] = sig
        self._refresh_motor_readout()
        for key in GAUGE_KEYS:
            if key not in cfg.gauge_a2l_map() and key not in cfg.gauge_can_map():
                self._values.pop(key, None)
        if MODE_KEY not in cfg.gauge_a2l_map() and MODE_KEY not in cfg.gauge_can_map():
            self._mode = None
        for key in SUB_MODE_KEYS:
            if key not in cfg.gauge_a2l_map() and key not in cfg.gauge_can_map():
                self._sub.pop(key, None)
        self._refresh_gauge_states()

    def open_mappings(self):
        from app.ui.mapping_dialog import MappingDialog
        dlg = MappingDialog(self.config, self.sim_inputs, self._dbc, self._a2l_summary, self)
        if dlg.exec() == MappingDialog.Accepted:
            cfg = dlg.result_config()
            self.set_config(cfg)
            self.config_saved.emit(cfg)
            self.mappings_requested.emit()

    def _on_tick(self):
        names = list(dict.fromkeys(list(self.config.gauge_a2l_map().values())
                                   + [self.config.sensor_map(k).fault.a2l_name.strip()
                                      for k in GAUGE_KEYS
                                      if self.config.sensor_map(k).fault.source == "a2l"
                                      and self.config.sensor_map(k).fault.a2l_name.strip()]
                                   + self.graph_measurement_names()
                                   + self.motor_a2l_names()))
        self._refresh_gauge_states()
        self._refresh_motor_readout()
        if names:
            self.tick.emit(names)
