import logging
import os
import queue
import time
from datetime import datetime

import can
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from app.can_worker import CanConnection
from app.ccp import codec as ccp_codec
from app.ccp import mapio as ccp_mapio
from app.ccp import protocol as ccp_protocol
from app.ccp.client import CCPClient
from app.ccp_poll import CcpReadPool
from app import control_panel as cpanel
from app.ui.control_panel_tab import ControlPanelTab
from app.ui.performance_tab import PerformanceTab
from app.sim_interface import INPUT_DEFS, SimConfig
from app.dashboard_config import DashboardConfigStore
from app.eventlog import EventLog
from app.history import CalibrationHistory
from app.logger import CanLogger
from app.paths import data_dir, data_path
from app.profiles import ConfigProfile, ProfileStore
from app.scheduler import PeriodicManager
from app.ui.a2l_tab import A2LTab
from app.ui.can_monitor_tab import CanMonitorTab
from app.ui.dashboard_tab import DashboardTab
from app.ui.graph_tab import GraphTab
from app.ui.workspace_tab import WorkspaceLayoutStore, WorkspaceTab
from app.ui.kalibrasyon_tab import KalibrasyonTab
from app.ui.session_tab import SessionTab
from app.ui.tanilama_tab import TanilamaTab
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
CCP_AUTO_CONNECT_DELAY_MS = 300  # CAN bağlandıktan kaç ms sonra CCP otomatik bağlansın
WATCH_FAIL_STREAK_LIMIT = 3  # Parametre Listesi'nde art arda bu kadar ECU-cevapsız turdan sonra sürekli okuma durur


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenECU M220 — Test & Kalibrasyon Aracı")
        self._apply_initial_geometry()

        self.connection = CanConnection()
        self.periodic_manager: PeriodicManager | None = None
        self.can_logger = CanLogger()
        self._logged_count = 0
        self.ccp_client: CCPClient | None = None
        # CCP okumaları UI thread'ini bloklamasın (bkz. app/ccp_poll.py).
        self._active_overrides: dict = {}   # actuator_key -> son değer (ECU'da açık override'lar)
        self.ccp_pool = CcpReadPool(self)
        self.ccp_pool.unresponsive_changed.connect(self._on_ccp_unresponsive)
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

        self.a2l_tab = A2LTab()
        self.control_panel_tab = ControlPanelTab(cpanel.ControlPanelConfig(data_path("kontrol_paneli.json")))
        self.tx_scheduler = cpanel.TxScheduler(self.transmit_tab.dbc, self._panel_send)

        self.kalibrasyon_tab = KalibrasyonTab()
        self.ccp_tab = self.kalibrasyon_tab.ccp
        self.watch_tab = self.kalibrasyon_tab.watch
        self.map_editor_tab = self.kalibrasyon_tab.map_editor
        self.history_tab = self.kalibrasyon_tab.history

        self.graph_tab = GraphTab()
        self.workspace_tab = WorkspaceTab(WorkspaceLayoutStore(data_path("workspace_layouts.json")))

        self.tanilama_tab = TanilamaTab()
        self.diagnostics_tab = self.tanilama_tab.diagnostics
        self.errors_tab = self.tanilama_tab.errors

        self.session_tab = SessionTab()
        self.user_tab = UserTab()

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
            ("📄", "A2L", self.a2l_tab),
            ("⚙", "Kalibrasyon", self.kalibrasyon_tab),
            ("📈", "Grafik", self.graph_tab),
            ("🔬", "Çalışma Alanı", self.workspace_tab),
            ("📊", "Performans", self.performance_tab),
            ("🎛", "Kontrol Paneli", self.control_panel_tab),
            ("🛡", "Tanılama", self.tanilama_tab),
            ("🗓", "Test Oturumu", self.session_tab),
            ("👤", "Kullanıcı / Profil", self.user_tab),
        ]
        # Her sayfa kendi QScrollArea'sı içinde yaşar: pencere sayfa
        # içeriğinden KÜÇÜKSE (düşük çözünürlüklü laptop vb.) içerik aşağıdan
        # dışarı taşıp erişilemez olmak yerine dikey/yatay kaydırılabilir.
        # Pencere büyükse sayfa alanı doldurur (widgetResizable).
        self._cap_form_widths([p for _i, _l, p in self._nav_pages
                               if p not in (self.dashboard_tab, self.performance_tab, self.control_panel_tab,
                                         self.workspace_tab)])
        self.stack = QStackedWidget()
        self._page_scrolls: dict[QWidget, QScrollArea] = {}
        for _icon, _label, page in self._nav_pages:
            self.stack.addWidget(self._make_scrollable_page(page))

        self._build_ui_chrome()

        self.dashboard_tab.set_config(self.dashboard_config_store.load())
        self.watch_tab.set_storage_path(data_path("watchlist.json"))

        # İzleme sekmesi, Gönderim sekmesindeki DBC ile AYNI nesneyi kullanır;
        # böylece DBC yüklenince ikisi de aynı anda görür.
        self.monitor_tab.dbc = self.transmit_tab.dbc
        self.transmit_tab.dbc_loaded.connect(self.monitor_tab.refresh_dbc_messages)

        # CCP sekmesi, A2L sekmesindeki AYNI A2LDatabase nesnesini kullanır;
        # A2L yüklenince nesne tarayıcısı orada da güncellenir.
        self.ccp_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.ccp_tab.refresh_objects)

        self.map_editor_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.map_editor_tab.refresh_objects)

        self.watch_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.watch_tab.refresh_objects)
        self.watch_tab.refresh_objects()

        self.graph_tab.a2l_db = self.a2l_tab.db
        self.a2l_tab.a2l_loaded.connect(self.graph_tab.refresh_objects)

        # Çalışma Alanı: A2L/DBC listeleri, CCP okuma isteği, giriş/gösterge beslemesi.
        self.a2l_tab.a2l_loaded.connect(self._sync_workspace_a2l)
        self.transmit_tab.dbc_loaded.connect(lambda *_: self.workspace_tab.set_dbc(self.transmit_tab.dbc))
        self.workspace_tab.set_dbc(self.transmit_tab.dbc)
        self.workspace_tab.read_requested.connect(self._on_workspace_tick)
        self.workspace_tab.send_input.connect(self.dashboard_tab.sim_inputs.send_value)
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
        self.dashboard_tab.open_graph_requested.connect(
            lambda: self.setCurrentWidget(self.graph_tab)
        )
        self.dashboard_tab.actuator_command.connect(self._send_actuator_override)
        self.dashboard_tab.set_role(self.current_role)

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

    def _make_scrollable_page(self, page: QWidget) -> QScrollArea:
        scroll = QScrollArea()
        scroll.setObjectName("pageScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(page)
        self._page_scrolls[page] = scroll
        return scroll

    def current_page(self) -> QWidget | None:
        """Şu an görünen sayfanın KENDİ widget'ı (QScrollArea sarmalayıcısı değil)."""
        scroll = self.stack.currentWidget()
        return scroll.widget() if isinstance(scroll, QScrollArea) else scroll

    def _apply_initial_geometry(self):
        """İlk pencere boyutu EKRANA sığmalı: sabit 1600x950, 1366x768 gibi
        laptop ekranlarında pencereyi alt kenardan dışarı taşırıyordu.
        Kullanılabilir alanın %92'sini aşmayacak şekilde seçilir."""
        self.setMinimumSize(900, 560)
        screen = QGuiApplication.primaryScreen()
        if screen is None:
            self.resize(1280, 800)
            return
        avail = screen.availableGeometry()
        width = min(1600, int(avail.width() * 0.92))
        height = min(950, int(avail.height() * 0.92))
        self.resize(max(900, width), max(560, height))
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

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self._build_sidebar())
        body.addWidget(self.stack, stretch=1)
        central_layout.addLayout(body, stretch=1)

        self.setCentralWidget(central)
        self.statusBar().setSizeGripEnabled(False)
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

    def _build_sidebar(self) -> QWidget:
        root = QWidget()
        root.setObjectName("sidebarRoot")
        root.setFixedWidth(220)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("sidebarNav")
        self.nav_list.setFocusPolicy(Qt.NoFocus)
        for icon, label, _page in self._nav_pages:
            item = QListWidgetItem(f"{icon}   {label}")
            self.nav_list.addItem(item)
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self.stack.setCurrentIndex)
        layout.addWidget(self.nav_list, stretch=1)

        # Alt durum bloğu: referans mockup'ta koyu lacivert sidebar
        # zemininin üzerinde YÜZEN, BEYAZ/açık renkli yuvarlak köşeli bir
        # "kart" (düz metin DEĞİL — bkz. görev tanımı madde 7).
        status = QFrame()
        status.setObjectName("sidebarStatusCard")
        status_layout = QVBoxLayout(status)
        status_layout.setContentsMargins(14, 12, 14, 10)
        status_layout.setSpacing(3)

        self.sidebar_conn_label = QLabel()
        self.sidebar_conn_label.setTextFormat(Qt.RichText)
        self.sidebar_conn_label.setObjectName("sidebarStatusTitle")
        self.sidebar_iface_label = QLabel("Bağlantı: Pasif")
        self.sidebar_iface_label.setObjectName("sidebarStatusDim")
        self.sidebar_version_label = QLabel("CAN 2.0A / 2.0B")
        self.sidebar_version_label.setObjectName("sidebarStatusDim")
        status_layout.addWidget(self.sidebar_conn_label)
        status_layout.addWidget(self.sidebar_iface_label)
        status_layout.addWidget(self.sidebar_version_label)

        settings_link = QPushButton("⚙  Ayarlar")
        settings_link.setObjectName("sidebarSettingsLink")
        settings_link.setCursor(Qt.PointingHandCursor)
        settings_link.clicked.connect(lambda: self.nav_list.setCurrentRow(
            len(self._nav_pages) - 1))  # "Kullanıcı / Profil" sekmesine götürür
        status_layout.addSpacing(4)
        status_layout.addWidget(settings_link)

        status_margin = QWidget()
        status_margin_layout = QVBoxLayout(status_margin)
        status_margin_layout.setContentsMargins(10, 8, 10, 14)
        status_margin_layout.addWidget(status)
        self._apply_shadow(status, blur=16, dy=2, alpha=70)
        layout.addWidget(status_margin)
        return root

    def _build_top_header(self) -> QWidget:
        """Üst koyu lacivert başlık şeridi: logo rozeti + başlık + bağlantı
        pili (referans mockup'taki ince navy şerit)."""
        header = QFrame()
        header.setObjectName("topHeaderNavy")
        outer = QHBoxLayout(header)
        outer.setContentsMargins(16, 10, 16, 10)
        outer.setSpacing(10)

        logo = QLabel("🔧")
        logo.setObjectName("headerLogoBadge")
        logo.setFixedSize(30, 30)
        logo.setAlignment(Qt.AlignCenter)
        outer.addWidget(logo)

        title = QLabel("ECU CAN Haberleşme Arayüzü")
        title.setObjectName("headerTitle")
        outer.addWidget(title)
        outer.addStretch()

        self.header_conn_pill = QLabel("●  Bağlı değil")
        self.header_conn_pill.setObjectName("connPillBad")
        outer.addWidget(self.header_conn_pill)
        return header

    def _build_action_status_row(self) -> QWidget:
        """Başlık şeridinin HEMEN altındaki TEK satır: solda motor
        komutu düğmeleri (her biri hafif gölgeli birer "kart" gibi),
        sağda ikonlu durum okumaları (Sistem / Ortam / Tarih-Saat) — arka
        plan kartı YOK, doğrudan sayfa zemini üzerinde (görev tanımı
        madde 3). Büyük koyu ikaz lambası şeridi burada KASITLI OLARAK
        YOK (bkz. app/ui/dashboard_tab.py DashboardTab sınıf yorumu ve bu
        dosyanın değişiklik raporu: lamba verisi/mantığı korunuyor,
        yalnızca görünür ana akıştan çıkarıldı)."""
        row = QFrame()
        row.setObjectName("actionStatusRow")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(16, 10, 20, 10)
        layout.setSpacing(10)

        # Dashboard sekmesinin KENDİ düğmelerini (mantık/onay diyalogları
        # zaten orada) burada, tek görünür satırda kullanıyoruz — ayrı bir
        # "Motor Komutları" kutusu / kopya düğme YOK.
        self.dashboard_tab.start_button.setText("▶  Motoru Başlat")
        self.dashboard_tab.stop_button.setText("⏹  Motoru Durdur")
        self.dashboard_tab.estop_button.setText("⚠  Acil Durdurma")
        self.dashboard_tab.estop_button.setProperty("danger", True)
        for btn in (self.dashboard_tab.start_button, self.dashboard_tab.stop_button,
                    self.dashboard_tab.estop_button):
            btn.setMinimumHeight(36)
            btn.setMaximumWidth(180)
            btn.setCursor(Qt.PointingHandCursor)
            self._apply_shadow(btn, blur=12, dy=2, alpha=35)
            layout.addWidget(btn)

        layout.addStretch()

        self.header_system_label = QLabel("ⓘ Sistem:  <span style=\"color:#1B8A4C;\">●</span> Aktif")
        self.header_ambient_label = QLabel("🌡 Ortam:  <span style=\"color:#1B8A4C;\">●</span> Normal")
        self.header_clock_label = QLabel("📅 Tarih/Saat  —")
        for lbl in (self.header_system_label, self.header_ambient_label, self.header_clock_label):
            lbl.setObjectName("headerReadout")
            lbl.setTextFormat(Qt.RichText)
            layout.addWidget(lbl)
            layout.addSpacing(18)
        return row

    def _update_clock(self):
        now_text = datetime.now().strftime("%d.%m.%Y  %H:%M:%S")
        self.header_clock_label.setText(f"📅 Tarih/Saat  {now_text}")

    def _update_connection_display(self, health_message: str | None = None):
        connected = self._conn_state["connected"]
        interface = self._conn_state["interface"]
        version = self._conn_state["version"]

        lost = bool(self._conn_state.get("lost", False))
        if connected:
            self.header_conn_pill.setObjectName("connPillOk")
            self.header_conn_pill.setText(f"●  Bağlı  |  {interface}")
            self.sidebar_iface_label.setText("Bağlantı: Aktif")
            dot_color = "#58D88C"
        elif lost:
            self.header_conn_pill.setObjectName("connPillBad")
            self.header_conn_pill.setText("●  Bağlantı koptu — yeniden bağlanılıyor…")
            self.sidebar_iface_label.setText("Bağlantı: KOPTU")
            dot_color = "#E0A030"
        else:
            self.header_conn_pill.setObjectName("connPillBad")
            self.header_conn_pill.setText("●  Bağlı değil")
            self.sidebar_iface_label.setText("Bağlantı: Pasif")
            dot_color = "#C22A1D"
        self.sidebar_conn_label.setText(
            f'<span style="color:{dot_color};">●</span>&nbsp;&nbsp;<b>PCAN-USB</b>'
        )
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
        çağrılarının (bkz. open_graph_requested bağlantısı) değişmeden
        çalışmaya devam etmesi için ince bir uyumluluk katmanı: hem sayfa
        yığınını hem de sidebar seçimini günceller."""
        index = self.stack.indexOf(self._page_scrolls.get(widget, widget))
        if index != -1:
            self.nav_list.setCurrentRow(index)

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
        self.tx_scheduler.state_changed.connect(self._panel_tx_state)
        self.control_panel_tab.set_allowed(can_override_actuator(self.current_role))
        self.watch_tab.read_requested.connect(self._on_watch_read)
        self.watch_tab.write_requested.connect(self._on_watch_write)

        self.map_editor_tab.read_requested.connect(self._on_map_read)
        self.map_editor_tab.write_requested.connect(self._on_map_write)
        self.map_editor_tab.read_all_requested.connect(self._on_map_read_all)
        self.map_editor_tab.write_all_requested.connect(self._on_map_write_all)

        self.graph_tab.read_requested.connect(self._on_graph_tick)

        self.diagnostics_tab.test_requested.connect(self._on_diag_test_requested)
        self.diagnostics_tab.diag_requested.connect(self._on_diag_requested)

        self.history_tab.revert_requested.connect(self._on_history_revert)

        self.user_tab.role_applied.connect(self._on_role_applied)
        self.user_tab.profile_save_requested.connect(self._on_profile_save)
        self.user_tab.profile_apply_requested.connect(self._on_profile_apply)
        self.user_tab.profile_delete_requested.connect(self._on_profile_delete)

    def _log_event(self, category: str, message: str):
        self.event_log.add(category, message, user=self.current_user, role=self.current_role.value)
        self.session_tab.refresh_log()
        if category == "HATA":
            self.errors_tab.set_errors([e for e in self.event_log.entries if e.category == "HATA"])

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
        self.periodic_manager = PeriodicManager(self.connection.bus)
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
            QTimer.singleShot(CCP_AUTO_CONNECT_DELAY_MS, self._auto_ccp_connect)

    def _release_overrides_on_teardown(self, graceful: bool):
        """Bağlantı kapanırken ECU'da açık kalmış eyleyici override'larını
        bırakmayı dener (graceful) ve her durumda arayüzü 'bilinmiyor'a çeker.
        Bırakılamayanlar HATA olarak loglanır ve kullanıcıya gösterilir."""
        keys = list(self._active_overrides)
        if not keys:
            return
        if graceful:
            for k in keys:
                try:
                    self._send_actuator_override(k, False, 0.0)
                except Exception:  # noqa: BLE001
                    pass
        remaining = [k for k in keys if k in self._active_overrides]
        if remaining:
            from app.dashboard_config import ACTUATOR_LABELS
            names = ", ".join(ACTUATOR_LABELS.get(k, k) for k in remaining)
            self._log_event("HATA", f"Bağlantı kapandı; ECU'da şu override'lar AÇIK kalmış olabilir: {names}")
            self.statusBar().showMessage(f"UYARI: override açık kalmış olabilir: {names}", 15000)
        self._active_overrides.clear()
        self.dashboard_tab.reset_actuators_unknown()

    def _teardown_connection(self, graceful: bool = True):
        """CAN bağlantısına bağlı her şeyi kapatır. graceful=False: adaptör
        gitmiş olduğu için CCP DISCONNECT gibi bus'a yazan adımlar ATLANIR
        (aksi halde zaman aşımlarında arayüz bloklanırdı)."""
        self._release_overrides_on_teardown(graceful)
        if self.ccp_client is not None:
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
        self.connection_tab.set_health(ok, message)
        self.errors_tab.set_health(ok, message)
        if not ok and getattr(self, "_last_health_state", "ok") == "ok":
            self._log_event("HATA", f"CAN hat durumu uyarısı: {message}")
        self._last_health_state = state
        self._update_connection_display(health_message=message)

    def _handle_connection_lost(self, reason: str, elapsed: float):
        """Bağlantı KOPTU: her şeyi temizle, kullanıcıya açıkça bildir ve
        adaptör geri gelirse otomatik yeniden bağlanmak için denemeye başla."""
        self._resume_ccp_after_reconnect = self.ccp_client is not None or self._resume_ccp_after_reconnect
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
            if self.can_logger.is_active:
                self.can_logger.write(msg.timestamp, msg.arbitration_id, msg.dlc,
                                       msg.data, msg.is_extended_id)
                self._logged_count += 1
        if n and self.can_logger.is_active:
            self.log_tab.set_count(self._logged_count)
        if self.can_logger.error and not self.can_logger.is_active and not getattr(self, "_log_err_shown", False):
            self._log_err_shown = True
            self.log_tab.set_active(False, "")
            self._log_event("HATA", f"CAN kaydı yazma hatasıyla DURDU: {self.can_logger.error}")
            QMessageBox.warning(self, "CAN kaydı durdu", f"Yazma hatası: {self.can_logger.error}")
        elif self.can_logger.is_active:
            self._log_err_shown = False

    # ---- Gönderim -------------------------------------------------------
    @staticmethod
    def _frame_text(can_id: int, data: bytes, extended: bool) -> str:
        return f"ID=0x{can_id:X}{' (ext)' if extended else ''} DLC={len(data)} DATA={data.hex(' ').upper()}"

    def _on_manual_send(self, can_id: int, data: bytes, extended: bool):
        if not can_transmit_frames(self.current_role):
            QMessageBox.warning(self, "Yetki yok",
                                "CAN çerçevesi göndermek için Mühendis veya Yönetici rolü gerekir "
                                "(Kullanıcı / Profil sekmesinden rol seçin).")
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
                                "(Kullanıcı / Profil sekmesinden rol seçin).")
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
        """Manuel "CCP Bağlan" düğmesi (hata durumunda kullanıcıya diyalog gösterir)."""
        self._do_ccp_connect(cro_id, dto_id, station_address, silent=False)

    def _auto_ccp_connect(self):
        """CAN bağlanınca otomatik CCP bağlantısı: başarısızlıkta diyalog
        AÇMAZ (ECU kapalı/CCP desteklemeyen hat olabilir), sadece günlüğe ve
        CCP durum etiketine yazar; kullanıcı elle tekrar deneyebilir."""
        if not self.connection.is_connected or self.ccp_client is not None:
            return
        try:
            cro_id, dto_id, station = self.ccp_tab.parsed_connection_params()
        except ValueError as exc:
            self._log_event("HATA", f"Otomatik CCP bağlantısı atlandı: {exc}")
            return
        self._do_ccp_connect(cro_id, dto_id, station, silent=True)

    def _do_ccp_connect(self, cro_id: int, dto_id: int, station_address: int, silent: bool) -> bool:
        if not self.connection.is_connected:
            if not silent:
                QMessageBox.warning(
                    self, "CAN bağlantısı yok",
                    "CCP bağlantısı kurmadan önce Bağlantı sekmesinden CAN hattına bağlanın."
                )
            return False
        if self.ccp_client is not None:
            if not silent:
                QMessageBox.warning(self, "Zaten bağlı", "CCP bağlantısı zaten açık.")
            return True

        # Tek RX thread bu DTO ID'sine uyan mesajları ccp_queue'ya da
        # yazsın diye önce filtreyi kuruyoruz (bkz. app/can_worker.py).
        self.connection.ccp_dto_id = dto_id
        client = CCPClient(
            self.connection.bus, cro_id, dto_id, station_address=station_address,
            timeout=0.5, retries=2, dto_queue=self.connection.ccp_queue,
        )
        try:
            client.connect()
            major, minor = client.get_ccp_version()
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError) as exc:
            self.connection.ccp_dto_id = None
            self._log_event("HATA", f"CCP {'otomatik ' if silent else ''}bağlantı hatası: {exc}")
            if silent:
                self.ccp_tab.set_auto_connect_failed(str(exc))
            else:
                QMessageBox.critical(self, "CCP bağlantı hatası", str(exc))
            return False
        except Exception as exc:  # bus yazma hatası (adaptör kopmuş olabilir)
            self.connection.ccp_dto_id = None
            self._log_event("HATA", f"CCP bağlantı hatası (bus): {exc}")
            if silent:
                self.ccp_tab.set_auto_connect_failed(str(exc))
            else:
                QMessageBox.critical(self, "CCP bağlantı hatası", str(exc))
            return False

        self.ccp_client = client
        self.ccp_pool.reset()
        self._watch_fail_streak = 0
        self.ccp_tab.set_connected(True, f"(CCP v{major}.{minor})")
        self.watch_tab.set_connected(True)
        self.map_editor_tab.set_online(True)
        self._panel_conn_state()
        self._log_event(
            "CCP",
            f"CCP {'otomatik ' if silent else ''}bağlandı (CRO=0x{cro_id:X}, DTO=0x{dto_id:X}, v{major}.{minor})"
        )
        return True

    def _drop_ccp_client(self):
        """CCP istemcisini bus'a HİÇ yazmadan bırakır (adaptör kopmuşken)."""
        if self.ccp_client is not None:
            try:
                self.ccp_client.stop_listening()
            except Exception:
                pass
            self.ccp_client = None
            self._log_event("CCP", "CCP bağlantısı düştü (CAN bağlantısı koptu)")
        self.connection.ccp_dto_id = None
        self.ccp_tab.set_connected(False)
        self.watch_tab.set_connected(False)
        self.map_editor_tab.set_online(False)
        self._panel_conn_state()

    def _on_ccp_disconnect(self):
        if self.ccp_client is not None:
            try:
                self.ccp_client.disconnect()
            except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError):
                pass  # bağlantı zaten kopmuş olabilir, yine de temizle
            except Exception:
                pass  # bus yazma hatası vb.; yine de temizle
            self.ccp_client = None
            self._log_event("CCP", "CCP bağlantısı kesildi")
        self.connection.ccp_dto_id = None
        self.ccp_tab.set_connected(False)
        self.watch_tab.set_connected(False)
        self.map_editor_tab.set_online(False)
        self._panel_conn_state()

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
            size = ccp_codec.datatype_size(obj.datatype)
            raw_bytes = self.ccp_client.read_memory(
                address, size, getattr(obj, "address_extension", 0) or 0
            )
            raw_value = ccp_codec.decode_value(obj.datatype, raw_bytes, getattr(obj, "byte_order", None))
            phys_value = ccp_codec.raw_to_physical(getattr(obj, "compu_method", None), raw_value)
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError) as exc:
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
                           "(Kullanıcı / Profil sekmesinden rol seçin)."
                )
                return
        elif not can_write_calibration(self.current_role):
            self.ccp_tab.set_write_result(
                False, "Yetki yok: kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir "
                       "(Kullanıcı / Profil sekmesinden rol seçin)."
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
            old_size = ccp_codec.datatype_size(obj.datatype)
            old_raw_bytes = self.ccp_client.read_memory(
                address, old_size, getattr(obj, "address_extension", 0) or 0
            )
            old_raw = ccp_codec.decode_value(obj.datatype, old_raw_bytes, getattr(obj, "byte_order", None))
            old_phys = ccp_codec.raw_to_physical(getattr(obj, "compu_method", None), old_raw)
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
            size = ccp_codec.datatype_size(e.datatype)
            raw = self.ccp_client.read_memory(e.address, size, e.address_extension or 0)
            return ccp_codec.raw_to_physical(e.compu_method, ccp_codec.decode_value(e.datatype, raw, e.byte_order))
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError):
            return None

    def _on_watch_read(self):
        if self.ccp_client is None:
            self.watch_tab.stop_polling()
            return
        any_ok = False
        timed_out = False
        for row, e in enumerate(self.watch_tab.entries()):
            if not getattr(e, "resolved", True) or not e.datatype:
                continue
            try:
                size = ccp_codec.datatype_size(e.datatype)
                raw = self.ccp_client.read_memory(e.address, size, e.address_extension or 0)
                phys = ccp_codec.raw_to_physical(
                    e.compu_method, ccp_codec.decode_value(e.datatype, raw, e.byte_order))
            except ccp_protocol.CCPTimeoutError:
                # ECU hiç cevap vermiyor: kalan satırlar için de (her biri ~1,5 sn)
                # beklemeyip bu turu kes — aksi halde arayüz donar.
                self.watch_tab.set_row_error(row, "ECU cevap vermedi")
                timed_out = True
                break
            except (ccp_protocol.CCPError, ccp_codec.UnknownDatatypeError, ValueError) as exc:
                self.watch_tab.set_row_error(row, str(exc))
                continue
            except Exception as exc:  # bus yazma hatası (adaptör kopmuş olabilir)
                self.watch_tab.set_row_error(row, f"Okuma hatası: {exc}")
                timed_out = True
                break
            self.watch_tab.set_row_value(row, raw, phys)
            any_ok = True
        if any_ok:
            self._watch_fail_streak = 0
        elif timed_out:
            self._watch_fail_streak += 1
            if self._watch_fail_streak >= WATCH_FAIL_STREAK_LIMIT:
                self.watch_tab.stop_polling()
                self.watch_tab.set_write_result(
                    False, "ECU art arda cevap vermedi — sürekli okuma durduruldu. "
                           "CAN/CCP bağlantısını kontrol edip tekrar başlatın.")
                self._log_event("HATA", "Parametre Listesi: ECU cevap vermedi, sürekli okuma durduruldu")
                self._watch_fail_streak = 0

    def _on_watch_write(self, rows: list):
        if self.ccp_client is None:
            self.watch_tab.set_write_result(False, "CCP bağlantısı yok; önce CCP'ye bağlanın.")
            return
        if not can_write_calibration(self.current_role):
            self.watch_tab.set_write_result(
                False, "Yetki yok: kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir "
                       "(Kullanıcı / Profil sekmesinden rol seçin).")
            return
        entries = self.watch_tab.entries()
        done = 0
        problems: list[str] = []
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
                continue
            old_phys = self._read_phys_best_effort(e)
            try:
                raw_bytes = ccp_codec.encode_for_write(e, phys)
                self.ccp_client.write_memory(e.address, raw_bytes, e.address_extension or 0, verify=True)
            except ccp_protocol.CCPTimeoutError:
                problems.append(f"{e.name}: ECU cevap vermedi")
                self._log_event("HATA", f"{e.name} RAM yazma: ECU cevap vermedi")
                break  # ECU yoksa kalan satırlar için de beklemeyelim
            except (ccp_protocol.CCPError, ccp_codec.UnknownDatatypeError, ValueError) as exc:
                problems.append(f"{e.name}: {exc}")
                self._log_event("HATA", f"{e.name} RAM yazma hatası: {exc}")
                continue
            self.watch_tab.commit_written(row, phys)
            self._log_event("KALIBRASYON", f"{e.name} = {phys} {e.unit or ''} (RAM, Parametre Listesi) yazıldı")
            self.calibration_history.add(
                self.current_user, self.current_role.value, e.name, old_phys, phys, e.unit or "",
                persistent=False,
            )
            done += 1
        self.history_tab.refresh()
        if problems:
            self.watch_tab.set_write_result(
                False, f"{done} parametre yazıldı; sorunlar: " + "; ".join(problems))
        elif done:
            self.watch_tab.set_write_result(True, f"{done} parametre RAM'e yazıldı.")
        else:
            self.watch_tab.set_write_result(False, "Yazılacak (değeri değiştirilmiş) satır yok.")

    # ---- Grafik (canlı Measurement çizimi) ---------------------------------
    def _poll_items(self, names: list):
        """Ölçüm adlarını [(ad, MeasurementInfo)] listesine çevirir (adresi olanlar)."""
        summary = self.a2l_tab.db.summary
        if summary is None:
            return []
        by_name = {m.name: m for m in summary.measurements}
        return [(n, by_name[n]) for n in names if n in by_name and by_name[n].address is not None]

    def _on_ccp_unresponsive(self, flag: bool):
        if flag:
            self._log_event("CCP", "ECU CCP isteklerine yanıt vermiyor; okuma kısa süre durduruldu.")
            self.statusBar().showMessage("CCP: ECU yanıt vermiyor — okumalar duraklatıldı", 5000)
        else:
            self._log_event("CCP", "ECU yeniden yanıt veriyor.")

    def _on_graph_tick(self, names: list):
        if self.ccp_client is None:
            return

        def sink(name, value):
            try:
                self.graph_tab.append_sample(name, float(value))
            except (TypeError, ValueError):
                pass
        self.ccp_pool.submit("graph", self.ccp_client, self._poll_items(names), sink)

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
    def _send_dbc_command(self, command_name: str, cmd) -> bool:
        if not cmd.message or not cmd.signal:
            return False
        if not self.connection.is_connected:
            QMessageBox.warning(
                self, "CAN bağlantısı yok",
                f"{command_name} göndermeden önce Bağlantı sekmesinden CAN hattına bağlanın."
            )
            return False
        try:
            can_id, data, extended = self.transmit_tab.dbc.encode(cmd.message, {cmd.signal: cmd.value})
            self.connection.send(can_id, data, extended)
        except Exception as exc:  # cantools/python-can çeşitli hata tipleri fırlatabilir
            QMessageBox.critical(self, f"{command_name} gönderilemedi", str(exc))
            self._log_event("HATA", f"{command_name} gönderilemedi: {exc}")
            return False
        sent_msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=extended,
                                timestamp=time.time())
        self.monitor_tab.add_message(sent_msg, direction="TX")
        self._log_event("MOTOR", f"{command_name} gönderildi ({cmd.message}.{cmd.signal}={cmd.value})")
        return True

    def _on_motor_start(self):
        self._send_dbc_command("Motor Start", self.dashboard_tab.config.motor_start)

    def _on_motor_stop(self):
        self._send_dbc_command("Motor Stop", self.dashboard_tab.config.motor_stop)

    def _on_estop(self):
        self._send_dbc_command("ACİL STOP", self.dashboard_tab.config.estop)

    def _on_dashboard_config_saved(self, cfg):
        if self.dashboard_config_store.save(cfg):
            self._log_event("AYAR", "Ana Sayfa ayarları (DBC/A2L eşlemeleri) kaydedildi.")
        else:
            self._log_event("HATA", "Ana Sayfa ayarları DİSKE YAZILAMADI (bellekte geçerli, yeniden açınca kaybolur).")
            QMessageBox.warning(self, "Ayarlar kaydedilemedi",
                                "Ana Sayfa ayarları diske yazılamadı; program kapanınca kaybolacak.")

    def _sync_workspace_a2l(self):
        summary = self.a2l_tab.db.summary
        self.workspace_tab.set_a2l_measurements(summary.measurements if summary is not None else [])

    def _on_workspace_tick(self, names: list):
        """Çalışma Alanı'nda seçili A2L ölçümlerini CCP ile (arka planda) okuyup hub'a yazar."""
        if self.ccp_client is None:
            return
        self.ccp_pool.submit(
            "workspace", self.ccp_client, self._poll_items(names),
            lambda name, value: self.workspace_tab.push(f"a2l:{name}", value))

    def _sync_dashboard_measurements(self):
        summary = self.a2l_tab.db.summary
        self.dashboard_tab.set_measurements(summary.measurements if summary is not None else [])

    def _on_dashboard_tick(self, names: list):
        if self.ccp_client is None:
            return
        summary = self.a2l_tab.db.summary
        if summary is None:
            return
        from app.dashboard_config import AMBIENT_KEYS, GAUGE_KEYS

        name_to_key = {v: k for k, v in self.dashboard_tab.config.measurement_map().items()}
        graph_names = set(self.dashboard_tab.graph_measurement_names())
        wanted = [n for n in names if name_to_key.get(n) is not None or n in graph_names]
        items = self._poll_items(wanted)
        by_name = dict(items)

        def sink(name, phys_value):
            m = by_name[name]
            key = name_to_key.get(name)
            if name in graph_names and isinstance(phys_value, (int, float)):
                self.dashboard_tab.add_measurement_sample(name, float(phys_value))
            if key in GAUGE_KEYS:
                self.dashboard_tab.set_gauge_value(key, float(phys_value))
            elif key in AMBIENT_KEYS:
                unit = f" {m.unit}" if m.unit else ""
                text = f"{phys_value:.6g}{unit}" if isinstance(phys_value, float) else f"{phys_value}{unit}"
                self.dashboard_tab.set_ambient_value(key, text)
        self.ccp_pool.submit("dashboard", self.ccp_client, items, sink)

    # ---- Eyleyiciler (manuel override) --------------------------------------
    def _send_actuator_override(self, actuator_key: str, enable: bool, value: float):
        """DashboardTab, gating (rol kontrolü + onay diyaloğu) işini
        KENDİSİ yapar (bkz. DashboardTab._on_actuator_toggle); bu
        fonksiyon yalnızca ZATEN onaylanmış bir override isteğinin
        gerçek CAN gönderimini yapar — tıpkı _send_dbc_command gibi.
        Reuses the same DBC-encode-and-send mechanism as motor komutları."""
        from app.dashboard_config import ACTUATOR_LABELS

        cmd = self.dashboard_tab.config.actuators.get(actuator_key)
        label = ACTUATOR_LABELS.get(actuator_key, actuator_key)
        if cmd is not None and cmd.channel == "a2l":
            return self._send_actuator_override_a2l(actuator_key, cmd, label, enable, value)
        if cmd is None or not cmd.message or not cmd.enable_signal:
            self.dashboard_tab.set_actuator_feedback(actuator_key, "DBC eşlemesi tanımsız")
            return False
        if not self.connection.is_connected:
            if enable or actuator_key not in self._active_overrides:
                QMessageBox.warning(
                    self, "CAN bağlantısı yok",
                    f"{label} override göndermeden önce Bağlantı grubundan CAN hattına bağlanın."
                )
            return False
        values = {cmd.enable_signal: 1.0 if enable else 0.0}
        if cmd.value_signal:
            values[cmd.value_signal] = value
        try:
            can_id, data, extended = self.transmit_tab.dbc.encode(cmd.message, values)
            self.connection.send(can_id, data, extended)
        except Exception as exc:  # cantools/python-can çeşitli hata tipleri fırlatabilir
            QMessageBox.critical(self, f"{label} override gönderilemedi", str(exc))
            self._log_event("HATA", f"{label} override gönderilemedi: {exc}")
            return False
        if enable:
            self._active_overrides[actuator_key] = value
        else:
            self._active_overrides.pop(actuator_key, None)
        sent_msg = can.Message(arbitration_id=can_id, data=data, is_extended_id=extended,
                                timestamp=time.time())
        self.monitor_tab.add_message(sent_msg, direction="TX")
        state_text = f"override AÇIK, değer={value:g}" if enable else "override KAPALI"
        self.dashboard_tab.set_actuator_feedback(
            actuator_key, f"%{value:g}" if enable else "Kapalı"
        )
        self._log_event(
            "EYLEYICI",
            f"{label}: {state_text} ({self.current_user}/{self.current_role.value})"
        )
        return True

    def _send_actuator_override_a2l(self, actuator_key, cmd, label, enable, value):
        """A2L kanalı: override-enable ve değer değişkenlerini CCP ile yazar."""
        if not cmd.a2l_enable:
            self.dashboard_tab.set_actuator_feedback(actuator_key, "A2L eşlemesi tanımsız")
            return False
        if self.ccp_client is None:
            if enable or actuator_key not in self._active_overrides:
                QMessageBox.warning(self, "CCP bağlı değil",
                                    f"{label} A2L üzerinden yazılmadan önce CCP bağlantısı kurun.")
            return False
        summary = self.a2l_tab.db.summary
        by_name = {m.name: m for m in summary.measurements} if summary is not None else {}
        steps = []
        if enable and cmd.a2l_value:
            steps.append((cmd.a2l_value, value))        # önce değer
        steps.append((cmd.a2l_enable, 1.0 if enable else 0.0))  # sonra bayrak
        try:
            for name, v in steps:
                info = by_name.get(name)
                if info is None:
                    raise ValueError(f"A2L'de '{name}' bulunamadı")
                # kapatma (enable=False) yazımı hiçbir A2L sınırı yüzünden engellenmemeli
                cpanel.ccp_write_value(self.ccp_client, info, v, enforce_limits=enable)
        except Exception as exc:
            QMessageBox.critical(self, f"{label} override yazılamadı", str(exc))
            self._log_event("HATA", f"{label} A2L override yazılamadı: {exc}")
            return False
        if enable:
            self._active_overrides[actuator_key] = value
        else:
            self._active_overrides.pop(actuator_key, None)
        self.dashboard_tab.set_actuator_feedback(
            actuator_key, f"%{value:g}" if enable else "Kapalı")
        self._log_event(
            "EYLEYICI",
            f"{label} [A2L]: {'override AÇIK, değer=%g' % value if enable else 'override KAPALI'} "
            f"({self.current_user}/{self.current_role.value})")
        return True

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
        items = list(pt.ccp_poll_targets())

        def err(key, exc):
            if key is None:
                return
            if isinstance(exc, ccp_protocol.CCPTimeoutError):
                pt.set_ccp_error(key, "ECU cevap vermedi")
            else:
                pt.set_ccp_error(key, str(exc))
        self.ccp_pool.submit("perf", self.ccp_client, items, pt.set_ccp_value, err)

    def _panel_tx_state(self):
        self.control_panel_tab.set_tx_running(
            set(self.tx_scheduler.running_messages()), paused=self._panel_paused)

    _panel_paused = False

    def _on_panel_tx_failed(self, message: str, error: str):
        self._log_event("HATA", f"Kontrol Paneli: {message} gönderimi durdu: {error}")
        self.control_panel_tab._set_status(f"{message} gönderilemedi: {error}", False)

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
        items = [((key, kind), info) for key, kind, info in panel.ccp_poll_targets()]

        def err(tag, exc):
            if tag is None:
                return
            if isinstance(exc, ccp_protocol.CCPTimeoutError):
                panel.set_ccp_error(tag[0], "ECU cevap vermedi")
            else:
                panel.set_ccp_error(tag[0], str(exc))
        self.ccp_pool.submit("panel", self.ccp_client, items,
                             lambda tag, value: panel.set_ccp_value(tag[0], tag[1], value), err)

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
            interface=self.connection_tab.interface_combo.currentText(),
            channel=self.connection_tab.channel_edit.text().strip(),
            bitrate=self.connection_tab.baudrate_combo.currentData(),
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
            self.a2l_tab.status_label.setText(
                f"Yüklü: {os.path.basename(profile.a2l_path)}  |  Proje: {summary.project_name}"
            )
            self.a2l_tab._populate_tree(summary)
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
        try:
            self.workspace_tab.shutdown()
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("workspace shutdown hatası")
        self.ccp_pool.shutdown()
        self._on_disconnect()
        self.can_logger.stop()
        super().closeEvent(event)
