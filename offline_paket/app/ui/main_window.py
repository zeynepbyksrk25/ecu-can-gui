import logging
from datetime import datetime

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from app import theme
from app.can_worker import CanConnection
from app.change_tracker import ChangeTracker
from app.ccp.worker import IDLE, CcpSession
from app import control_panel as cpanel
from app.ui.control_panel_tab import ControlPanelTab
from app.dashboard_config import (
    DashboardConfigStore,
)
from app.eventlog import EventLog
from app.history import CalibrationHistory
from app.input_log import InputLog
from app.logger import CanLogger
from app.signal_feed import SignalFeed
from app.session_recorder import FrameRecorder, SessionRecorder
from app.paths import data_path
from app.profiles import ProfileStore
from app.scheduler import PeriodicManager
from app.ui.a2l_tab import A2LTab
from app.ui.can_monitor_tab import CanMonitorTab
from app.ui.dashboard_tab import DashboardTab
from app.ui.kalibrasyon_tab import KalibrasyonTab
from app.ui.tanilama_tab import TanilamaTab
from app.ui.settings_dialog import SettingsDialog
from app.ui.user_tab import UserTab
from app.user_roles import ROL_ADI

# Eski içe aktarma yolu (app.ui.main_window) çalışmaya devam etsin diye yeniden dışa aktarılır.
from app.ui.mainwin.common import (  # noqa: F401
    CCP_AUTO_CONNECT_DELAY_MS, CCP_JOB_INLINE_S, CONNECTION_LOSS_CONFIRM_S, CcpBusyError,
    HEALTH_CHECK_INTERVAL_MS, RECONNECT_INTERVAL_MS, RX_POLL_INTERVAL_MS, SAFETY_A2L_ATTEMPTS,
    SAFETY_REPEAT_COUNT, SAFETY_REPEAT_MS, SILENT_NOTICE_S, _CCP_IO_ERRORS,
)
from app.ui.mainwin.calibration import CalibrationMixin
from app.ui.mainwin.connection import ConnectionMixin
from app.ui.mainwin.dashboard import DashboardMixin
from app.ui.mainwin.exports import ExportMixin
from app.ui.mainwin.modas import ModasMixin
from app.ui.mainwin.modas_tools import ModasToolsMixin
from app.ui.mainwin.panel import PanelMixin
from app.ui.mainwin.profiles import ProfilesMixin
from app.ui.mainwin.recording import RecordingMixin
from app.ui.modas.pages import PageModel
from app.ui.modas.ribbon import ModasRibbon
from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace


class _ClickLabel(QLabel):
    """Tıklanabilir QLabel (bağlantı hapı)."""
    clicked = Signal()

    def mouseReleaseEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)


class _ToolWindow(QWidget):
    """Bağımsız araç penceresi (Modas 'Tools'): eski sayfanın widget'ını sarar; kapatılınca gizlenir, silinmez
    (sayfa arka planda canlı kalır)."""

    def __init__(self, title: str, body: QWidget, owner: QWidget):
        super().__init__(owner, Qt.Window)
        self.setWindowTitle(f"{title} — OpenECU")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(body)
        self.resize(1180, 780)

    def closeEvent(self, event):  # noqa: N802
        event.ignore()
        self.hide()


class MainWindow(ConnectionMixin, CalibrationMixin, DashboardMixin, PanelMixin, ProfilesMixin, ExportMixin, ModasMixin,
                 ModasToolsMixin, RecordingMixin, QMainWindow):
    """Ana pencere: pencere çatısı, sayfalar, sinyal bağlantıları ve kapanış. İş mantığı alanlara bölünmüş
    parçalardadır (bkz. ``app/ui/mainwin``): bağlantı, CCP/kalibrasyon, Ana Sayfa, Kontrol Paneli, profiller."""

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
        self.input_log = InputLog()          # tüm sayfalardaki girişlerin yapılandırılmış kaydı (Excel'e gider)
        self.profile_store = ProfileStore(path=data_path("profiles.json"))
        self.dashboard_config_store = DashboardConfigStore(path=data_path("dashboard_config.json"))
        self.current_user = "bilinmeyen"

        # ---- Bağlantı kopması izleme durumu (bkz. _check_connection_health)
        self._unhealthy_since: float | None = None
        self._conn_lost = False
        self._last_connect_params: tuple | None = None   # (interface, channel, bitrate)
        self.latest_signals: dict = {}                   # senaryo için son DBC sinyal değerleri
        self.latest_signals_enabled = False
        self.trigger_engine = None                       # kuruluyken tetik mantığı (app/record_trigger.py)
        self.backend_mode = "REAL"                       # REAL | MIL | VIRTUAL (bağlantı sayfasından seçilir)
        self._resume_ccp_after_reconnect = False
        self._loss_box: QMessageBox | None = None
        self._ccp_busy = False               # arka planda uzun bir CCP işi sürüyor (bkz. _ccp_job)
        self._job_progress = ""              # işin durum çubuğunda gösterilen ilerleme metni

        self.dashboard_tab = DashboardTab()

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

        self.a2l_tab = A2LTab()      # yalnız arka plan (yükleme/ayrıştırma); ekranda gösterilmez, ama ilerleme/hata kutuları için pencereye bağlı
        self.a2l_tab.setParent(self)
        self.a2l_tab.hide()
        self.control_panel_tab = ControlPanelTab(cpanel.ControlPanelConfig(data_path("kontrol_paneli.json")))
        self.tx_scheduler = cpanel.TxScheduler(self.transmit_tab.dbc, self._panel_send)

        self.kalibrasyon_tab = KalibrasyonTab()
        self.ccp_tab = self.kalibrasyon_tab.ccp
        self.history_tab = self.kalibrasyon_tab.history

        self.tanilama_tab = TanilamaTab()
        self.diagnostics_tab = self.tanilama_tab.diagnostics
        self.errors_tab = self.tanilama_tab.errors

        self.session_tab = self.tanilama_tab.session      # Tanılama ve Oturum sayfasının parçası
        self.user_tab = UserTab()
        # Profil artık üst sekme değil: komut şeridindeki "⚙ Ayarlar" penceresi (kullanıcı + profiller)
        self.settings_dialog = SettingsDialog(self.user_tab, self)

        # ---- Tek ana pencere (Modas). Eski sayfa widget'ları değişmedi; aşağıdaki takma adlar `self.xxx_tab`
        # referanslarının çalışmasını sağlar. Sayfalar artık yığın değil, Tools sekmesinden açılan araç pencereleridir.
        # Modas Sport tarzı çalışma alanı (ilk sayfa) + Ribbon; bkz. app/ui/modas ve app/ui/mainwin/modas.py
        self.modas_tab = ModasWorkspace(ModasSheetStore(data_path("modas_worksheets.json")))
        self.modas_ribbon = ModasRibbon()
        self.page_model = PageModel()

        # Tek ana pencere = Modas (ribbon + worksheet'ler). Diğer eski sayfalar ARAÇ PENCERELERİ olarak (Tools sekmesi)
        # ayrı, bağımsız pencerelerde açılır; sayfa yığını / üst sayfa sekmeleri yoktur.
        self._nav_pages = [
            ("📑", "Çalışma Sayfaları", self.modas_tab),
            ("🧪", "Test Tezgâhı", self.dashboard_tab),
            ("📶", "CAN İzleme", self.can_monitor_tab),
            ("⚙", "Kalibrasyon Araçları", self.kalibrasyon_tab),
            ("🎛", "Kontrol Paneli", self.control_panel_tab),
            ("🛡", "Tanılama", self.tanilama_tab),
        ]
        self._tool_pages = {label: page for _i, label, page in self._nav_pages[1:]}
        self._tool_windows: dict = {}
        self._cap_form_widths([p for _i, _l, p in self._nav_pages
                               if p not in (self.modas_tab, self.dashboard_tab, self.control_panel_tab)])
        self._page_scrolls: dict[QWidget, QScrollArea] = {}
        # Koyu temaya geçirilmiş sayfalar (koyu gövdeye sarılır); diğerleri henüz açık temada.
        self._dark_pages = {self.tanilama_tab, self.session_tab, self.kalibrasyon_tab, self.control_panel_tab}
        self._build_ui_chrome()

        self.dashboard_tab.set_config(self.dashboard_config_store.load())
        self._rebuild_dash_can_map()

        # İzleme sekmesi, Gönderim sekmesindeki DBC ile AYNI nesneyi kullanır;
        # böylece DBC yüklenince ikisi de aynı anda görür.
        self.monitor_tab.dbc = self.transmit_tab.dbc
        self.transmit_tab.dbc_loaded.connect(self.monitor_tab.refresh_dbc_messages)

        # CCP sekmesi, arka plandaki a2l_tab'ın AYNI A2LDatabase nesnesini kullanır;
        # A2L yüklenince nesne tarayıcısı orada da güncellenir.
        self.ccp_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.ccp_tab.refresh_objects)


        # Scope pencerelerinin sinyal beslemesi (Qt'siz): DBC kareleri, gösterge ve giriş değerleri ortak hub'a gider.
        from app.dashboard_config import GAUGE_KEYS
        self.signal_feed = SignalFeed(self.modas_tab.hub, GAUGE_KEYS)
        self.modas_tab.signal_groups = self.signal_feed.groups
        self.transmit_tab.dbc_loaded.connect(lambda *_: self.signal_feed.set_dbc(self.transmit_tab.dbc))
        self.signal_feed.set_dbc(self.transmit_tab.dbc)
        self.dashboard_tab.gauge_sample.connect(lambda k, v: self.signal_feed.push(f"gauge:{k}", v))


        self.session_tab.event_log = self.event_log
        self.session_tab.trend_provider = self.signal_feed.snapshot       # PDF rapor grafikleri: Scope'larda çizilen sinyaller
        # Oturum boyunca izlenen parametreleri diske (CSV) yazan kayıt.
        self.session_recorder = SessionRecorder()
        # Kayıt KAYNAKTA, verinin kendi geliş zamanında yapılır (bkz. app/session_recorder.py): CAN kareleri alım
        # iş parçacığından (FrameRecorder), CCP değerleri CCP iş parçacığından; kullanıcı girişleri girildikleri anda
        # (_record_input). Gösterge/grafik beslemeleri (arayüz zamanlayıcısıyla) KAYDA GİRMEZ.
        self.frame_recorder = FrameRecorder(self.session_recorder, lambda: self.transmit_tab.dbc)
        self.ccp_session.on_read = self._on_ccp_sample
        self._record_index: dict = {}                # (adres, uzantı, boyut) -> [A2L nesneleri]
        self._ccp_last_bytes: dict = {}
        self.a2l_tab.a2l_loaded.connect(self._rebuild_record_index)
        self.session_tab.session_started.connect(self._on_session_record_start)
        self.session_tab.session_stopped.connect(self._on_session_record_stop)
        self._wire_recording()
        self.session_tab.excel_requested.connect(self._on_excel_export_requested)
        self.history_tab.history = self.calibration_history
        self.session_tab.host_provider = lambda: self
        self.change_tracker = ChangeTracker()          # tek ortak değişiklik takibi (Worksheets, CCP, geçmiş)
        self.user_tab.set_profiles(self.profile_store.names())

        self.dashboard_tab.motor_start_requested.connect(self._on_motor_start)
        self.dashboard_tab.motor_stop_requested.connect(self._on_motor_stop)
        self.dashboard_tab.motor_start_released.connect(self._on_motor_start_off)
        self.dashboard_tab.motor_stop_released.connect(self._on_motor_stop_off)
        self.dashboard_tab.estop_requested.connect(self._on_estop)
        self.dashboard_tab.estop_released.connect(self._on_estop_released)
        self.dashboard_tab.config_saved.connect(self._on_dashboard_config_saved)
        self.dashboard_tab.tick.connect(self._on_dashboard_tick)
        self.dashboard_tab.writer = self._write_binding
        self.transmit_tab.dbc_loaded.connect(self._on_dashboard_sources_changed)
        self.a2l_tab.a2l_loaded.connect(self._on_dashboard_sources_changed)
        if hasattr(self, "header_user_label"):
            self._update_user_label()

        self._wire_signals()
        self._install_shortcuts_and_accessibility()
        self._wire_modas()
        self._wire_modas_tools()
        for sig in (self.transmit_tab.dbc_loaded, self.a2l_tab.a2l_loaded, self.dashboard_tab.config_saved,
                    self.user_tab.user_applied):
            sig.connect(self._schedule_minimum_size_refresh)

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

    def _make_scrollable_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        if page in self._dark_pages:
            from app.ui.dark_theme import dark_scroll_page
            scroll.setStyleSheet(theme.paint("QScrollArea#pageScroll { background: @@MODAS_RIBBON_BG@@; border: none; }"))
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
        """Etkin araç penceresinin sayfa widget'ı; araç penceresi etkin değilse ana pencerenin Worksheets sayfası."""
        active = QApplication.activeWindow()
        for page, win in self._tool_windows.items():
            if win is active:
                return page
        return self.modas_tab

    def open_tool(self, label_or_page) -> QWidget | None:
        """Araç penceresini (Test Bench, CAN Trace, Calibration Tools …) açar / öne getirir. Pencere ilk açılışta kurulur;
        sayfa widget'ı arka planda her zaman canlıdır (CAN/CCP besleme kodu bundan etkilenmez)."""
        page = self._tool_pages.get(label_or_page, label_or_page)
        if page is self.modas_tab or page not in self._tool_pages.values():
            self.activateWindow()
            self.raise_()
            return None
        win = self._tool_windows.get(page)
        if win is None:
            label = next(l for l, p in self._tool_pages.items() if p is page)
            win = _ToolWindow(label, self._make_scrollable_page(page), self)
            self._tool_windows[page] = win
        win.show()
        win.raise_()
        win.activateWindow()
        return win

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
        central_layout.addWidget(self._build_modas_chrome())
        central_layout.addWidget(self.modas_tab, stretch=1)

        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)
        # Ana Sayfa kaydırılmadığı için pencere, sayfanın sığacağı en küçük boyuttan
        # küçültülemez (16" laptop: 1280x720 etkin çözünürlükte bile sığar).
        self._refresh_minimum_size()
        self.header_clock_label = QLabel("")
        self.header_clock_label.setObjectName("headerClock")
        self.statusBar().addPermanentWidget(self.header_clock_label)
        self._update_connection_display()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start()
        self._update_clock()

    def _refresh_minimum_size(self):
        """Pencerenin asgari boyutunu İÇERİĞE göre yeniden hesaplar ve gerekirse pencereyi büyütür.

        Neden tekrar tekrar: DBC/A2L yüklenince ya da eşleşmeler değişince kartlar genişleyebilir (ör. "CAN
        periyodik" etiketi, uyarı simgeleri). Asgari boyut yalnızca açılışta hesaplanırsa pencere eski asgari
        boyutunda kalır, sayfa kendi asgari boyutunun altına sıkışır ve düğme metinleri kırpılır."""
        central = self.centralWidget()
        if central is None:
            return
        if central.layout() is not None:
            central.layout().activate()                     # bekleyen yerleşim işlenmeden ipucu okunmasın
        hint = central.minimumSizeHint()
        want_w, want_h = max(1100, hint.width()), max(600, hint.height() + 26)
        if (want_w, want_h) != (self.minimumWidth(), self.minimumHeight()):
            self.setMinimumSize(want_w, want_h)
        # Tam ekran / büyütülmüş pencere zaten ekranı kaplar: yeniden boyutlandırmak yerleşimi kaydırır.
        if not (self.isMaximized() or self.isFullScreen()) and (self.width() < want_w or self.height() < want_h):
            self.resize(max(self.width(), want_w), max(self.height(), want_h))

    def showEvent(self, event):  # noqa: N802
        """İlk gösterimde asgari boyutu YENİDEN hesaplar. Yapıcıdaki ilk hesap sayfa gösterilip stiller uygulanmadan
        yapıldığı için eksik kalıyordu (kartlar ~40 px sıkışık açılıyor); ilk Kaydet'te düzelince pencere büyüyüp
        yerleşim kayıyordu. Stil uygulanması bir olay turu sürdüğünden ikinci bir kez de geciktirilmiş çalışır."""
        super().showEvent(event)
        if not getattr(self, "_min_size_settled", False):
            self._min_size_settled = True
            self._schedule_minimum_size_refresh()
            QTimer.singleShot(300, self._schedule_minimum_size_refresh)

    def _schedule_minimum_size_refresh(self, *_):
        """İçerik değişiminden SONRA (yerleşim güncellenince) asgari boyutu yeniler; art arda çağrılar birleşir."""
        if not getattr(self, "_min_refresh_pending", False):
            self._min_refresh_pending = True

            def run():
                self._min_refresh_pending = False
                self._refresh_minimum_size()

            QTimer.singleShot(0, run)

    def _apply_shadow(self, widget: QWidget, blur: float = 18, dy: float = 3, alpha: int = 45):
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur)
        effect.setOffset(0, dy)
        effect.setColor(QColor(20, 30, 40, alpha))
        widget.setGraphicsEffect(effect)

    def _build_modas_chrome(self) -> QWidget:
        """Üst şerit = Modas Ribbon (bkz. app/ui/modas/ribbon.py). Eski başlık + komut şeridindeki tüm widget'lar
        (bağlantı hapı, CCP durumu, kullanıcı, Ayarlar, Eşleşmeler, Motor Başlat/Durdur/ACİL DURDURMA) aynı adlarla yaşar:
        durum alanı sekme satırının sağında, Motor grubu HER sekmede görünen sağ bölmede (Acil Durdurma gizlenmez).
        Araç pencereleri: Tools sekmesi, Ctrl+1…6, bağlantı hapı (bkz. ``open_tool``)."""
        rb = self.modas_ribbon
        rb.set_pages([(icon, label) for icon, label, _p in self._nav_pages])

        self.header_conn_pill = _ClickLabel("●  Bağlı değil")
        self.header_conn_pill.setObjectName("connPillBad")
        self.header_conn_pill.setCursor(Qt.PointingHandCursor)
        self.header_conn_pill.setToolTip("Tıkla: bağlantı ayarları (CAN Monitor sekmesi)")
        self.header_conn_pill.clicked.connect(self._open_connection_page)

        self.ccp_chip = QLabel("CCP bağlı değil")
        self.ccp_chip.setObjectName("ccpChip")
        self.ccp_chip.setProperty("state", IDLE)
        self.ccp_chip.setToolTip("CCP/ECU durumu: bağlı değil → bağlanıyor → çevrimiçi → ECU yok (otomatik yeniden bağlanır)")
        self.rec_chip = QLabel("REC yok")
        self.rec_chip.setObjectName("recChip")
        self.rec_chip.setProperty("state", "")
        self.rec_chip.setToolTip("Veri kaydı durumu: Test oturumu başlayınca REC; duraklatma ve yazma hataları burada görünür")
        self.header_user_label = _ClickLabel("")
        self.header_user_label.setObjectName("headerReadout")
        self.header_user_label.setTextFormat(Qt.RichText)
        self.header_user_label.setCursor(Qt.PointingHandCursor)
        self.header_user_label.setToolTip("Tıkla: kullanıcı ayarları")
        self.header_user_label.clicked.connect(self.open_settings)
        self.settings_button = QPushButton("⚙  Ayarlar")
        self.settings_button.setFixedHeight(24)
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setToolTip("Kullanıcı ve bağlantı+CCP profilleri")
        self.settings_button.clicked.connect(self.open_settings)
        self.mappings_button = QPushButton("⚙  Eşleşmeler")
        self.mappings_button.setFixedHeight(24)
        self.mappings_button.setCursor(Qt.PointingHandCursor)
        self.mappings_button.setToolTip("Sensör, eyleyici, motor komutu ve giriş sinyallerinin CAN (DBC) / A2L eşleşmeleri")
        self.mappings_button.clicked.connect(self.dashboard_tab.open_mappings)
        for w in (self.rec_chip, self.ccp_chip, self.header_user_label, self.settings_button, self.mappings_button, self.header_conn_pill):
            rb.add_status_widget(w)

        dt = self.dashboard_tab
        for tg in (dt.start_toggle, dt.stop_toggle, dt.estop_toggle):
            if tg is dt.estop_toggle:
                # Acil Durdurma normal komutlardan görsel olarak ayrılır
                sep = QFrame()
                sep.setObjectName("cmdSep")
                sep.setFixedHeight(30)
                rb.add_motor_widget(sep)
            rb.add_motor_widget(tg)
        rb.add_motor_note(dt.estop_warn)
        self._update_user_label()
        return rb

    ESTOP_SHORTCUT = "Ctrl+Shift+E"

    def _install_shortcuts_and_accessibility(self):
        """Klavye kısayolları ve ekran okuyucu / erişilebilirlik adları.

        Acil Durdurma kısayolu UYGULAMA kapsamlıdır: hangi sayfa açık olursa olsun (ve odak bir giriş
        kutusunda bile) çalışır. Yanlışlıkla basılmasın diye üç tuşludur."""
        dt = self.dashboard_tab
        self._estop_shortcut = QShortcut(QKeySequence(self.ESTOP_SHORTCUT), self)
        self._estop_shortcut.setContext(Qt.ApplicationShortcut)
        self._estop_shortcut.activated.connect(dt.estop_button.click)
        for i, (_icon, label, _page) in enumerate(self._nav_pages[:9]):      # Ctrl+1..6: sayfa geçişi
            sc = QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(lambda _c=False, pg=_page: self.open_tool(pg))
        self._install_record_shortcuts()
        dt.estop_hint = f"Kısayol: {self.ESTOP_SHORTCUT}"
        dt.update_estop_tooltip()
        names = {
            dt.start_button: ("Motoru başlat", "Motor Başlat sinyaline AÇIK=1, KAPALI=0 yazar"),
            dt.stop_button: ("Motoru durdur", "Motor Durdur sinyaline AÇIK=1, KAPALI=0 yazar"),
            dt.estop_button: ("Acil durdurma", f"Acil Durdurma komutunu hemen gönderir. Kısayol {self.ESTOP_SHORTCUT}"),
            dt.estop_warn: ("Acil durdurma eşlenmemiş uyarısı", "Eşleşmeler penceresini açar"),
            self.header_conn_pill: ("CAN bağlantı durumu", "CAN Trace penceresini açar"),
            self.ccp_chip: ("CCP durumu", "CCP oturumunun durumu"),
            self.header_user_label: ("Kullanıcı", "Kullanıcı ayarlarını açar"),
            self.settings_button: ("Ayarlar", "Kullanıcı ve profiller"),
            self.mappings_button: ("Eşleşmeler", "CAN ve A2L eşleşmeleri"),
        }
        for widget, (name, desc) in names.items():
            widget.setAccessibleName(name)
            widget.setAccessibleDescription(desc)

    def _open_connection_page(self):
        """Bağlantı hapına / ECU düğmesine tıklanınca CAN Trace (bağlantı şeridi) araç penceresini aç."""
        self.open_tool("CAN İzleme")

    def open_settings(self):
        """Ayarlar penceresi (kullanıcı + profiller)."""
        self.settings_dialog.exec()

    def _update_user_label(self):
        self.header_user_label.setText(f"Kullanıcı: <b style='color:{theme.INK}'>{self.current_user} · {ROL_ADI} ▾</b>")

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
        """Eski sayfa-geçişi çağrılarının uyumluluk katmanı: Worksheets ana pencereyi, diğer sayfalar araç penceresini açar."""
        self.open_tool(widget)

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

        self.ccp_tab.open_in_modas_requested.connect(self._open_in_modas)

        self.transmit_tab.dbc_loaded.connect(self._panel_sources_changed)
        self.transmit_tab.dbc_loaded.connect(lambda *_: self.tx_scheduler.refresh_frames())
        self.a2l_tab.a2l_loaded.connect(self._panel_sources_changed)
        self.control_panel_tab.apply_requested.connect(self._on_panel_apply)
        self.control_panel_tab.poll_requested.connect(self._on_panel_poll)
        self.control_panel_tab.kill_overrides_requested.connect(self._on_panel_kill_overrides)
        self.control_panel_tab.tx_toggle_requested.connect(self._on_panel_tx_toggle)
        self.control_panel_tab.reload_requested.connect(self._on_panel_reload)
        self.tx_scheduler.failed.connect(self._on_panel_tx_failed)
        self.tx_scheduler.recovered.connect(self._on_panel_tx_recovered)
        self.tx_scheduler.state_changed.connect(self._panel_tx_state)

        self.diagnostics_tab.test_requested.connect(self._on_diag_test_requested)
        self.diagnostics_tab.diag_requested.connect(self._on_diag_requested)

        self.history_tab.revert_requested.connect(self._on_history_revert)

        self.settings_dialog.mappings_requested.connect(self.dashboard_tab.open_mappings)
        self.user_tab.user_applied.connect(self._on_user_applied)
        self.user_tab.profile_save_requested.connect(self._on_profile_save)
        self.user_tab.profile_apply_requested.connect(self._on_profile_apply)
        self.user_tab.profile_delete_requested.connect(self._on_profile_delete)

    def _log_event(self, category: str, message: str):
        self.event_log.add(category, message, user=self.current_user, role=ROL_ADI)
        rec = getattr(self, "session_recorder", None)
        if rec is not None:
            rec.record_event(category, message)       # kayıt açıkken olay dosyasına (bağlantı, hata, kalibrasyon…)
        self.modas_tab.log_panel.add_entry(self.event_log.entries[-1])
        self.session_tab.refresh_log()

    def closeEvent(self, event):
        if self._ccp_busy:
            # Yarım kalmış bir tablo/flaş yazımı ECU'yu tutarsız bırakır: iş bitene kadar kapanma.
            event.ignore()
            self.statusBar().showMessage("CCP işlemi sürüyor; bitince kapatabilirsiniz.", 5000)
            return
        try:
            self._modas_save_dataset()                   # workbase açıkken PC veri seti (son WP değerleri) kaydedilir
        except Exception:  # noqa: BLE001 - kapanışı engellemesin
            logging.getLogger(__name__).exception("Veri seti kapanışta kaydedilemedi")
        try:
            self.modas_tab.shutdown()
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("modas shutdown hatası")
        self._on_disconnect()
        if getattr(self, "model_ctl", None) is not None:
            self.model_ctl.close()
        self._model_timer.stop()
        self.ccp_session.stop(graceful=False)       # iş parçacığı her durumda bitsin
        self.can_logger.stop()
        self.connection.frame_tap = None
        self.frame_recorder.stop()
        self.session_recorder.stop()
        # Pencere kapandıktan sonra hiçbir zamanlayıcı çalışmasın (kapanmış pencerenin sayfaları
        # arka planda okuma/çizim yapmaya devam etmesin).
        for timer in self.findChildren(QTimer):
            timer.stop()
        super().closeEvent(event)
