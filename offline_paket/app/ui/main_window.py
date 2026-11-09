import logging
import os
import queue
import time
from datetime import datetime

import can
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QTabBar, QVBoxLayout, QWidget,
)

from app.can_worker import CanConnection
from app.ccp import codec as ccp_codec
from app.ccp import mapio as ccp_mapio
from app.ccp import protocol as ccp_protocol
from app.ccp.client import CCPClient
from app.ccp.worker import CONNECTING, IDLE, LOST, ONLINE, CcpSession
from app import control_panel as cpanel
from app.ui.control_panel_tab import ControlPanelTab
from app.ui.performance_tab import PerformanceTab
from app.sim_interface import INPUT_DEFS, SimConfig
from app.dashboard_config import (
    GAUGE_KEYS, SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfigStore,
)
from app.eventlog import EventLog
from app.history import CalibrationHistory
from app.logger import CanLogger
from app.paths import data_dir, data_path
from app.profiles import ConfigProfile, ProfileStore
from app.scheduler import PeriodicManager
from app.ui.a2l_tab import A2LTab
from app.ui.can_monitor_tab import CanMonitorTab
from app.ui.dashboard_tab import DashboardTab
from app.ui.analiz_tab import AnalizTab
from app.ui.workspace_tab import WorkspaceLayoutStore, WorkspaceTab
from app.ui.kalibrasyon_tab import KalibrasyonTab
from app.ui.tanilama_tab import TanilamaTab
from app.ui.settings_dialog import SettingsDialog
from app.ui.user_tab import UserTab
from app.ui.watch_tab import parse_value_text
from app.user_roles import (
    Role, can_manage_profiles, can_override_actuator, can_transmit_frames, can_run_diagnostics, can_write_calibration,
    can_write_flash,
)

RX_POLL_INTERVAL_MS = 30  # UI thread'in queue'yu ne sıklıkla yokladığı
HEALTH_CHECK_INTERVAL_MS = 500  # bağlantının GERÇEKTEN sağlıklı olup olmadığı (sürekli izleme)
# Adaptör/sürücü sorunu bu kadar SANİYE boyunca KESİNTİSİZ sürerse "bağlantı
# koptu" denir (anlık/geçici hatalarda yanlış alarm vermemek için).
CONNECTION_LOSS_CONFIRM_S = 3.0
RECONNECT_INTERVAL_MS = 2000  # bağlantı koptuktan sonra otomatik yeniden bağlanma denemesi aralığı
SILENT_NOTICE_S = 3.0  # bu kadar süre mesaj gelmezse bağlantı şeridinde "Hat sessiz" uyarısı
CCP_AUTO_CONNECT_DELAY_MS = 300  # CAN bağlandıktan kaç ms sonra CCP otomatik bağlansın
WATCH_FAIL_STREAK_LIMIT = 3  # Parametre Listesi'nde art arda bu kadar ECU-cevapsız turdan sonra sürekli okuma durur


class _ClickLabel(QLabel):
    """Tıklanabilir QLabel (bağlantı hapı)."""
    clicked = Signal()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenECU M220 — Test & Kalibrasyon Aracı")
        self._apply_initial_geometry()

        self.connection = CanConnection()
        self.periodic_manager: PeriodicManager | None = None
        self.can_logger = CanLogger()
        self._logged_count = 0
        self.ccp_session = CcpSession(self.connection)
        self.event_log = EventLog(file_path=data_path("audit_log.txt"))
        # calibration_history diske de kalıcı yazılır: FLAŞ yazımlarının,
        # uygulama kapansa/yeniden başlasa bile eski değerine geri
        # alınabilmesi gerektiği için (bkz. app/history.py).
        self.calibration_history = CalibrationHistory(file_path=data_path("calibration_history.json"))
        self.profile_store = ProfileStore(path=data_path("profiles.json"))
        self.dashboard_config_store = DashboardConfigStore(path=data_path("dashboard_config.json"))
        self.current_user = "bilinmeyen"
        self.current_role = Role.OPERATOR

        # ---- Bağlantı kopması izleme durumu (bkz. _check_connection_health)
        self._unhealthy_since: float | None = None
        self._conn_lost = False
        self._last_connect_params: tuple | None = None   # (interface, channel, bitrate)
        self._resume_ccp_after_reconnect = False
        self._loss_box: QMessageBox | None = None
        self._watch_fail_streak = 0

        self._sim_sent: set = set()
        self.sim_config = SimConfig(data_path("sim_interface.json"))
        self.dashboard_tab = DashboardTab(self.sim_config)
        self.performance_tab = PerformanceTab(self.sim_config)

        # ---- Birleştirilmiş sekmeler (bkz. app/ui/can_monitor_tab.py,
        # app/ui/tanilama_tab.py, app/ui/kalibrasyon_tab.py). Eski kod
        # tabanındaki 9 ayrı sekmenin iç widget'ları hiç değiştirilmedi;
        # aşağıdaki takma adlar (alias) bu dosyanın GERİ KALANINDAKİ tüm
        # `self.connection_tab.xxx` vb. referansların DEĞİŞMEDEN çalışmasını
        # sağlar.
        self.can_monitor_tab = CanMonitorTab()
        self.connection_tab = self.can_monitor_tab.connection
        self.monitor_tab = self.can_monitor_tab.monitor
        self.transmit_tab = self.can_monitor_tab.transmit
        self.log_tab = self.can_monitor_tab.log
        self.connection_tab.attach_settings(data_path("can_ayarlari.json"))
        self.monitor_tab.frame_hook = self._on_monitor_frame

        self.a2l_tab = A2LTab()
        self.control_panel_tab = ControlPanelTab(cpanel.ControlPanelConfig(data_path("kontrol_paneli.json")))
        self.tx_scheduler = cpanel.TxScheduler(self.transmit_tab.dbc, self._panel_send)

        self.kalibrasyon_tab = KalibrasyonTab(self.a2l_tab)   # A2L ilk iç sekme (a2l_tab takma adı korunur)
        self.ccp_tab = self.kalibrasyon_tab.ccp
        self.watch_tab = self.kalibrasyon_tab.watch
        self.map_editor_tab = self.kalibrasyon_tab.map_editor
        self.history_tab = self.kalibrasyon_tab.history

        self.workspace_tab = WorkspaceTab(WorkspaceLayoutStore(data_path("workspace_layouts.json")))
        # Çalışma Alanı + Performans tek "Analiz" sayfasında iç sekmeler olarak yaşar;
        # workspace_tab/performance_tab takma adları değişmeden kullanılır. (Eski Grafik sekmesi kaldırıldı:
        # Çalışma Alanı'nın grafik paneli A2L ölçümleri, ayarlanabilir skalerler ve ayrı pencere dahil
        # aynı işi daha kapsamlı yapıyor.)
        self.analiz_tab = AnalizTab(self.workspace_tab, self.performance_tab)

        self.tanilama_tab = TanilamaTab()
        self.diagnostics_tab = self.tanilama_tab.diagnostics
        self.errors_tab = self.tanilama_tab.errors

        self.session_tab = self.tanilama_tab.session      # Tanılama ve Oturum sayfasının parçası
        self.user_tab = UserTab()
        # Profil artık üst sekme değil: komut şeridindeki "⚙ Ayarlar" penceresi (rol + profiller)
        self.settings_dialog = SettingsDialog(self.user_tab, self)

        # ---- Sol kenar çubuğu navigasyonu + sayfa yığını (QStackedWidget).
        # Eskiden burada üstte bir QTabWidget sekme çubuğu vardı; kullanıcı
        # referans tasarıma göre bunu soldaki dikey navigasyona taşımamızı
        # istedi. Sayfa widget'larının KENDİSİ (dashboard_tab, vb.) hiç
        # değişmedi — yalnızca aralarında geçiş yöntemi değişti, bu yüzden
        # MainWindow'un geri kalanındaki `self.xxx_tab` referansları aynen
        # çalışmaya devam eder.
        self._nav_pages = [
            ("🏠", "Ana Sayfa", self.dashboard_tab),
            ("📶", "CAN Monitor", self.can_monitor_tab),
            ("⚙", "Kalibrasyon", self.kalibrasyon_tab),
            ("📈", "Analiz", self.analiz_tab),
            ("🎛", "Kontrol Paneli", self.control_panel_tab),
            ("🛡", "Tanılama ve Oturum", self.tanilama_tab),
        ]
        # Her sayfa kendi QScrollArea'sı içinde yaşar: pencere sayfa
        # içeriğinden KÜÇÜKSE (düşük çözünürlüklü laptop vb.) içerik aşağıdan
        # dışarı taşıp erişilemez olmak yerine dikey/yatay kaydırılabilir.
        # Pencere büyükse sayfa alanı doldurur (widgetResizable).
        self._cap_form_widths([p for _i, _l, p in self._nav_pages
                               if p not in (self.dashboard_tab, self.analiz_tab, self.performance_tab,
                                         self.control_panel_tab, self.workspace_tab)])
        self.stack = QStackedWidget()
        self._page_scrolls: dict[QWidget, QScrollArea] = {}
        # Koyu temaya geçirilmiş sayfalar (koyu gövdeye sarılır); diğerleri henüz açık temada.
        self._dark_pages = {self.tanilama_tab, self.session_tab, self.kalibrasyon_tab, self.analiz_tab, self.performance_tab, self.workspace_tab, self.control_panel_tab}
        for _icon, _label, page in self._nav_pages:
            # Ana Sayfa kaydırılmaz: 16" ekrana tamamen sığar (bkz. DashboardTab)
            self.stack.addWidget(page if page is self.dashboard_tab else self._make_scrollable_page(page))

        self._build_ui_chrome()

        self.dashboard_tab.set_config(self.dashboard_config_store.load())
        self._rebuild_dash_can_map()
        self.watch_tab.set_storage_path(data_path("watchlist.json"))

        # İzleme sekmesi, Gönderim sekmesindeki DBC ile AYNI nesneyi kullanır;
        # böylece DBC yüklenince ikisi de aynı anda görür.
        self.monitor_tab.dbc = self.transmit_tab.dbc
        self.transmit_tab.dbc_loaded.connect(self.monitor_tab.refresh_dbc_messages)

        # CCP sekmesi, A2L (Kalibrasyon > A2L) sekmesindeki AYNI A2LDatabase nesnesini kullanır;
        # A2L yüklenince nesne tarayıcısı orada da güncellenir.
        self.ccp_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.ccp_tab.refresh_objects)

        self.map_editor_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.map_editor_tab.refresh_objects)

        self.watch_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.watch_tab.refresh_objects)
        self.watch_tab.refresh_objects()

        # Çalışma Alanı: A2L/DBC listeleri, CCP okuma isteği, giriş/gösterge beslemesi.
        self.a2l_tab.a2l_loaded.connect(self._sync_workspace_a2l)
        self.transmit_tab.dbc_loaded.connect(lambda *_: self.workspace_tab.set_dbc(self.transmit_tab.dbc))
        self.workspace_tab.set_dbc(self.transmit_tab.dbc)
        self.workspace_tab.read_requested.connect(self._on_workspace_tick)
        self.dashboard_tab.gauge_sample.connect(lambda k, v: self.workspace_tab.push(f"gauge:{k}", v))
        self.workspace_tab.set_input_values(self.dashboard_tab.sim_inputs.values())
        self.dashboard_tab.sim_inputs.values_changed.connect(self.workspace_tab.set_input_values)

        # Ana Sayfa > Canlı Grafik'in 'Sinyalleri seç' penceresi A2L ölçümlerini listeler.
        self.a2l_tab.a2l_loaded.connect(self._sync_dashboard_measurements)

        self.session_tab.event_log = self.event_log
        self.history_tab.history = self.calibration_history
        self.user_tab.set_profiles(self.profile_store.names())

        self.dashboard_tab.motor_start_requested.connect(self._on_motor_start)
        self.dashboard_tab.motor_stop_requested.connect(self._on_motor_stop)
        self.dashboard_tab.estop_requested.connect(self._on_estop)
        self.dashboard_tab.config_saved.connect(self._on_dashboard_config_saved)
        self.dashboard_tab.tick.connect(self._on_dashboard_tick)
        self.dashboard_tab.writer = self._write_binding
        self.transmit_tab.dbc_loaded.connect(self._on_dashboard_sources_changed)
        self.a2l_tab.a2l_loaded.connect(self._on_dashboard_sources_changed)
        self.dashboard_tab.set_role(self.current_role)
        if hasattr(self, "header_role_label"):
            self._update_role_label()

        self._wire_signals()

        self.rx_timer = QTimer(self)
        self.rx_timer.setInterval(RX_POLL_INTERVAL_MS)
        self.rx_timer.timeout.connect(self._drain_rx_queue)

        self.health_timer = QTimer(self)
        self.health_timer.setInterval(HEALTH_CHECK_INTERVAL_MS)
        self.health_timer.timeout.connect(self._check_connection_health)

        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setInterval(RECONNECT_INTERVAL_MS)
        self.reconnect_timer.timeout.connect(self._try_reconnect)

        QTimer.singleShot(800, self._startup_auto_connect)
        self._ccp_timer = QTimer(self)
        self._ccp_timer.setInterval(100)
        self._ccp_timer.timeout.connect(self._on_ccp_events)
        self._ccp_timer.start()
        self.connection.on_reopen.append(self._on_bus_reopened)

    # ---- CCP oturumu (arka plan iş parçacığı; bkz. app/ccp/worker.py) ----------------------
    @property
    def ccp_client(self):
        """Açık işlemler (yazma, harita, tanılama) için CCPClient benzeri; oturum yoksa None.
        ECU 'yok' iken çağrılar bekletmeden hata verir."""
        return self.ccp_session.client

    @ccp_client.setter
    def ccp_client(self, client):
        if client is None:
            self.ccp_session.stop(graceful=False)
        else:
            self.ccp_session.adopt(client)

    @property
    def ccp_reader(self):
        """Periyodik okuma yapan arayüz zamanlayıcıları için: önbellekten okur, ASLA beklemez."""
        return self.ccp_session.reader

    def _make_scrollable_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        if page in self._dark_pages:
            from app.ui.dark_theme import dark_scroll_page
            scroll.setStyleSheet("QScrollArea#pageScroll { background: #EEF2F6; border: none; }")
            scroll.setWidget(dark_scroll_page(page))
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.NoFrame)
            self._page_scrolls[page] = scroll
            return scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(page)
        self._page_scrolls[page] = scroll
        return scroll

    def current_page(self) -> QWidget | None:
        """Şu an görünen sayfanın KENDİ widget'ı (QScrollArea / koyu gövde sarmalayıcısı değil)."""
        scroll = self.stack.currentWidget()
        inner = scroll.widget() if isinstance(scroll, QScrollArea) else scroll
        return getattr(inner, "inner", inner)

    def _apply_initial_geometry(self):
        """İlk pencere boyutu EKRANA sığmalı: sabit 1600x950, 1366x768 gibi
        laptop ekranlarında pencereyi alt kenardan dışarı taşırıyordu.
        Kullanılabilir alanın %92'sini aşmayacak şekilde seçilir."""
        self.setMinimumSize(1100, 600)
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        avail = screen.availableGeometry()
        width = min(1600, int(avail.width() * 0.92))
        height = min(950, int(avail.height() * 0.92))
        self.resize(max(1100, width), max(600, height))
        frame = self.frameGeometry()
        frame.moveCenter(avail.center())
        self.move(frame.topLeft())

    # ---- Genel pencere çatısı (chrome): sol sidebar + üst (koyu lacivert)
    # başlık çubuğu + tek "buton + durum" satırı + sayfa yığını + alt
    # durum çubuğu (referans mockup'a göre: iki AYRI üst şerit — koyu
    # lacivert başlık şeridi, hemen altında açık renkli tek bir buton/
    # durum satırı — büyük koyu ikaz lambası şeridi YOK). --------------
    def _build_ui_chrome(self):
        self._conn_state = {"connected": False, "lost": False, "interface": "—", "version": "—"}

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._build_top_header())
        central_layout.addWidget(self._build_action_status_row())
        central_layout.addWidget(self.stack, stretch=1)

        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)
        # Ana Sayfa kaydırılmadığı için pencere, sayfanın sığacağı en küçük boyuttan
        # küçültülemez (16" laptop: 1280x720 etkin çözünürlükte bile sığar).
        hint = central.minimumSizeHint()
        self.setMinimumSize(max(1100, hint.width()), max(600, hint.height() + 26))
        self.resize(max(self.width(), self.minimumWidth()), max(self.height(), self.minimumHeight()))
        self.header_clock_label = QLabel("")
        self.header_clock_label.setObjectName("headerClock")
        self.statusBar().addPermanentWidget(self.header_clock_label)
        self._update_connection_display()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

    def _apply_shadow(self, widget: QWidget, blur: float = 18, dy: float = 3, alpha: int = 45):
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setOffset(0, dy)
        effect.setColor(QColor(20, 30, 40, alpha))
        widget.setGraphicsEffect(effect)

    def _build_top_header(self) -> QWidget:
        """Üst şerit: logo + başlık + YATAY sekme çubuğu (sidebar yok) + bağlantı pili.
        Sekmeler sabittir: kapatılamaz/taşınamaz, "Ana Sayfa" her zaman ilk sekmedir."""
        header = QFrame()
        header.setObjectName("topHeaderNavy")
        outer = QHBoxLayout(header)
        outer.setContentsMargins(14, 0, 14, 0)
        outer.setSpacing(14)

        logo = QLabel("⚡")
        logo.setObjectName("headerLogoBadge")
        logo.setFixedSize(24, 24)
        logo.setAlignment(Qt.AlignCenter)
        outer.addWidget(logo)
        title = QLabel("ECU CAN Arayüzü")
        title.setObjectName("headerTitle")
        outer.addWidget(title)

        self.nav_bar = QTabBar()
        self.nav_bar.setObjectName("topNav")
        self.nav_bar.setDrawBase(False)
        self.nav_bar.setExpanding(False)
        self.nav_bar.setMovable(False)
        self.nav_bar.setTabsClosable(False)
        self.nav_bar.setUsesScrollButtons(False)
        self.nav_bar.setFocusPolicy(Qt.NoFocus)
        for _icon, label, _page in self._nav_pages:
            self.nav_bar.addTab(label)
        self.nav_bar.setCurrentIndex(0)
        self.nav_bar.currentChanged.connect(self.stack.setCurrentIndex)
        outer.addWidget(self.nav_bar, 1)

        self.header_conn_pill = _ClickLabel("●  Bağlı değil")
        self.header_conn_pill.setObjectName("connPillBad")
        self.header_conn_pill.setCursor(Qt.PointingHandCursor)
        self.header_conn_pill.setToolTip("Tıkla: bağlantı ayarları (CAN Monitor sekmesi)")
        self.header_conn_pill.clicked.connect(self._open_connection_page)
        outer.addWidget(self.header_conn_pill)
        return header

    def _build_action_status_row(self) -> QWidget:
        """Sekmelerin altındaki komut şeridi (TÜM sayfalarda görünür; Acil Durdurma
        her zaman erişilebilir): Motoru Başlat / Durdur / Acil Durdurma, sağda rol ve
        ⚙ Eşleşmeler."""
        row = QFrame()
        row.setObjectName("actionStatusRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 4, 14, 4)
        layout.setSpacing(10)

        self.dashboard_tab.start_button.setText("▶  Motoru Başlat")
        self.dashboard_tab.stop_button.setText("⏹  Motoru Durdur")
        self.dashboard_tab.estop_button.setText("⚠  Acil Durdurma")
        for btn in (self.dashboard_tab.start_button, self.dashboard_tab.stop_button,
                    self.dashboard_tab.estop_button):
            btn.setFixedHeight(30)
            btn.setMinimumWidth(150)
            btn.setCursor(Qt.PointingHandCursor)
            if btn is self.dashboard_tab.estop_button:
                # Acil Durdurma normal komutlardan görsel olarak ayrılır
                sep = QFrame()
                sep.setObjectName("cmdSep")
                sep.setFixedHeight(22)
                layout.addSpacing(6)
                layout.addWidget(sep)
                layout.addSpacing(6)
            layout.addWidget(btn)
        layout.addWidget(self.dashboard_tab.estop_warn)

        layout.addStretch()
        self.ccp_chip = QLabel("CCP bağlı değil")
        self.ccp_chip.setObjectName("ccpChip")
        self.ccp_chip.setProperty("state", IDLE)
        self.ccp_chip.setToolTip("CCP/ECU durumu: bağlı değil → bağlanıyor → çevrimiçi → ECU yok (otomatik yeniden bağlanır)")
        layout.addWidget(self.ccp_chip)
        layout.addSpacing(8)
        self.header_role_label = _ClickLabel("")
        self.header_role_label.setObjectName("headerReadout")
        self.header_role_label.setTextFormat(Qt.RichText)
        self.header_role_label.setCursor(Qt.PointingHandCursor)
        self.header_role_label.setToolTip("Tıkla: kullanıcı ve rol ayarları")
        self.header_role_label.clicked.connect(self.open_settings)
        layout.addWidget(self.header_role_label)
        self.settings_button = QPushButton("⚙  Ayarlar")
        self.settings_button.setFixedHeight(28)
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setToolTip("Kullanıcı / rol ve bağlantı+CCP profilleri")
        self.settings_button.clicked.connect(self.open_settings)
        layout.addWidget(self.settings_button)
        self.mappings_button = QPushButton("⚙  Eşleşmeler")
        self.mappings_button.setFixedHeight(28)
        self.mappings_button.setCursor(Qt.PointingHandCursor)
        self.mappings_button.setToolTip("Sensör, eyleyici, motor komutu ve giriş sinyallerinin CAN (DBC) / A2L eşleşmeleri")
        self.mappings_button.clicked.connect(self.dashboard_tab.open_mappings)
        layout.addWidget(self.mappings_button)
        self._update_role_label()
        return row

    def _open_connection_page(self):
        """Bağlantı hapına tıklanınca CAN Monitor (bağlantı şeridi) sekmesine geç."""
        for i, (_icon, label, _page) in enumerate(self._nav_pages):
            if label == "CAN Monitor":
                self.nav_bar.setCurrentIndex(i)
                return

    def open_settings(self):
        """Ayarlar penceresi (kullanıcı/rol + profiller)."""
        self.settings_dialog.exec()

    def _update_role_label(self):
        self.header_role_label.setText(f"Rol: <b style='color:#121A22'>{self.current_role.value} ▾</b>")

    def _update_clock(self):
        now_text = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
        self.header_clock_label.setText(now_text)

    def _update_connection_display(self, health_message: str | None = None):
        connected = self._conn_state["connected"]
        interface = self._conn_state["interface"]
        version = self._conn_state["version"]

        lost = bool(self._conn_state.get("lost", False))
        if connected:
            self.header_conn_pill.setObjectName("connPillOk")
            self.header_conn_pill.setText(f"●  Bağlı  |  {interface}")
        elif lost:
            self.header_conn_pill.setObjectName("connPillBad")
            self.header_conn_pill.setText("●  Bağlantı koptu — yeniden bağlanılıyor…")
        else:
            self.header_conn_pill.setObjectName("connPillBad")
            self.header_conn_pill.setText("●  Bağlı değil")
        # objectName değiştiğinde QSS'in yeniden uygulanması gerekir.
        self.header_conn_pill.style().unpolish(self.header_conn_pill)
        self.header_conn_pill.style().polish(self.header_conn_pill)

        state_word = "Bağlı" if connected else ("BAĞLANTI KOPTU" if lost else "Bağlı değil")
        status_text = f"Arayüz: {interface}   |   Durum: {state_word}   |   CAN: {version}"
        if health_message:
            status_text += f"   |   {health_message}"
        self.statusBar().showMessage(status_text)

    @staticmethod
    def _cap_form_widths(pages, max_w: int = 420):
        """Tam ekranda form alanlarının (metin kutusu / açılır liste) yatayda
        aşırı uzamasını engeller; tablolar ve listeler etkilenmez."""
        from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit
        for page in pages:
            for form in page.findChildren(QFormLayout):
                for row in range(form.rowCount()):
                    item = form.itemAt(row, QFormLayout.FieldRole)
                    w = item.widget() if item is not None else None
                    if isinstance(w, (QLineEdit, QComboBox)) and w.maximumWidth() > max_w:
                        w.setMaximumWidth(max_w)

    def setCurrentWidget(self, widget):
        """Eski QTabWidget tabanlı kodun `self.setCurrentWidget(...)`
        çağrılarının değişmeden çalışmaya devam etmesi için ince bir uyumluluk
        katmanı: hem sayfa yığınını hem de üst sekme çubuğunu günceller."""
        index = self.stack.indexOf(self._page_scrolls.get(widget, widget))
        if index != -1:
            self.nav_bar.setCurrentIndex(index)

    def _wire_signals(self):
        self.connection_tab.connect_requested.connect(self._on_connect)
        self.connection_tab.disconnect_requested.connect(self._on_disconnect)

        self.transmit_tab.manual_send_requested.connect(self._on_manual_send)
        self.transmit_tab.periodic_start_requested.connect(self._on_periodic_start)
        self.transmit_tab.periodic_stop_requested.connect(self._on_periodic_stop)

        self.log_tab.start_requested.connect(self._on_log_start)
        self.log_tab.stop_requested.connect(self._on_log_stop)

        self.ccp_tab.connect_requested.connect(self._on_ccp_connect)
        self.ccp_tab.disconnect_requested.connect(self._on_ccp_disconnect)
        self.ccp_tab.read_requested.connect(self._on_ccp_read)
        self.ccp_tab.write_requested.connect(self._on_ccp_write)

        self.ccp_tab.open_in_map_editor_requested.connect(self._open_in_map_editor)

        self.transmit_tab.dbc_loaded.connect(self._panel_sources_changed)
        self.a2l_tab.a2l_loaded.connect(self._panel_sources_changed)
        self.control_panel_tab.apply_requested.connect(self._on_panel_apply)
        self.dashboard_tab.sim_inputs.values_changed.connect(self._on_sim_inputs)
        self.dashboard_tab.sim_inputs.set_allowed(can_override_actuator(self.current_role))
        self.performance_tab.poll_requested.connect(self._on_perf_poll)
        self.control_panel_tab.poll_requested.connect(self._on_panel_poll)
        self.control_panel_tab.kill_overrides_requested.connect(self._on_panel_kill_overrides)
        self.control_panel_tab.tx_toggle_requested.connect(self._on_panel_tx_toggle)
        self.control_panel_tab.reload_requested.connect(self._on_panel_reload)
        self.tx_scheduler.failed.connect(self._on_panel_tx_failed)
        self.tx_scheduler.recovered.connect(self._on_panel_tx_recovered)
        self.tx_scheduler.state_changed.connect(self._panel_tx_state)
        self.control_panel_tab.set_allowed(can_override_actuator(self.current_role))
        self.watch_tab.read_requested.connect(self._on_watch_read)
        self.watch_tab.write_requested.connect(self._on_watch_write)

        self.map_editor_tab.read_requested.connect(self._on_map_read)
        self.map_editor_tab.write_requested.connect(self._on_map_write)
        self.map_editor_tab.read_all_requested.connect(self._on_map_read_all)
        self.map_editor_tab.write_all_requested.connect(self._on_map_write_all)

        self.diagnostics_tab.test_requested.connect(self._on_diag_test_requested)
        self.diagnostics_tab.diag_requested.connect(self._on_diag_requested)

        self.history_tab.revert_requested.connect(self._on_history_revert)

        self.settings_dialog.mappings_requested.connect(self.dashboard_tab.open_mappings)
        self.user_tab.role_applied.connect(self._on_role_applied)
        self.user_tab.profile_save_requested.connect(self._on_profile_save)
        self.user_tab.profile_apply_requested.connect(self._on_profile_apply)
        self.user_tab.profile_delete_requested.connect(self._on_profile_delete)

    def _log_event(self, category: str, message: str):
        self.event_log.add(category, message, user=self.current_user, role=self.current_role.value)
        self.session_tab.refresh_log()

    # ---- Bağlantı ----------------------------------------------------
    def _on_connect(self, interface: str, channel: str, bitrate: int):
        # Kullanıcı elle bağlanıyorsa bekleyen otomatik yeniden bağlanma iptal.
        self._cancel_reconnect()
        try:
            self.connection.connect(interface, channel, bitrate)
        except Exception as exc:  # python-can farklı arka uçlarda farklı hata tipleri fırlatabilir
            QMessageBox.critical(self, "Bağlantı hatası", str(exc))
            return
        self._after_connected(interface, channel, bitrate)

    def _after_connected(self, interface: str, channel: str, bitrate: int, reconnected: bool = False):
        """connect() başarılı olduktan sonraki ortak kurulum (hem elle
        bağlanma hem de koptuktan sonra otomatik yeniden bağlanma)."""
        self._last_connect_params = (interface, channel, bitrate)
        self._unhealthy_since = None
        self._last_health_state = "ok"
        self._conn_lost = False
        self._dismiss_loss_box()
        self.periodic_manager = PeriodicManager(lambda: self.connection.bus)
        self.connection_tab.set_connected(True)
        self.monitor_tab.set_bitrate(bitrate if interface != "virtual" else None)
        self.rx_timer.start()
        self._panel_conn_state()
        self._log_event(
            "BAGLANTI",
            f"CAN hattına {'yeniden ' if reconnected else ''}bağlanıldı ({interface}, {channel}, {bitrate} bps)"
        )
        self._conn_state.update(connected=True, lost=False, interface=f"{interface}/{channel}",
                                version=f"{bitrate} bps")
        self._update_connection_display()

        # can.Bus() hata firlatmamis olmasi, donanimin GERCEKTEN saglikli
        # oldugu anlamina gelmez (ozellikle pcan'de) - hemen bir kere,
        # sonra da SUREKLI olarak (her HEALTH_CHECK_INTERVAL_MS) gercek
        # durumu sorguluyoruz.
        self._check_connection_health()
        self.health_timer.start()

        # CAN'a bağlanınca CCP'yi de otomatik bağla (kutu işaretliyse; ya da
        # bağlantı koptuğunda CCP açıktıysa yeniden kurulumda). Manuel
        # CCP Bağlan / Kes düğmeleri ayrıca çalışmaya devam eder.
        if self.ccp_tab.auto_connect_enabled() or self._resume_ccp_after_reconnect:
            self._resume_ccp_after_reconnect = False
            self._auto_ccp_connect()

    def _release_overrides_on_teardown(self, graceful: bool):
        """Bağlantı kapanırken ECU'da AÇIK kalmış eyleyici override'larını (kilit açık) bırakmayı
        dener (graceful) ve her durumda arayüzü 'bilinmiyor/kilitli'ye çeker. Bırakılamayanlar
        HATA olarak loglanır ve kullanıcıya gösterilir."""
        try:
            unconfirmed = self.dashboard_tab.release_all_actuators(write=graceful)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("override bırakma hatası")
            return
        if unconfirmed:
            names = ", ".join(unconfirmed)
            self._log_event("HATA", f"Bağlantı kapandı; ECU'da şu override'lar AÇIK kalmış olabilir: {names}")
            self.statusBar().showMessage(f"UYARI: override açık kalmış olabilir: {names}", 15000)

    def _teardown_connection(self, graceful: bool = True):
        """CAN bağlantısına bağlı her şeyi kapatır. graceful=False: adaptör
        gitmiş olduğu için CCP DISCONNECT gibi bus'a yazan adımlar ATLANIR
        (aksi halde zaman aşımlarında arayüz bloklanırdı)."""
        self._release_overrides_on_teardown(graceful)   # CCP/CAN hâlâ açıkken: override'ları bırakmayı dene
        if self.ccp_session.state != IDLE:
            if graceful:
                self._on_ccp_disconnect()
            else:
                self._drop_ccp_client()
        if self.periodic_manager is not None:
            try:
                self.periodic_manager.stop_all()
            except Exception:
                pass
            self.periodic_manager = None
        self.transmit_tab.stop_all_rows()
        self.tx_scheduler.stop_all()
        self.rx_timer.stop()
        self.health_timer.stop()
        self.connection.disconnect()
        self.connection_tab.set_connected(False)
        self._panel_conn_state()

    def _on_disconnect(self):
        self._cancel_reconnect()
        self._conn_lost = False
        self._dismiss_loss_box()
        self._unhealthy_since = None
        self._teardown_connection(graceful=True)
        self.errors_tab.set_health(False, "Bağlı değil")
        self._log_event("BAGLANTI", "CAN bağlantısı kesildi")
        self._conn_state.update(connected=False, lost=False, interface="—", version="—")
        self._update_connection_display()

    # ---- Bağlantı SÜREKLİ izleme + kopma tespiti + otomatik yeniden bağlanma
    def _check_connection_health(self):
        """Her HEALTH_CHECK_INTERVAL_MS'de sürücüden gerçek bağlantı durumunu
        sorar. Adaptör/sürücü sorunu CONNECTION_LOSS_CONFIRM_S saniye
        KESİNTİSİZ sürerse "bağlantı koptu" der (anlık hatada yanlış alarm
        yok). Hat düzeyi sorunlar (ECU kapalı, bus-off...) kopma sayılmaz,
        yalnızca uyarı olarak gösterilir."""
        if not self.connection.is_connected:
            return
        # Bus-off/ağır hata + sessizlikte reset → gerekirse adaptörü yeniden aç (otomatik kurtarma);
        # PCAN durum kodu geçişleri donanım testinde teşhis için günlüğe yazılır.
        for event in self.connection.watchdog():
            self._log_event("BAGLANTI", event)
        state, message = self.connection.link_state()
        now = time.monotonic()

        if state == "lost":
            if self._unhealthy_since is None:
                self._unhealthy_since = now
                self._log_event("HATA", f"CAN bağlantı sorunu algılandı, doğrulanıyor: {message}")
            elapsed = now - self._unhealthy_since
            if elapsed >= CONNECTION_LOSS_CONFIRM_S:
                self._handle_connection_lost(message, elapsed)
                return
            shown = f"Bağlantı sorunu algılandı, doğrulanıyor… ({elapsed:.0f}/{CONNECTION_LOSS_CONFIRM_S:.0f} sn): {message}"
            self.connection_tab.set_health(False, shown)
            self.errors_tab.set_health(False, shown)
            self._update_connection_display(health_message=shown)
            return

        if self._unhealthy_since is not None:
            lasted = now - self._unhealthy_since
            self._log_event("BAGLANTI", f"CAN bağlantı sorunu kendiliğinden geçti ({lasted:.1f} sn sürdü)")
            self._unhealthy_since = None

        ok = state == "ok"
        silent = self.connection.silent_for()
        if state == "bus_warning" and self.connection.recovering:
            message = f"Hat hatalı, kurtarılıyor: {message} (son mesaj {silent:.0f} sn önce)"
        elif ok and silent > SILENT_NOTICE_S:
            ok = False
            message = f"Hat sessiz ({silent:.0f} sn): ECU kapalı olabilir; hat dönünce otomatik sürer"
        self.connection_tab.set_health(ok, message)
        self.errors_tab.set_health(ok, message)
        if not ok and getattr(self, "_last_health_state", "ok") == "ok":
            self._log_event("HATA", f"CAN hat durumu uyarısı: {message}")
        self._last_health_state = state
        self._update_connection_display(health_message=message)

    def _handle_connection_lost(self, reason: str, elapsed: float):
        """Bağlantı KOPTU: her şeyi temizle, kullanıcıya açıkça bildir ve
        adaptör geri gelirse otomatik yeniden bağlanmak için denemeye başla."""
        self._resume_ccp_after_reconnect = self.ccp_session.state != IDLE or self._resume_ccp_after_reconnect
        self._conn_lost = True
        self._unhealthy_since = None
        self._teardown_connection(graceful=False)  # adaptör yok: bus'a yazan adımlar atlanır
        self.watch_tab.stop_polling()
        self.connection_tab.set_lost(True)
        self._panel_conn_state()
        lost_text = f"Bağlantı koptu: {reason}"
        self.errors_tab.set_health(False, lost_text)
        self._log_event(
            "HATA",
            f"CAN BAĞLANTISI KOPTU ({elapsed:.1f} sn boyunca adaptör yanıt vermedi): {reason}. "
            "Otomatik yeniden bağlanma deneniyor."
        )
        self._conn_state.update(connected=False, lost=True, version="—")
        self._update_connection_display(health_message=lost_text)
        self._show_loss_box(reason)
        self.reconnect_timer.start()

    def _show_loss_box(self, reason: str):
        self._dismiss_loss_box()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("CAN bağlantısı koptu")
        box.setText(
            "CAN adaptörüyle bağlantı koptu (adaptör çıkarılmış veya sürücü yanıt vermiyor olabilir)."
        )
        box.setInformativeText(
            f"Ayrıntı: {reason}\n\nAdaptörü tekrar taktığınızda uygulama otomatik "
            "olarak yeniden bağlanmayı dener. İsterseniz CAN Monitor sekmesinden "
            "elle de bağlanabilirsiniz."
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.setWindowModality(Qt.NonModal)  # arayüzü kilitlemesin
        box.setAttribute(Qt.WA_DeleteOnClose, True)
        box.show()
        self._loss_box = box

    def _dismiss_loss_box(self):
        if self._loss_box is not None:
            try:
                self._loss_box.close()
            except RuntimeError:
                pass  # zaten silinmiş
            self._loss_box = None

    def _cancel_reconnect(self):
        self.reconnect_timer.stop()

    def _on_bus_reopened(self):
        """Bekçi adaptörü yeniden açınca: CCP istemcisi ve periyodik görevler yeni bus'a geçer
        (periyodik görevler bus'ı çağrılabilirle aldığı için kendiliğinden geçer)."""
        self.ccp_session.refresh_bus()
        self._log_event("BAGLANTI", "Adaptör yeniden açıldı; CCP ve periyodik gönderim yeni bus'a geçti")

    def _try_reconnect(self):
        if not self._conn_lost or self._last_connect_params is None:
            self._cancel_reconnect()
            return
        interface, channel, bitrate = self._last_connect_params
        try:
            self.connection.connect(interface, channel, bitrate)
        except Exception:
            return  # adaptör hâlâ yok; sonraki turda tekrar dene
        state, _msg = self.connection.link_state()
        if state == "lost":
            self.connection.disconnect()  # açıldı ama sağlıksız: vazgeç, sonra tekrar dene
            return
        self._cancel_reconnect()
        self._log_event("BAGLANTI", "CAN adaptörü geri geldi, bağlantı otomatik yeniden kuruldu")
        self._after_connected(interface, channel, bitrate, reconnected=True)

    # ---- Alım (Receive) -----------------------------------------------
    RX_DRAIN_MAX_FRAMES = 400     # tek tick'te işlenecek en çok kare
    RX_DRAIN_MAX_SECONDS = 0.015  # ... ve en çok bu kadar süre (UI donmasın)

    def _drain_rx_queue(self):
        deadline = time.monotonic() + self.RX_DRAIN_MAX_SECONDS
        n = 0
        while n < self.RX_DRAIN_MAX_FRAMES and time.monotonic() < deadline:
            try:
                msg = self.connection.rx_queue.get_nowait()
            except queue.Empty:
                break
            n += 1
            self.monitor_tab.add_message(msg, direction="RX")
            self.control_panel_tab.on_can_frame(msg.arbitration_id, bytes(msg.data))
            self.performance_tab.on_can_frame(msg.arbitration_id, bytes(msg.data))
            self.workspace_tab.on_can_frame(msg.arbitration_id, bytes(msg.data))
            self._dash_on_can_frame(msg.arbitration_id, bytes(msg.data))

    def _on_monitor_frame(self, msg, direction: str):
        """İzleme sekmesi her RX/TX mesajı için çağırır (duraklatılmış olsa da): kayıt açıksa
        CSV'ye yön ve (DBC varsa) mesaj adıyla yazar."""
        if not self.can_logger.is_active:
            return
        name = ""
        dbc = self.transmit_tab.dbc
        if dbc.is_loaded:
            m = dbc.get_message_by_frame_id(msg.arbitration_id)
            name = m.name if m is not None else ""
        self.can_logger.write(msg.timestamp, msg.arbitration_id, msg.dlc, msg.data,
                              msg.is_extended_id, direction=direction, name=name)
        self._logged_count += 1
        self.log_tab.set_count(self._logged_count)
        if self.can_logger.error and not self.can_logger.is_active:
            self.log_tab.set_active(False, "")
            err = self.can_logger.error
            self.can_logger.error = None
            self._log_event("HATA", f"CAN kaydı yazma hatasıyla DURDU: {err}")
            QMessageBox.warning(self, "CAN kaydı durdu", f"Yazma hatası: {err}")

    def _startup_auto_connect(self):
        """"Açılışta otomatik bağlan" seçiliyse sessizce bağlanır; hata iletişim kutusu açmaz."""
        if self.connection.is_connected or not self.connection_tab.auto_connect_enabled():
            return
        interface = self.connection_tab.current_interface()
        channel = self.connection_tab.current_channel()
        bitrate = self.connection_tab.current_bitrate()
        try:
            self.connection.connect(interface, channel, bitrate)
        except Exception as exc:
            self.connection_tab.set_health(False, f"Otomatik bağlanma başarısız: {exc}")
            self._log_event("HATA", f"Otomatik bağlanma başarısız: {exc}")
            return
        self._after_connected(interface, channel, bitrate)

    # ---- Gönderim -------------------------------------------------------
    @staticmethod
    def _frame_text(can_id: int, data: bytes, extended: bool) -> str:
        return f"ID=0x{can_id:X}{' (ext)' if extended else ''} DLC={len(data)} DATA={data.hex(' ').upper()}"

    def _on_manual_send(self, can_id: int, data: bytes, extended: bool):
        if not can_transmit_frames(self.current_role):
            QMessageBox.warning(self, "Yetki yok",
                                "CAN çerçevesi göndermek için Mühendis veya Yönetici rolü gerekir "
                                "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
            return
        try:
            self.connection.send(can_id, data, extended)
        except Exception as exc:
            QMessageBox.critical(self, "Gönderim hatası", str(exc))
            self._log_event("HATA", f"Manuel gönderim başarısız: {exc}")
            return
        self._log_event("GÖNDERİM", "Manuel çerçeve gönderildi: " + self._frame_text(can_id, data, extended))
        sent_msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=extended,
                                timestamp=time.time())
        self.monitor_tab.add_message(sent_msg, direction="TX")

    def _on_periodic_start(self, row_key: str, can_id: int, data: bytes,
                            extended: bool, period_ms: int):
        if not can_transmit_frames(self.current_role):
            self.transmit_tab.mark_start_failed(row_key)
            QMessageBox.warning(self, "Yetki yok",
                                "Periyodik gönderim için Mühendis veya Yönetici rolü gerekir "
                                "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
            return
        if self.periodic_manager is None:
            self.transmit_tab.mark_start_failed(row_key)
            QMessageBox.warning(self, "Bağlantı yok", "Önce CAN hattına bağlanın.")
            return
        try:
            self.periodic_manager.start(row_key, can_id, data, extended, period_ms)
        except Exception as exc:
            self.transmit_tab.mark_start_failed(row_key)
            QMessageBox.critical(self, "Periyodik gönderim hatası", str(exc))
            self._log_event("HATA", f"Periyodik gönderim başlatılamadı: {exc}")
            return
        self._log_event("GÖNDERİM", f"Periyodik gönderim BAŞLADI [{period_ms} ms]: "
                                    + self._frame_text(can_id, data, extended))
        sent_msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=extended,
                                timestamp=time.time())
        self.monitor_tab.add_message(sent_msg, direction="TX")

    def _on_periodic_stop(self, row_key: str):
        if self.periodic_manager is not None:
            try:
                self.periodic_manager.stop(row_key)
            except Exception as exc:  # noqa: BLE001
                self._log_event("HATA", f"Periyodik gönderim durdurulamadı: {exc}")
                return
            self._log_event("GÖNDERİM", "Periyodik gönderim durduruldu")

    # ---- CCP (kalibrasyon) ------------------------------------------------
    def _on_ccp_connect(self, cro_id: int, dto_id: int, station_address: int):
        """Manuel "CCP Bağlan": arka planda (geri çekilmeli) bağlanmayı başlatır; arayüz beklemez,
        durum CCP sekmesinde ve üst şeritteki çipte canlı görünür."""
        if not self.connection.is_connected:
            QMessageBox.warning(
                self, "CAN bağlantısı yok",
                "CCP bağlantısı kurmadan önce CAN Monitor sekmesinden CAN hattına bağlanın.")
            return
        self.ccp_session.start(cro_id, dto_id, station_address)
        self._log_event("CCP", f"CCP bağlanıyor (CRO=0x{cro_id:X}, DTO=0x{dto_id:X}, istasyon=0x{station_address:X})")

    def _auto_ccp_connect(self):
        """CAN bağlanınca otomatik CCP: sabit gecikme + tek deneme yerine arka planda geri çekilmeli
        sonsuz deneme (ECU henüz açılmamış/hazır değilse sürer; ECU gelince kendiliğinden bağlanır)."""
        if not self.connection.is_connected or self.ccp_session.state != IDLE:
            return
        try:
            cro_id, dto_id, station = self.ccp_tab.parsed_connection_params()
        except ValueError as exc:
            self._log_event("HATA", f"Otomatik CCP bağlantısı atlandı: {exc}")
            return
        self.ccp_session.start(cro_id, dto_id, station)

    def _drop_ccp_client(self):
        """CCP oturumunu bus'a HİÇ yazmadan bırakır (adaptör kopmuşken)."""
        was_active = self.ccp_session.state != IDLE
        self.ccp_session.stop(graceful=False)
        if was_active:
            self._log_event("CCP", "CCP bağlantısı düştü (CAN bağlantısı koptu)")
        self._apply_ccp_state(IDLE, "")

    def _on_ccp_disconnect(self):
        was_active = self.ccp_session.state != IDLE
        self.ccp_session.stop(graceful=True)
        if was_active:
            self._log_event("CCP", "CCP bağlantısı kesildi")
        self._apply_ccp_state(IDLE, "")

    def _on_ccp_events(self):
        """Arka plan CCP iş parçacığından gelen durum/günlük olaylarını arayüze uygular (100 ms)."""
        for ev in self.ccp_session.poll_events():
            if ev[0] == "state":
                self._apply_ccp_state(ev[1], ev[2])
            elif ev[0] == "log":
                self._log_event(ev[1], ev[2])
        self._update_ccp_chip()

    def _apply_ccp_state(self, state: str, info: str):
        online = state == ONLINE
        self.ccp_tab.set_session_state(state, self.ccp_session.status_text())
        self.watch_tab.set_live_state(state, self.ccp_session.status_text())
        self.watch_tab.set_connected(state in (ONLINE, LOST))
        self.map_editor_tab.set_online(online)
        self._panel_conn_state()
        self._update_ccp_chip()

    def _update_ccp_chip(self):
        if not hasattr(self, "ccp_chip"):
            return
        st = self.ccp_session.state
        text = self.ccp_session.status_text()
        if self.ccp_chip.text() != text or self.ccp_chip.property("state") != st:
            self.ccp_chip.setText(text)
            self.ccp_chip.setProperty("state", st)
            self.ccp_chip.style().unpolish(self.ccp_chip)
            self.ccp_chip.style().polish(self.ccp_chip)

    def _on_ccp_read(self):
        if self.ccp_client is None:
            return
        selected = self.ccp_tab.selected_object()
        if selected is None:
            return
        _, obj = selected
        address = getattr(obj, "address", None)
        if address is None:
            self.ccp_tab.set_write_result(
                False, "Bu nesnenin ECU adresi A2L dosyasında tanımlı değil; okunamaz."
            )
            return
        try:
            reading = ccp_codec.read_value(self.ccp_reader, obj)
            raw_value, phys_value = reading.raw, reading.phys
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError) as exc:
            self.ccp_tab.set_read_value("-")
            self.ccp_tab.set_write_result(False, f"Okuma hatası: {exc}")
            return

        unit = f" {obj.unit}" if obj.unit else ""
        display = f"{phys_value:.4g}" if isinstance(phys_value, float) else str(phys_value)
        self.ccp_tab.set_read_value(f"{display}{unit}  (ham: {raw_value})")

    def _on_ccp_write(self, persistent: bool):
        # persistent=False -> RAM (geçici) yazma; persistent=True -> KALICI
        # (flaş) yazma. CCPTab yalnızca güçlü bir onay diyaloğundan sonra
        # persistent=True gönderir (bkz. app/ui/ccp_tab.py _on_write_flash_clicked).
        if self.ccp_client is None:
            return
        if persistent:
            if not can_write_flash(self.current_role):
                self.ccp_tab.set_write_result(
                    False, "Yetki yok: FLAŞ yazmak için Yönetici rolü gerekir "
                           "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin)."
                )
                return
        elif not can_write_calibration(self.current_role):
            self.ccp_tab.set_write_result(
                False, "Yetki yok: kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir "
                       "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin)."
            )
            return
        selected = self.ccp_tab.selected_object()
        if selected is None or selected[0] != "characteristic":
            return
        _, obj = selected
        if obj.read_only:
            return
        address = getattr(obj, "address", None)
        if address is None:
            self.ccp_tab.set_write_result(
                False, "Bu nesnenin ECU adresi A2L dosyasında tanımlı değil; yazılamaz."
            )
            return

        text = self.ccp_tab.entered_value_text()
        try:
            phys_value = float(text.replace(",", "."))
        except ValueError:
            self.ccp_tab.set_write_result(False, f"Geçersiz sayı: {text!r}")
            return

        # RAM'e yazarken ONAY SORULMAZ (kullanıcı isteği: "RAM'e Yaz'a tıklayınca
        # direkt yazsın"). Güvenlik katmanları yine de geçerli: rol kontrolü,
        # salt-okunur nesne kontrolü ve her yazımın geçmişe kaydı (geri alınabilir).
        # FLAŞ (kalıcı) yazma için güçlü onay CCPTab'da (_on_write_flash_clicked)
        # alınmaya DEVAM eder.

        # Geri alınabilir bir revizyon geçmişi tutabilmek için yazmadan
        # önce mevcut (eski) değeri en iyi çaba ile okuyoruz; okunamazsa
        # geçmişte "eski değer bilinmiyor" olarak görünür, yazma yine de
        # devam eder.
        old_phys = None
        try:
            old_phys = ccp_codec.read_value(self.ccp_client, obj).phys
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError):
            old_phys = None

        try:
            # Doğrulama (sonlu, A2L min/max, READ_ONLY) + güvenli dönüşüm; yazma
            # sonrası geri okuma ile doğrulanır.
            raw_bytes = ccp_codec.encode_for_write(obj, phys_value)
            ext = getattr(obj, "address_extension", 0) or 0
            if persistent:
                self.ccp_client.write_flash_memory(address, raw_bytes, ext, verify=True)
            else:
                self.ccp_client.write_memory(address, raw_bytes, ext, verify=True)
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError) as exc:
            kind = "FLAŞ" if persistent else "RAM"
            self.ccp_tab.set_write_result(False, f"Yazma hatası ({kind}): {exc}")
            self._log_event("HATA", f"{obj.name} {kind} yazma hatası: {exc}")
            return

        kind_label = "FLAŞ, kalıcı" if persistent else "RAM, geçici"
        self.ccp_tab.set_write_result(True, f"Yazıldı ({kind_label}): {obj.name} = {phys_value}")
        self._log_event(
            "KALIBRASYON",
            f"{obj.name} = {phys_value} {obj.unit or ''} ({'FLAŞ' if persistent else 'RAM'}) yazıldı"
        )
        self.calibration_history.add(
            self.current_user, self.current_role.value, obj.name, old_phys, phys_value, obj.unit or "",
            persistent=persistent,
        )
        self.history_tab.refresh()

    # ---- Harita Editörü (CURVE/MAP/ARRAY okuma-yazma; çoklu tablo) ----------
    def _open_in_map_editor(self, characteristic):
        """CCP sekmesindeki dizi/tablo nesnesini Harita Editörü'nde açar."""
        self.map_editor_tab.open_characteristic(characteristic)
        inner = self.kalibrasyon_tab.inner_tabs
        inner.setCurrentWidget(self.map_editor_tab)

    def _require_ccp(self, action_text: str) -> bool:
        if self.ccp_client is None:
            QMessageBox.warning(
                self, "CCP bağlantısı yok",
                f"{action_text} önce Kalibrasyon (CCP) sekmesinden CCP bağlantısı kurun."
            )
            return False
        return True

    def _read_map_doc(self, doc) -> bool:
        characteristic = doc.characteristic
        if not characteristic.address:
            doc.set_error("Bu nesnenin ECU adresi A2L dosyasında tanımlı değil.")
            return False
        try:
            grid = ccp_mapio.read_grid(self.ccp_client, characteristic)
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError) as exc:
            doc.set_error(f"Okuma hatası: {exc}")
            return False
        doc.set_grid_from_ecu(grid)
        return True

    @staticmethod
    def _count_changed_cells(old_grid, new_grid) -> int:
        if old_grid is None:
            return sum(len(r) for r in new_grid)
        changed = 0
        for r, row in enumerate(new_grid):
            for c, v in enumerate(row):
                try:
                    if abs(old_grid[r][c] - v) > 1e-9:
                        changed += 1
                except IndexError:
                    changed += 1
        return changed

    def _save_table_backup(self, characteristic, old_grid) -> str:
        """Tablo yazımından önceki ECU içeriğini data_dir()/tablo_yedekleri
        altına JSON olarak yazar (geri dönüş için). Başarısızsa '' döner."""
        import json
        import re
        import time as _time
        try:
            folder = os.path.join(data_path("tablo_yedekleri"))
            os.makedirs(folder, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]", "_", characteristic.name)
            fname = f"{safe}_{_time.strftime('%Y%m%d_%H%M%S')}.json"
            with open(os.path.join(folder, fname), "w", encoding="utf-8") as f:
                json.dump({"name": characteristic.name, "address": characteristic.address,
                           "unit": characteristic.unit, "grid": old_grid}, f, ensure_ascii=False)
            return fname
        except (OSError, TypeError, ValueError):
            return ""

    def _write_map_doc(self, doc) -> bool:
        """Tek bir tablo dokümanını ECU RAM'ine yazar. ONAY SORULMAZ
        (kullanıcı isteği); rol kontrolü ve geçmiş kaydı yine yapılır."""
        characteristic = doc.characteristic
        if not doc.is_writable():
            doc.set_write_result(False, "Tabloda boş/geçersiz hücre var; önce tüm hücreleri doldurun.")
            return False
        try:
            grid = doc.current_grid()
            # write_grid: önce doğrular, ECU'daki mevcut içeriği anlık görüntü
            # alır, yazar, geri okuyup doğrular; hata olursa eski içeriği geri
            # yazar. Yazmadan ÖNCEKİ gerçek ECU içeriğini döndürür.
            old_grid = ccp_mapio.write_grid(self.ccp_client, characteristic, grid)
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError, RuntimeError) as exc:
            doc.set_write_result(False, f"Yazma hatası: {exc}")
            self._log_event("HATA", f"{characteristic.name} tablo yazma hatası: {exc}")
            return False
        backup = self._save_table_backup(characteristic, old_grid)
        rows, cols = len(grid), len(grid[0]) if grid else 0
        changed = self._count_changed_cells(old_grid, grid)
        doc.set_write_result(True, f"Yazıldı (RAM, geçici): {characteristic.name} — {changed} hücre değişti")
        self._log_event(
            "KALIBRASYON",
            f"Tablo yazıldı (RAM): {characteristic.name} [{rows}x{cols}], {changed} hücre değişti"
        )
        self.calibration_history.add(
            self.current_user, self.current_role.value,
            f"{characteristic.name} [tablo {rows}×{cols}]", None, 0.0, characteristic.unit or "",
            persistent=False,
            detail=f"{rows}×{cols} tablo yazıldı, {changed} hücre değişti"
                   + (f"; önceki içerik yedeği: {backup}" if backup else ""),
        )
        self.history_tab.refresh()
        return True

    def _on_map_read(self):
        doc = self.map_editor_tab.current_document()
        if doc is None:
            return
        if not self._require_ccp("Harita okumadan"):
            return
        self._read_map_doc(doc)

    def _on_map_write(self):
        doc = self.map_editor_tab.current_document()
        if doc is None:
            return
        if not self._require_ccp("Harita yazmadan"):
            return
        if not can_write_calibration(self.current_role):
            doc.set_write_result(False, "Yetki yok: harita yazmak için Mühendis veya Yönetici rolü gerekir.")
            return
        self._write_map_doc(doc)

    def _on_map_read_all(self):
        docs = self.map_editor_tab.documents()
        if not docs or not self._require_ccp("Tabloları okumadan"):
            return
        ok = sum(1 for d in docs if self._read_map_doc(d))
        self._log_event("KALIBRASYON", f"{ok}/{len(docs)} tablo ECU'dan okundu")

    def _on_map_write_all(self):
        docs = self.map_editor_tab.documents()
        if not docs or not self._require_ccp("Tabloları yazmadan"):
            return
        if not can_write_calibration(self.current_role):
            for d in docs:
                d.set_write_result(False, "Yetki yok: harita yazmak için Mühendis veya Yönetici rolü gerekir.")
            return
        written = skipped = failed = 0
        for d in docs:
            if not d.is_modified():
                skipped += 1
                continue
            if self._write_map_doc(d):
                written += 1
            else:
                failed += 1
        self._log_event(
            "KALIBRASYON",
            f"Toplu tablo yazma: {written} yazıldı, {skipped} değişmediği için atlandı, {failed} başarısız"
        )

    # ---- Parametre Listesi (çoklu parametre izleme/yazma) --------------------
    def _read_phys_best_effort(self, e):
        try:
            return ccp_codec.read_value(self.ccp_client, e).phys
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError):
            return None

    def _on_watch_read(self):
        """Parametre Listesi canlı okuma: değerler arka plan CCP iş parçacığının önbelleğinden
        gelir (arayüz hiç beklemez); ECU yokken satırlar anında 'ECU cevap vermiyor' gösterir ve
        ECU geri gelince değerler kendiliğinden akmaya başlar."""
        if self.ccp_client is None:
            return
        for row, e in enumerate(self.watch_tab.entries()):
            if not getattr(e, "resolved", True) or not e.datatype:
                continue
            try:
                reading = ccp_codec.read_value(self.ccp_reader, e)
            except ccp_protocol.CCPTimeoutError as exc:
                self.watch_tab.set_row_error(row, str(exc) or "ECU cevap vermedi")
                continue
            except (ccp_protocol.CCPError, ccp_codec.UnknownDatatypeError, ValueError) as exc:
                self.watch_tab.set_row_error(row, str(exc))
                continue
            except Exception as exc:
                self.watch_tab.set_row_error(row, f"Okuma hatası: {exc}")
                continue
            self.watch_tab.set_row_value(row, reading.raw_bytes, reading.phys)    # Parametre Listesi HAM BAYT bekler

    def _on_watch_write(self, rows: list):
        """Parametre Listesi: Değer hücresine Enter ile onaylanan değerleri RAM'e yazar (anında).
        Yazılamayanlarda bekleyen metin atılır (hücre canlı değere döner); yazılanlar ECU'dan geri
        okunarak doğrulanır (bkz. WatchTab.commit_written / set_row_value)."""
        if self.ccp_client is None:
            self.watch_tab.discard_pending(rows)
            self.watch_tab.set_write_result(False, "CCP bağlı değil; değer yazılamadı (bağlantı kurulunca tekrar deneyin).")
            return
        if not can_write_calibration(self.current_role):
            self.watch_tab.discard_pending(rows)
            self.watch_tab.set_write_result(
                False, "Yetki yok: kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir "
                       "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
            return
        entries = self.watch_tab.entries()
        done = 0
        problems: list[str] = []
        failed_rows: list[int] = []
        for row in rows:
            if row < 0 or row >= len(entries):
                continue
            e = entries[row]
            text = self.watch_tab.pending_text(row)
            if text is None or e.read_only or not getattr(e, "resolved", True):
                continue
            try:
                phys = parse_value_text(text)
            except ValueError:
                problems.append(f"{e.name}: geçersiz sayı ({text!r})")
                failed_rows.append(row)
                continue
            old_phys = self._read_phys_best_effort(e)
            try:
                # doğrulama (sonlu, tür aralığı, A2L min/max, READ_ONLY) + güvenli dönüşüm
                raw_bytes = ccp_codec.encode_for_write(e, phys)
                self.ccp_client.write_memory(e.address, raw_bytes, e.address_extension or 0)
            except ccp_protocol.CCPTimeoutError as exc:
                problems.append(f"{e.name}: {str(exc) or 'ECU cevap vermedi'}")
                self._log_event("HATA", f"{e.name} RAM yazma: ECU cevap vermedi")
                failed_rows.append(row)
                continue
            except (ccp_protocol.CCPError, ccp_codec.UnknownDatatypeError, ValueError) as exc:
                problems.append(f"{e.name}: {exc}")
                self._log_event("HATA", f"{e.name} RAM yazma hatası: {exc}")
                failed_rows.append(row)
                continue
            self.watch_tab.commit_written(row, phys)
            self._log_event("KALIBRASYON", f"{e.name} = {phys} {e.unit or ''} (RAM, Parametre Listesi) yazıldı")
            self.calibration_history.add(
                self.current_user, self.current_role.value, e.name, old_phys, phys, e.unit or "",
                persistent=False,
            )
            done += 1
        self.watch_tab.discard_pending(failed_rows)
        self.history_tab.refresh()
        if problems:
            self.watch_tab.set_write_result(
                False, f"{done} parametre yazıldı; sorunlar: " + "; ".join(problems))
        elif done:
            self.watch_tab.set_write_result(True, f"{done} parametre RAM'e yazıldı; ECU'dan doğrulanıyor…")

    # ---- Grafik (canlı Measurement çizimi) ---------------------------------
    def _iter_a2l_samples(self, names: list):
        """Verilen A2L ölçüm adlarını (önbellekten, beklemeden) okuyup ``(ad, ölçüm, Reading)``
        üretir. Okunamayanlar (A2L'de yok, adres yok, ECU cevap vermiyor, bilinmeyen veri tipi)
        sessizce atlanır; ayrıntılı hata gösterimi isteyenler (Ana Sayfa, Parametre Listesi)
        ``ccp_codec.read_value`` ile kendileri okur."""
        if self.ccp_client is None:
            return
        summary = self.a2l_tab.db.summary
        if summary is None:
            return
        by_name = summary.readable_by_name()
        for name in names:
            m = by_name.get(name)
            if m is None or m.address is None:
                continue
            try:
                reading = ccp_codec.read_value(self.ccp_reader, m)
            except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                    ccp_codec.UnknownDatatypeError, ValueError):
                continue
            yield name, m, reading

    # ---- Diagnostics --------------------------------------------------------
    def _on_diag_test_requested(self):
        if self.ccp_client is None:
            self.diagnostics_tab.set_test_result(False, "CCP bağlantısı yok.")
            return
        ok = self.ccp_client.test_connection()
        self.diagnostics_tab.set_test_result(
            ok, "ECU cevap veriyor." if ok else "ECU cevap vermiyor / bağlantı koptu."
        )

    def _on_diag_requested(self, service_number: int, params: bytes):
        if self.ccp_client is None:
            self.diagnostics_tab.set_diag_result("CCP bağlantısı yok.", ok=False)
            return
        if not can_run_diagnostics(self.current_role):
            self.diagnostics_tab.set_diag_result(
                "Yetki yok: DIAG_SERVICE çalıştırmak için Mühendis veya Yönetici rolü gerekir.", ok=False
            )
            return
        try:
            data = self.ccp_client.diag_service(service_number, params)
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError) as exc:
            self.diagnostics_tab.set_diag_result(f"Hata: {exc}", ok=False)
            self.diagnostics_tab.add_diag_log(service_number, params, None, str(exc))
            self._log_event("HATA", f"DIAG_SERVICE 0x{service_number:04X} başarısız: {exc}")
            return
        self.diagnostics_tab.set_diag_result(f"Cevap verisi (5 bayt): {data.hex(' ')}")
        self.diagnostics_tab.add_diag_log(service_number, params, data)
        self._log_event("BILGI", f"DIAG_SERVICE 0x{service_number:04X} params={params.hex(' ') or '-'} cevap={data.hex(' ')}")

    # ---- Kalibrasyon Geçmişi (revizyon geri alma) --------------------------
    def _on_history_revert(self, index: int):
        if self.ccp_client is None:
            QMessageBox.warning(self, "CCP bağlantısı yok", "Geri yazmak için önce CCP bağlantısı kurun.")
            return
        entries = self.calibration_history.entries
        if index < 0 or index >= len(entries):
            return
        entry = entries[index]
        # FLAŞ kaydı FLAŞ'a, RAM kaydı RAM'e geri yazılır — ve flaş geri
        # alma RAM'den daha riskli olduğu için daha yüksek yetki ister.
        required_ok = can_write_flash(self.current_role) if entry.persistent else can_write_calibration(self.current_role)
        if not required_ok:
            role_needed = "Yönetici" if entry.persistent else "Mühendis veya Yönetici"
            QMessageBox.warning(self, "Yetki yok", f"Bu işlem için {role_needed} rolü gerekir.")
            return
        if getattr(entry, "detail", ""):
            QMessageBox.information(
                self, "Tablo kaydı",
                "Bu kayıt bir tablo (harita/dizi) yazımıdır; tek değere geri alınamaz. "
                "Tabloyu ECU'dan okuyup istediğiniz değerlerle tekrar yazabilirsiniz."
            )
            return
        if entry.old_value is None:
            QMessageBox.warning(
                self, "Eski değer bilinmiyor",
                "Bu kayıt için yazmadan önceki değer okunamamıştı, geri yazılamaz."
            )
            return
        summary = self.a2l_tab.db.summary
        if summary is None:
            return
        obj = next((c for c in summary.characteristics if c.name == entry.object_name), None)
        if obj is None:
            QMessageBox.warning(self, "Nesne bulunamadı", "Bu Characteristic artık yüklü A2L'de yok.")
            return
        if getattr(obj, "address", None) is None:
            QMessageBox.warning(self, "Adres yok", "Bu nesnenin ECU adresi A2L'de tanımlı değil; geri yazılamaz.")
            return

        kind_label = "FLAŞ (kalıcı)" if entry.persistent else "RAM (geçici)"
        # Onay yalnızca KALICI (flaş) geri alma için sorulur; RAM geri alma
        # doğrudan yapılır (kullanıcı isteği: RAM'e yazarken onay istenmesin).
        if entry.persistent:
            confirm = QMessageBox.question(
                self, "Eski değere geri yazılsın mı?",
                f"{obj.name}, {entry.new_value} yerine eski değeri {entry.old_value} ile "
                f"{kind_label} olarak geri yazılacak. Devam edilsin mi?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        try:
            raw_bytes = ccp_codec.encode_for_write(obj, entry.old_value)
            ext = obj.address_extension or 0
            if entry.persistent:
                self.ccp_client.write_flash_memory(obj.address, raw_bytes, ext, verify=True)
            else:
                self.ccp_client.write_memory(obj.address, raw_bytes, ext, verify=True)
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError) as exc:
            QMessageBox.critical(self, "Geri yazma hatası", str(exc))
            self._log_event("HATA", f"{obj.name} geri yazma hatası ({kind_label}): {exc}")
            return

        self.calibration_history.add(
            self.current_user, self.current_role.value, obj.name,
            entry.new_value, entry.old_value, obj.unit or "",
            persistent=entry.persistent,
        )
        self.history_tab.refresh()
        self._log_event("KALIBRASYON", f"{obj.name} eski değerine geri yazıldı: {entry.old_value}")

    # ---- Ana Sayfa (Dashboard) -----------------------------------------------
    # Her değişken bir Binding ile tanımlıdır: CAN (DBC mesaj.sinyal) ya da A2L (CCP).
    _can_tx_values: dict = {}

    def _write_binding(self, binding: Binding, value: float, label: str, merge: bool = True,
                       safety: bool = False) -> bool:
        """Bir Binding'e değer yazar (DashboardTab.writer). Başarısızlıkta kullanıcıyı
        bilgilendirir ve False döner. ``merge``: aynı CAN mesajına daha önce yazılan
        diğer sinyallerin son değerleri korunur (değer + anahtar aynı mesajda olabilir).
        ``safety``: güvenlik komutu (Acil Durdurma): A2L min/max + READ_ONLY ve DBC min/max denetimi
        komutu ENGELLEMEZ (sınır dışıysa günlüğe not düşülür); değer veri tipine / bit genişliğine
        sığmıyorsa yine gönderilmez."""
        if not binding.is_set:
            QMessageBox.warning(self, "Eşleşme yok", f"{label} için eşleşme tanımlı değil (⚙ Eşleşmeler).")
            return False
        if binding.source == SOURCE_A2L:
            return self._write_a2l(binding, value, label, safety)
        return self._write_can(binding, value, label, merge, safety)

    def _write_can(self, binding: Binding, value: float, label: str, merge: bool = True,
                   safety: bool = False) -> bool:
        if not self.connection.is_connected:
            QMessageBox.warning(self, "CAN bağlantısı yok",
                                f"{label} göndermeden önce CAN hattına bağlanın.")
            return False
        vals = self._can_tx_values.setdefault(binding.message, {}) if merge else {}
        vals[binding.signal] = value
        try:
            if safety:
                try:
                    self.transmit_tab.dbc.encode(binding.message, dict(vals))
                except ValueError as exc:
                    # Sınır (min/max) dışı olabilir: güvenlik komutu engellenmez. Gerçekten kodlanamıyorsa
                    # (bit genişliği) aşağıdaki strict=False kodlama da hata verir ve gönderilmez.
                    self._log_event("MOTOR", f"{label}: DBC sınır denetimi güvenlik komutu olduğu için atlandı ({exc})")
            can_id, data, extended = self.transmit_tab.dbc.encode(binding.message, dict(vals), strict=not safety)
            self.connection.send(can_id, data, extended)
        except Exception as exc:  # cantools/python-can çeşitli hata tipleri fırlatabilir
            hint = ("\n\nDeğer sinyalin bit genişliğine sığmıyor: yapılandırılmış komut değerini "
                    "(⚙ Eşleşmeler) düzeltin.") if safety else ""
            QMessageBox.critical(self, f"{label} gönderilemedi", f"{exc}{hint}")
            self._log_event("HATA", f"{label} gönderilemedi: {exc}")
            return False
        sent_msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=extended,
                                timestamp=time.time())
        self.monitor_tab.add_message(sent_msg, direction="TX")
        self._log_event("EYLEYICI", f"{label} [CAN {binding.message}.{binding.signal}] = {value:g} "
                                    f"({self.current_user}/{self.current_role.value})")
        return True

    def _a2l_info(self, name: str):
        summary = self.a2l_tab.db.summary
        if summary is None:
            return None
        for coll in (summary.measurements, summary.characteristics):
            for m in coll:
                if m.name == name:
                    return m
        return None

    def _write_a2l(self, binding: Binding, value: float, label: str, safety: bool = False) -> bool:
        if self.ccp_client is None:
            QMessageBox.warning(self, "CCP bağlı değil",
                                f"{label} A2L üzerinden yazılmadan önce CCP bağlantısı kurun.")
            return False
        info = self._a2l_info(binding.a2l_name)
        try:
            if info is None:
                raise ValueError(f"A2L'de '{binding.a2l_name}' bulunamadı")
            if info.address is None:
                raise ValueError(f"'{binding.a2l_name}' için ECU adresi yok")
            if safety:
                try:
                    ccp_codec.validate_write(info, value)
                except ccp_codec.WriteValidationError as exc:
                    self._log_event("MOTOR", f"{label}: A2L sınır/READ_ONLY denetimi güvenlik komutu olduğu için "
                                             f"atlandı ({exc})")
            # 0 = kapat/güvenli yön: A2L alt sınırı kapatmayı engellemesin (yine de sonlu/tür kontrolü var).
            # Güvenlik komutunda (safety) değer ne olursa olsun sınır/READ_ONLY denetimi atlanır.
            cpanel.ccp_write_value(self.ccp_client, info, value,
                                   enforce_limits=(not safety and float(value) != 0.0))
        except Exception as exc:
            hint = ("\n\nDeğer veri tipine sığmıyor: yapılandırılmış komut değerini "
                    "(⚙ Eşleşmeler) düzeltin.") if safety else ""
            QMessageBox.critical(self, f"{label} yazılamadı", f"{exc}{hint}")
            self._log_event("HATA", f"{label} A2L yazılamadı: {exc}")
            return False
        self._log_event("EYLEYICI", f"{label} [A2L {binding.a2l_name}] = {value:g} "
                                    f"({self.current_user}/{self.current_role.value})")
        return True

    def _send_motor_command(self, command_name: str, cmd, safety: bool = False) -> bool:
        if not cmd.binding.is_set:
            self._log_event("HATA", f"{command_name} GÖNDERİLEMEDİ: eşleme tanımlı değil")
            return False
        # Komutlar tek sinyallik darbedir: diğer sinyallerin eski değerleri taşınmaz.
        ok = self._write_binding(cmd.binding, cmd.value, command_name, merge=False, safety=safety)
        if ok:
            self._log_event("MOTOR", f"{command_name} gönderildi ({cmd.binding.text}={cmd.value:g})")
        else:
            self._log_event("HATA", f"{command_name} GÖNDERİLEMEDİ ({cmd.binding.text})")
        return ok

    def _on_motor_start(self):
        self._send_motor_command("Motor Start", self.dashboard_tab.config.motor_start)

    def _on_motor_stop(self):
        # Durdurma "güvenli yön" komutudur: A2L/DBC sınırı ya da READ_ONLY yüzünden reddedilmez
        # (Motor Start sınırda kalır; bkz. _write_binding safety).
        self._send_motor_command("Motor Stop", self.dashboard_tab.config.motor_stop, safety=True)

    def _on_estop(self):
        cmd = self.dashboard_tab.config.estop
        if not cmd.binding.is_set:
            # Sessizce dönme: operatör komutun GİTMEDİĞİNİ açıkça görmeli.
            self._log_event("HATA", "ACİL DURDURMA GÖNDERİLEMEDİ: eşleme tanımlı değil")
            QMessageBox.critical(
                self, "ACİL DURDURMA GÖNDERİLEMEDİ",
                "Acil Durdurma için DBC sinyali veya A2L değişkeni TANIMLI DEĞİL; komut ECU'ya gitmedi.\n\n"
                "Motoru manuel / fiziksel olarak hemen durdurun. Sonra ⚙ Eşleşmeler penceresinden "
                "Acil Durdurma eşlemesini tanımlayın.")
            return
        # Güvenlik komutu: A2L/DBC sınırı ya da READ_ONLY yüzünden reddedilmez (bkz. _write_binding).
        self._send_motor_command("ACİL DURDURMA", cmd, safety=True)

    def _on_dashboard_config_saved(self, cfg):
        if not self.dashboard_config_store.save(cfg):
            self._log_event("HATA", "Eşleşmeler DİSKE YAZILAMADI (bellekte geçerli, yeniden açınca kaybolur).")
            QMessageBox.warning(self, "Ayarlar kaydedilemedi",
                                "Eşleşmeler diske yazılamadı; program kapanınca kaybolacak.")
        self._rebuild_dash_can_map()
        self._log_event("AYAR", "Eşleşmeler (CAN/A2L) kaydedildi.")

    def _on_dashboard_sources_changed(self, *_):
        summary = self.a2l_tab.db.summary
        self.dashboard_tab.set_sources(self.transmit_tab.dbc, summary)
        self._rebuild_dash_can_map()

    # ---- Ana Sayfa: CAN'dan (DBC) sensör okuma --------------------------------
    _dash_can: dict = {}

    def _rebuild_dash_can_map(self):
        """CAN kaynaklı sensör değer/arıza sinyallerini frame id'ye göre indeksler."""
        self._dash_can = {}
        cdb = getattr(self.transmit_tab.dbc, "_db", None)
        if cdb is None:
            return
        cfg = self.dashboard_tab.config
        for key in GAUGE_KEYS:
            smap = cfg.sensor_map(key)
            for role, b in (("value", smap.value), ("fault", smap.fault)):
                if b.source != SOURCE_CAN or not b.is_set:
                    continue
                try:
                    msg = cdb.get_message_by_name(b.message)
                except KeyError:
                    continue
                ent = self._dash_can.setdefault(msg.frame_id, {"msg": msg, "sigs": []})
                ent["sigs"].append((b.signal, role, key))

    def _dash_on_can_frame(self, can_id: int, data: bytes):
        ent = self._dash_can.get(can_id)
        if ent is None:
            return
        try:
            vals = ent["msg"].decode(bytes(data), decode_choices=False)
        except Exception:
            return
        dt = self.dashboard_tab
        for sig, role, key in ent["sigs"]:
            v = vals.get(sig)
            if not isinstance(v, (int, float)):
                continue
            if role == "value":
                dt.set_gauge_value(key, float(v))
            else:
                dt.set_sensor_fault(key, "Sensör arızası" if v else None)

    def _sync_workspace_a2l(self):
        summary = self.a2l_tab.db.summary
        self.workspace_tab.set_a2l_measurements(summary.readable() if summary is not None else [])

    def _on_workspace_tick(self, names: list):
        """Çalışma Alanı'nda seçili A2L ölçümlerini CCP ile (arka planda) okuyup hub'a yazar."""
        for name, _m, reading in self._iter_a2l_samples(names):
            self.workspace_tab.push(f"a2l:{name}", reading.phys)

    def _sync_dashboard_measurements(self):
        summary = self.a2l_tab.db.summary
        self.dashboard_tab.set_measurements(summary.readable() if summary is not None else [])

    # ---- Ana Sayfa: A2L'den (CCP) okuma --------------------------------------
    def _on_dashboard_tick(self, names: list):
        dt = self.dashboard_tab
        cfg = dt.config
        a2l_gauges = cfg.gauge_a2l_map()                    # gösterge -> A2L adı
        if self.ccp_client is None:
            reason = self.ccp_session.not_ready_reason()
            for key in a2l_gauges:
                dt.set_gauge_error(key, reason)
            return
        summary = self.a2l_tab.db.summary
        if summary is None:
            for key in a2l_gauges:
                dt.set_gauge_error(key, "A2L yüklü değil")
            return

        by_name = summary.readable_by_name()
        roles: dict[str, list] = {}                          # A2L adı -> [(rol, gösterge)]
        for key, name in a2l_gauges.items():
            roles.setdefault(name, []).append(("value", key))
            m = by_name.get(name)
            if m is not None:
                dt.set_gauge_limits(key, m.minimum, m.maximum)
        for key in GAUGE_KEYS:
            f = cfg.sensor_map(key).fault
            if f.source == SOURCE_A2L and f.a2l_name.strip():
                roles.setdefault(f.a2l_name.strip(), []).append(("fault", key))
        graph_names = set(dt.graph_measurement_names())

        for name in names:
            targets = roles.get(name, [])
            graph_wanted = name in graph_names
            if not targets and not graph_wanted:
                continue
            m = by_name.get(name)

            def fail(reason: str, targets=targets):
                for role, key in targets:
                    if role == "value":
                        dt.set_gauge_error(key, reason)

            if m is None:
                fail(f"A2L'de '{name}' yok")
                continue
            if m.address is None:
                fail("ECU adresi yok")
                continue
            try:
                reading = ccp_codec.read_value(self.ccp_reader, m)
                raw_value, phys_value = reading.raw, reading.phys
            except ccp_protocol.CCPTimeoutError as exc:
                fail(str(exc) or "ECU cevap vermedi")
                continue
            except ccp_protocol.CCPError as exc:
                fail(f"CCP hatası: {exc}")
                continue
            except ccp_codec.UnknownDatatypeError:
                fail(f"Veri tipi desteklenmiyor ({m.datatype})")
                continue
            except ValueError as exc:
                fail(str(exc))
                continue
            if graph_wanted and isinstance(phys_value, (int, float)):
                dt.add_measurement_sample(name, float(phys_value))
            for role, key in targets:
                if role == "value":
                    dt.set_gauge_value(key, float(phys_value))
                    dt.set_gauge_debug(
                        key, f"A2L: {name}  @0x{m.address:X}  {m.datatype}  "
                             f"{m.byte_order or 'bayt sırası: varsayılan (MSB_FIRST)'}\n"
                             f"ham = {raw_value}   →   fiziksel = {float(phys_value):.6g} {m.unit or ''}"
                             f"   [{getattr(m.compu_method, 'conversionType', 'dönüşüm yok')}]")
                else:
                    dt.set_sensor_fault(key, "Sensör arızası" if phys_value else None)

    # ---- Kullanıcı / Profil -------------------------------------------------
    # ---- Kontrol Paneli ---------------------------------------------------
    def _panel_send(self, can_id: int, data: bytes, extended: bool):
        self.connection.send(can_id, data, extended)

    def _panel_conn_state(self):
        self.control_panel_tab.set_connection_state(
            self.connection.is_connected, self.ccp_client is not None, self._conn_lost)
        self.performance_tab.set_connection_state(
            self.connection.is_connected, self.ccp_client is not None, self._conn_lost)

    def _panel_sources_changed(self):
        self.control_panel_tab.refresh_sources(self.transmit_tab.dbc, self.a2l_tab.db)
        self.dashboard_tab.sim_inputs.refresh_sources(self.transmit_tab.dbc)
        self.performance_tab.refresh_sources(self.transmit_tab.dbc, self.a2l_tab.db)
        self._push_flight()

    def _push_flight(self):
        vals = self.dashboard_tab.sim_inputs.values()
        self.performance_tab.set_flight({k: v for k, v in vals.items() if k in self._sim_sent})

    def _sync_sim_inputs(self):
        """Kontrol Paneli'nden gönderilen değerleri Ana Sayfa girişlerine yansıtır."""
        panel = self.dashboard_tab.sim_inputs
        vals = {}
        for d in INPUT_DEFS:
            m = panel.mapped(d.key)
            if m is None:
                continue
            cur = self.tx_scheduler.values_of(m[0])
            if m[1] in cur:
                vals[d.key] = cur[m[1]]
        if vals:
            panel.set_values(vals)
            self._sim_sent.update(vals)
            self._push_flight()

    def _on_sim_inputs(self, values: dict):
        panel = self.dashboard_tab.sim_inputs
        if not can_override_actuator(self.current_role):
            panel.set_status("Yetki yok: Mühendis veya Yönetici rolü gerekir.", False)
            return
        if not self.connection.is_connected:
            panel.set_status("CAN bağlı değil: değerler gönderilemedi.", False)
            return
        by_msg: dict[str, dict] = {}
        unmapped = []
        for key, v in values.items():
            m = panel.mapped(key)
            if m is None:
                unmapped.append(key)
                continue
            by_msg.setdefault(m[0], {})[m[1]] = v
        errors = []
        for msg, vals in by_msg.items():
            try:
                self.tx_scheduler.set_values(msg, vals, None, start=not self._panel_paused)
                for sig, v in vals.items():
                    self.control_panel_tab.set_external_applied(msg, sig, v)
            except Exception as exc:
                errors.append(f"{msg}: {exc}")
        sent = sum(len(v) for v in by_msg.values()) - len(errors)
        panel.set_sent([k for k in values if k not in unmapped], ok=not errors)
        if not errors:
            self._sim_sent.update(k for k in values if k not in unmapped)
        if errors:
            panel.set_status("Gönderilemedi: " + "; ".join(errors), False)
        else:
            txt = f"{sent} değer gönderildi."
            if unmapped:
                txt += f" {len(unmapped)} giriş DBC'ye bağlı olmadığı için atlandı."
            panel.set_status(txt, not unmapped)
            self._log_event("SIMÜLASYON", "Giriş gönderildi: " + ", ".join(
                f"{k}={v:g}" for k, v in values.items() if k not in unmapped))
        self._push_flight()
        self._panel_tx_state()

    def _on_perf_poll(self):
        pt = self.performance_tab
        if self.ccp_client is None:
            return
        for key, info in pt.ccp_poll_targets():
            try:
                pt.set_ccp_value(key, cpanel.ccp_read_value(self.ccp_reader, info))
            except ccp_protocol.CCPTimeoutError:
                pt.set_ccp_error(key, "ECU cevap vermedi")
                continue
            except Exception as exc:
                pt.set_ccp_error(key, str(exc))

    def _panel_tx_state(self):
        self.control_panel_tab.set_tx_running(
            set(self.tx_scheduler.running_messages()), paused=self._panel_paused)

    _panel_paused = False

    def _on_panel_tx_failed(self, message: str, error: str):
        self._log_event("HATA", f"Kontrol Paneli: {message} gönderilemiyor ({error}); hat düzelince "
                                "otomatik yeniden denenecek")
        self.control_panel_tab._set_status(
            f"{message} gönderilemiyor: {error} — hat düzelince otomatik sürecek", False)

    def _on_panel_tx_recovered(self, message: str):
        self._log_event("BAGLANTI", f"Kontrol Paneli: {message} gönderimi yeniden başladı")
        self.control_panel_tab._set_status(f"{message} gönderimi yeniden başladı", True)

    def _on_panel_tx_toggle(self, stop: bool):
        if stop:
            self.tx_scheduler.stop_all()
            self._panel_paused = True
        else:
            self._panel_paused = False
            if self.connection.is_connected:
                self.tx_scheduler.resume_all()
        self._log_event("KONTROL PANELİ", "Uçak girişi gönderimi " + ("durduruldu" if stop else "başlatıldı"))
        self._panel_tx_state()

    def _on_panel_apply(self, changes: dict):
        panel = self.control_panel_tab
        results = []
        if not can_override_actuator(self.current_role):
            panel._set_status("Yetki yok: Mühendis veya Yönetici rolü gerekir.", False)
            return
        can_items = changes.get("can", {})
        if can_items and not self.connection.is_connected:
            panel._set_status("CAN bağlı değil: uçak girişleri gönderilemedi.", False)
            can_items = {}
            changes = dict(changes, can={})
        for msg, vals in can_items.items():
            try:
                self.tx_scheduler.set_values(msg, vals, changes.get("cycles", {}).get(msg),
                                             start=not self._panel_paused)
                ok, err = True, ""
            except Exception as exc:
                ok, err = False, str(exc)
            for sig in vals:
                key = next((s.key for s in panel._catalog if s.message == msg and s.signal == sig), None)
                if key:
                    results.append({"key": key, "field": "value", "ok": ok, "error": err})
        ccp_items = changes.get("ccp", [])
        failed_keys = set()
        for it in ccp_items:
            if self.ccp_client is None:
                results.append({"key": it["key"], "field": it["field"], "ok": False, "error": "CCP bağlı değil"})
                continue
            if it["key"] in failed_keys and it["field"] == "enable":
                results.append({"key": it["key"], "field": "enable", "ok": False,
                                "error": "değer yazılamadığı için bayrak açılmadı"})
                continue
            try:
                cpanel.ccp_write_value(self.ccp_client, it["info"], it["value"])
                results.append({"key": it["key"], "field": it["field"], "ok": True, "error": ""})
            except Exception as exc:
                failed_keys.add(it["key"])
                results.append({"key": it["key"], "field": it["field"], "ok": False, "error": str(exc)})
        okn = sum(1 for r in results if r["ok"])
        self._log_event("KONTROL PANELİ", f"Uygula: {okn}/{len(results)} değişiklik başarılı")
        panel.apply_finished(results)
        self._sync_sim_inputs()
        self._panel_tx_state()

    def _on_panel_poll(self):
        panel = self.control_panel_tab
        if self.ccp_client is None:
            return
        for key, kind, info in panel.ccp_poll_targets():
            try:
                panel.set_ccp_value(key, kind, cpanel.ccp_read_value(self.ccp_reader, info))
            except ccp_protocol.CCPTimeoutError:
                panel.set_ccp_error(key, "ECU cevap vermedi")
                break
            except Exception as exc:
                panel.set_ccp_error(key, str(exc))

    def _on_panel_kill_overrides(self, infos: list):
        panel = self.control_panel_tab
        if self.ccp_client is None:
            panel._set_status("CCP bağlı değil: override kapatılamadı.", False)
            return
        # Override'ları KAPATMAK güvenlik eylemidir: hiçbir rol kısıtına takılmamalı.
        bad = 0
        for info in infos:
            try:
                cpanel.ccp_write_value(self.ccp_client, info, 0, enforce_limits=False)
            except Exception:
                bad += 1
        self._log_event("KONTROL PANELİ", f"Tüm override'lar kapatıldı ({len(infos) - bad}/{len(infos)})")
        if bad == 0:
            panel.overrides_killed()
        else:
            panel._set_status(f"{bad} override kapatılamadı!", False)

    def _on_panel_reload(self):
        try:
            if self.transmit_tab.dbc.path:
                self.transmit_tab.dbc.load(self.transmit_tab.dbc.path)
            if self.a2l_tab.db.path:
                summary = self.a2l_tab.db.load(self.a2l_tab.db.path)
                self.a2l_tab._populate_tree(summary)
        except Exception as exc:
            QMessageBox.warning(self, "Yeniden yükleme hatası", str(exc))
            return
        self.control_panel_tab.refresh_sources(self.transmit_tab.dbc, self.a2l_tab.db)

    def _on_role_applied(self, user_name: str, role_value: str):
        self.current_user = user_name
        self.current_role = Role(role_value)
        self.dashboard_tab.set_role(self.current_role)
        if hasattr(self, "header_role_label"):
            self._update_role_label()
        self.control_panel_tab.set_allowed(can_override_actuator(self.current_role))
        self.dashboard_tab.sim_inputs.set_allowed(can_override_actuator(self.current_role))
        self._log_event("KULLANICI", f"Rol uygulandı: {user_name} ({role_value})")

    def _on_profile_save(self, name: str):
        if not can_manage_profiles(self.current_role):
            QMessageBox.warning(self, "Yetki yok", "Profil kaydetmek için Mühendis veya Yönetici rolü gerekir.")
            return
        if self.profile_store.get(name) is not None:
            ans = QMessageBox.question(
                self, "Profil üzerine yazılsın mı?",
                f"'{name}' profili zaten var; mevcut ayarlarla üzerine yazılacak.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        profile = ConfigProfile(
            name=name,
            interface=self.connection_tab.current_interface(),
            channel=self.connection_tab.current_channel(),
            bitrate=self.connection_tab.current_bitrate(),
            cro_id=self.ccp_tab.cro_edit.text().strip(),
            dto_id=self.ccp_tab.dto_edit.text().strip(),
            station_address=self.ccp_tab.station_edit.text().strip(),
            a2l_path=self.a2l_tab.db.path or "",
        )
        try:
            self.profile_store.upsert(profile)
        except OSError as exc:
            QMessageBox.warning(self, "Profil kaydedilemedi", str(exc))
            return
        self.user_tab.set_profiles(self.profile_store.names())
        self._log_event("PROFIL", f"Profil kaydedildi: {name}")

    def _on_profile_apply(self, name: str):
        profile = self.profile_store.get(name)
        if profile is None:
            return
        if self.connection.is_connected:
            QMessageBox.warning(
                self, "Bağlıyken profil uygulanamaz",
                "Bağlantı/CCP ayarlarını değiştirmeden önce önce bağlantıyı kesin."
            )
            return
        self.connection_tab.apply_profile_values(profile.interface, profile.channel, profile.bitrate)
        self.ccp_tab.cro_edit.setText(profile.cro_id)
        self.ccp_tab.dto_edit.setText(profile.dto_id)
        self.ccp_tab.station_edit.setText(profile.station_address)
        self._log_event("PROFIL", f"Profil uygulandı: {name}")

        if profile.a2l_path:
            try:
                summary = self.a2l_tab.db.load(profile.a2l_path)
            except ValueError as exc:
                QMessageBox.warning(self, "A2L yüklenemedi", str(exc))
                return
            self.a2l_tab.show_loaded(profile.a2l_path, summary)
            self.a2l_tab.a2l_loaded.emit()

    def _on_profile_delete(self, name: str):
        if not can_manage_profiles(self.current_role):
            QMessageBox.warning(self, "Yetki yok", "Profil silmek için Mühendis veya Yönetici rolü gerekir.")
            return
        ans = QMessageBox.question(self, "Profil silinsin mi?", f"'{name}' profili silinecek.",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.profile_store.delete(name)
        self.user_tab.set_profiles(self.profile_store.names())
        self._log_event("PROFIL", f"Profil silindi: {name}")

    # ---- Log --------------------------------------------------------------
    def _on_log_start(self, directory: str):
        try:
            path = self.can_logger.start(directory)
        except OSError as exc:
            QMessageBox.warning(self, "Kayıt başlatılamadı", f"Klasöre yazılamıyor: {exc}")
            self._log_event("HATA", f"CAN kaydı başlatılamadı: {exc}")
            return
        self._logged_count = 0
        self.log_tab.set_active(True, path)
        self.log_tab.set_count(0)

    def _on_log_stop(self):
        self.can_logger.stop()
        self.log_tab.set_active(False)

    def closeEvent(self, event):
        # Ayrı penceredeki Trend geri yerleşsin; aksi halde uygulama
        # son pencere kapanana kadar çıkmaz.
        for det in (getattr(self.dashboard_tab.trend, "detacher", None),):
            try:
                if det is not None:
                    det.dock()
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).exception("ayrı pencere kapatma hatası")
        try:
            self.workspace_tab.shutdown()
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("workspace shutdown hatası")
        self._on_disconnect()
        self.can_logger.stop()
        super().closeEvent(event)
