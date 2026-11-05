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

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMessageBox, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)
from PySide6.QtWidgets import QDoubleSpinBox

from app.dashboard_config import (
    ACTUATOR_KEYS, ACTUATOR_KINDS, ACTUATOR_LABELS, GAUGE_KEYS, Binding, DashboardConfig,
)
from app.ui.dash_widgets import (  # noqa: F401  (GaugeWidget/ToggleSwitch: eski import yolları)
    DK_CYAN, DK_MUT, DashGauge, GaugeCard, GaugeWidget, IconLabel, LockButton, ToggleSwitch,
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
    "RPM": (0.0, 6000.0, "rpm"),
    "İtki": (0.0, 100.0, "%"),
    "PLA": (0.0, 100.0, "%"),
    "Tt5": (0.0, 800.0, "°C"),
    "FP": (0.0, 10.0, "bar"),
    "FT": (0.0, 500.0, "°C"),
    "Ps2": (0.0, 5.0, "bar"),
    "Tt2": (0.0, 120.0, "°C"),
}
GAUGE_DISPLAY_LABELS = {key: key for key in GAUGE_KEYS}
GAUGE_DISPLAY_LABELS["FP"] = "Fp"
GAUGE_DISPLAY_LABELS["FT"] = "Ft"

ACTUATOR_SHORT = {
    "pompa_start": "Yakıt Pompası Start",
    "pompa_fuel": "Yakıt Pompası Fuel",
    "valf": "Yakıt Debisi Valfi",
    "glow_plug": "Buji Isıtıcı (Glow Plug)",
    "starter": "Başlatma Motoru",
}
ACTUATOR_ICON = {"pompa_start": "pump", "pompa_fuel": "pump", "valf": "valve",
                 "glow_plug": "glow", "starter": "starter"}

DASH_QSS = dark_qss("dashBody")


class DashboardTab(QWidget):
    motor_start_requested = Signal()
    motor_stop_requested = Signal()
    estop_requested = Signal()
    config_saved = Signal(object)        # DashboardConfig
    tick = Signal(list)                  # o an okunması gereken A2L ölçüm adları
    open_graph_requested = Signal()
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
        self._sensor_open: dict[str, bool] = {k: False for k in GAUGE_KEYS}
        self._sensor_manual: dict[str, float] = {}
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
        left.addWidget(self.sim_inputs, 0)
        left.addWidget(self._build_actuators_card(), 1)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(512)
        left_w.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        right = QVBoxLayout()
        right.setSpacing(10)
        right.addWidget(self._build_gauges_card(), 11)
        self.trend = TrendPanel()
        self.trend.pick_requested.connect(self._on_pick_graph_signals)
        right.addWidget(self.trend, 10)
        right_w = QWidget()
        right_w.setLayout(right)

        body.addWidget(left_w, 0)
        body.addWidget(right_w, 1)

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
        self.start_button = QPushButton("Motoru Başlat")
        self.start_button.setProperty("primary", True)
        self.stop_button = QPushButton("Motoru Durdur")
        self.estop_button = QPushButton("Acil Durdurma")
        self.estop_button.setProperty("danger", True)
        self.start_button.clicked.connect(self.motor_start_requested.emit)
        self.stop_button.clicked.connect(self.motor_stop_requested.emit)
        self.estop_button.clicked.connect(self._on_estop_clicked)

    def _on_estop_clicked(self):
        confirm = QMessageBox.warning(
            self, "ACİL DURDURMA gönderilsin mi?",
            "Motoru derhal durdurmak üzere ACİL DURDURMA komutu gönderilecek. Devam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes,
        )
        if confirm == QMessageBox.Yes:
            self.estop_requested.emit()

    # ======================================================================
    # Motor Parametreleri (8 gösterge) + sensör sağlığı
    # ======================================================================
    def _build_gauges_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 8, 14, 10)
        lay.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel("gauge", DK_CYAN, 18))
        t = QLabel("MOTOR PARAMETRELERİ")
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addSpacing(10)
        cap = QLabel("Sensör sağlığı")
        cap.setObjectName("mutedSmall")
        head.addWidget(cap)
        self._health_box = QHBoxLayout()
        self._health_box.setSpacing(6)
        head.addLayout(self._health_box)
        self._health_labels: list = []
        head.addStretch(1)
        self.map_warn_label = QLabel("")
        self.map_warn_label.setObjectName("warnSmall")
        head.addWidget(self.map_warn_label)
        lay.addLayout(head)

        grid = QGridLayout()
        grid.setSpacing(8)
        for i, key in enumerate(GAUGE_KEYS):
            lo, hi, unit = GAUGE_RANGES[key]
            gc = GaugeCard(key, GAUGE_DISPLAY_LABELS.get(key, key), lo, hi, unit)
            gc.lock_requested.connect(self._on_sensor_lock)
            gc.value_requested.connect(self._on_sensor_value_request)
            self._gauge_cards[key] = gc
            grid.addWidget(gc, i // 4, i % 4)
        for c in range(4):
            grid.setColumnStretch(c, 1)
        for r in range(2):
            grid.setRowStretch(r, 1)
        lay.addLayout(grid, 1)
        self.refresh_sensor_health()
        return card

    def refresh_sensor_health(self):
        """Arızalı sensörleri (neden ile birlikte) başlık şeridinde listeler."""
        for w in self._health_labels:
            self._health_box.removeWidget(w)
            w.deleteLater()
        self._health_labels = []
        faults = dict(self._faults)
        if not faults:
            w = QLabel("Arıza yok")
            w.setObjectName("chipGreen")
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
            elif self._sensor_open.get(key):
                gc.set_tag("MANUEL", "manual")
            else:
                gc.set_tag("")
        self._refresh_gauge_states()

    def _refresh_gauge_states(self):
        now = time.monotonic()
        unbound = set(self.config.unbound_gauges())
        for key, gc in self._gauge_cards.items():
            val = self._values.get(key)
            fresh = val is not None and (now - val[1]) <= STALE_S
            if fresh:
                gc.gauge.set_value(val[0])
                gc.set_status("")
            else:
                gc.gauge.set_value(None if val is None else val[0], dim=val is not None)
                if key in unbound:
                    gc.set_status("Eşleşme yok")
                elif val is not None:
                    gc.set_status(f"Veri yok ({STALE_S:.0f} sn)")
                else:
                    gc.set_status(self._reasons.get(key, "Veri bekleniyor"))

    def set_gauge_value(self, key: str, value):
        if isinstance(value, (int, float)):
            self._values[key] = (float(value), time.monotonic())
            self._reasons.pop(key, None)
            gc = self._gauge_cards.get(key)
            if gc is not None:
                gc.gauge.set_value(value)
                gc.set_status("")
            self.trend.append(f"g:{key}", value)
            self.gauge_sample.emit(key, float(value))
            self._check_limits(key, float(value))
        else:
            self._values.pop(key, None)
            gc = self._gauge_cards.get(key)
            if gc is not None:
                gc.gauge.set_value(None)

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

    # ---- sensör manuel değer (anahtar kapısı)
    def _on_sensor_lock(self, key: str, want_open: bool):
        smap = self.config.sensor_map(key)
        label = GAUGE_DISPLAY_LABELS.get(key, key)
        gc = self._gauge_cards[key]
        if want_open:
            if not smap.sw.is_set or not smap.value.is_set:
                QMessageBox.information(
                    self, "Eşleşme yok",
                    f"{label} için değer ve anahtar (_sw) eşleşmesi tanımlı değil.\n"
                    "⚙ Eşleşmeler penceresinden tanımlayın.")
                return
            if not self._confirm_override(label):
                return
            cur = self._values.get(key)
            start = cur[0] if cur is not None else self._sensor_manual.get(key, 0.0)
            if not self._write(smap.value, start, f"{label} değeri"):
                return
            if not self._write(smap.sw, 1.0, f"{label} anahtarı"):
                return
            self._sensor_open[key] = True
            self._sensor_manual[key] = start
            gc.lock.set_open(True)
        else:
            if not self._write(smap.sw, 0.0, f"{label} anahtarı"):
                return
            self._sensor_open[key] = False
            gc.lock.set_open(False)
        self.refresh_sensor_health()

    def _on_sensor_value_request(self, key: str):
        if not self._sensor_open.get(key):
            return
        smap = self.config.sensor_map(key)
        label = GAUGE_DISPLAY_LABELS.get(key, key)
        lo, hi, unit = GAUGE_RANGES[key]
        span = hi - lo
        cur = self._sensor_manual.get(key, lo)
        v, ok = QInputDialog.getDouble(self, f"{label} manuel değer",
                                       f"{label} için gönderilecek değer ({unit}):",
                                       cur, lo - span, hi + span, 3)
        if ok and self._write(smap.value, v, f"{label} değeri"):
            self._sensor_manual[key] = v

    # ======================================================================
    # Eyleyiciler
    # ======================================================================
    def _build_actuators_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 10, 14, 8)
        lay.setSpacing(0)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel("actuator", DK_CYAN, 18))
        t = QLabel("EYLEYİCİLER")
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        lay.addLayout(head)

        cols = QHBoxLayout()
        cols.setContentsMargins(2, 4, 2, 2)
        for text, align in (("EYLEYİCİ", Qt.AlignLeft), ("KOMUT", Qt.AlignRight), ("MANUEL", Qt.AlignRight)):
            c = QLabel(text)
            c.setObjectName("colHead")
            cols.addWidget(c, 1 if align == Qt.AlignLeft else 0)
            if text == "KOMUT":
                cols.addSpacing(34)
        lay.addLayout(cols)

        for key in ACTUATOR_KEYS:
            lay.addWidget(self._build_actuator_row(key), 1)
        lay.addStretch(1)      # satırlar azami yüksekliğe ulaşınca artan boşluk altta toplanır
        return card

    def _build_actuator_row(self, key: str) -> QFrame:
        kind = ACTUATOR_KINDS[key]
        row = QFrame()
        row.setObjectName("rowFrame")
        row.setMinimumHeight(28)
        row.setMaximumHeight(44)
        hl = QHBoxLayout(row)
        hl.setContentsMargins(0, 2, 0, 2)
        hl.setSpacing(10)
        icon = IconLabel(ACTUATOR_ICON[key], DK_CYAN, 18)
        name = QLabel(ACTUATOR_SHORT[key])
        name.setObjectName("rowName")
        hl.addWidget(icon)
        hl.addWidget(name, 1)
        entry = {"kind": kind, "name": name, "icon": icon}
        if kind == "toggle":
            onoff = QLabel("OFF")
            onoff.setObjectName("onoff")
            onoff.setProperty("on", False)
            sw = ToggleSwitch(on_color="#22c55e")
            sw.toggled.connect(lambda checked, k=key: self._on_actuator_toggle(k, checked))
            hl.addWidget(onoff)
            hl.addWidget(sw)
            entry.update(control=sw, onoff=onoff)
        else:
            spin = QDoubleSpinBox()
            spin.setObjectName("valueSpin")
            spin.setRange(0.0, 100.0)
            spin.setDecimals(1)
            spin.setSuffix(" %")
            spin.setKeyboardTracking(False)
            spin.setMinimumWidth(92)
            spin.valueChanged.connect(lambda v, k=key: self._on_actuator_value(k, v))
            hl.addWidget(spin)
            entry.update(control=spin)
        lock = LockButton(26)
        lock.lock_requested.connect(lambda want, k=key: self._on_actuator_lock(k, want))
        hl.addWidget(lock)
        entry["lock"] = lock
        entry["control"].setEnabled(False)
        self._act_rows[key] = entry
        self._style_actuator_row(key)
        return row

    def _style_actuator_row(self, key: str):
        e = self._act_rows[key]
        opened = self._act_open[key]
        e["name"].setEnabled(opened)
        e["icon"].setEnabled(opened)
        e["control"].setEnabled(opened)
        e["name"].setStyleSheet("" if opened else "color:#7d93a8;")

    def set_role(self, role: Role):
        self._role = role

    def _confirm_override(self, label: str) -> bool:
        if not can_override_actuator(self._role):
            QMessageBox.warning(
                self, "Yetki yok",
                f"{label} için manuel değeri açmak için Mühendis veya Yönetici rolü gerekir "
                "(Kullanıcı / Profil sekmesinden rol seçin).")
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

    def _actuator_value(self, key: str) -> float:
        e = self._act_rows[key]
        if e["kind"] == "toggle":
            return 1.0 if e["control"].isChecked() else 0.0
        return float(e["control"].value())

    def _on_actuator_lock(self, key: str, want_open: bool):
        amap = self.config.actuator_map(key)
        label = ACTUATOR_SHORT[key]
        e = self._act_rows[key]
        if want_open:
            if not amap.sw.is_set or not amap.value.is_set:
                QMessageBox.information(
                    self, "Eşleşme yok",
                    f"{label} için değer ve anahtar (_sw) eşleşmesi tanımlı değil.\n"
                    "⚙ Eşleşmeler penceresinden tanımlayın.")
                return
            if not self._confirm_override(label):
                return
            # önce değer, sonra anahtar: anahtar açıldığında ECU bilinen bir değer görür
            if not self._write(amap.value, self._actuator_value(key), f"{label} değeri"):
                return
            if not self._write(amap.sw, 1.0, f"{label} anahtarı"):
                return
            self._act_open[key] = True
            e["lock"].set_open(True)
        else:
            if not self._write(amap.sw, 0.0, f"{label} anahtarı"):
                return
            self._act_open[key] = False
            e["lock"].set_open(False)
        self._style_actuator_row(key)

    def _on_actuator_toggle(self, key: str, checked: bool):
        e = self._act_rows[key]
        e["onoff"].setText("ON" if checked else "OFF")
        e["onoff"].setProperty("on", checked)
        e["onoff"].style().unpolish(e["onoff"])
        e["onoff"].style().polish(e["onoff"])
        if not self._act_open[key]:
            return
        label = ACTUATOR_SHORT[key]
        if not self._write(self.config.actuator_map(key).value, 1.0 if checked else 0.0, f"{label} komutu"):
            e["control"].blockSignals(True)
            e["control"].setChecked(not checked)
            e["control"].blockSignals(False)
            e["onoff"].setText("ON" if not checked else "OFF")

    def _on_actuator_value(self, key: str, value: float):
        if not self._act_open[key]:
            return
        self._write(self.config.actuator_map(key).value, value, f"{ACTUATOR_SHORT[key]} komutu")

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
                    closed = self._write(self.config.actuator_map(key).sw, 0.0, f"{label} anahtarı")
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

    def _rebuild_trend_series(self):
        from app.ui.graph_signal_dialog import signal_label
        specs = []
        for sid in self.config.graph_signals:
            if sid.startswith("g:"):
                k = sid[2:]
                unit = GAUGE_RANGES[k][2] if k in GAUGE_RANGES else ""
                specs.append({"key": sid, "label": GAUGE_DISPLAY_LABELS.get(k, k), "unit": unit})
            elif sid.startswith("m:"):
                specs.append({"key": sid, "label": signal_label(sid), "unit": self._measurement_units.get(sid[2:], "")})
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
        self._rebuild_trend_series()
        miss = cfg.unbound_gauges()
        self.map_warn_label.setText(f"⚠ {len(miss)} sensör bağlı değil" if miss else "")
        self.start_button.setEnabled(cfg.motor_start.binding.is_set)
        self.stop_button.setEnabled(cfg.motor_stop.binding.is_set)
        self.estop_button.setEnabled(cfg.estop.binding.is_set)
        for btn, cmd, label in ((self.start_button, cfg.motor_start, "Motoru Başlat"),
                                 (self.stop_button, cfg.motor_stop, "Motoru Durdur"),
                                 (self.estop_button, cfg.estop, "Acil Durdurma")):
            btn.setToolTip("" if btn.isEnabled() else f"{label} için ⚙ Eşleşmeler penceresinden DBC sinyali veya A2L değişkeni seçin.")
        for key in GAUGE_KEYS:
            if key not in cfg.gauge_a2l_map() and key not in cfg.gauge_can_map():
                self._values.pop(key, None)
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
                                   + self.graph_measurement_names()))
        self._refresh_gauge_states()
        if names:
            self.tick.emit(names)
