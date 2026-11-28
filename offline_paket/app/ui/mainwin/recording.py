"""Kayıt / MIL / trend yerleşimi bağlantıları: sinyaller, zamanlayıcılar, kısayollar ve mod değişimi (MainWindow'u
küçük tutmak için ayrı parça; bkz. test_main_window_logic_lives_in_area_modules)."""

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut



class RecordingMixin:

    def _wire_recording(self):
        """Veri kaydı, MIL model denetimi, tetikleyici ve parametre eşleme sinyalleri + gösterge zamanlayıcıları."""
        st = self.session_tab
        st.record_pause_requested.connect(self._on_record_pause)
        st.record_resume_requested.connect(self._on_record_resume)
        st.marker_requested.connect(self._on_record_marker)
        st.trigger_panel.config_changed.connect(self._on_trigger_config)
        self.connection_tab.mode_changed.connect(self._on_backend_mode_changed)
        self.connection_tab.manifest_requested.connect(self._on_sim_manifest_requested)
        self.a2l_tab.a2l_loaded.connect(self._apply_sim_params)
        self._init_sim_manifest()
        self.model_ctl = None
        self._model_events_seen = 0
        panel = self.dashboard_tab.sim_panel
        panel.connect_requested.connect(self._on_model_connect)
        panel.command_requested.connect(self._on_model_command)
        self._model_timer = QTimer(self)
        self._model_timer.setInterval(250)
        self._model_timer.timeout.connect(self._update_model_panel)
        self._model_timer.start()
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(500)               # yalnızca GÖSTERGE; kayıt hızı bundan bağımsızdır
        self._rec_timer.timeout.connect(self._update_rec_state)
        self._rec_timer.start()

    def _install_record_shortcuts(self):
        """Kayıt kısayolları (uygulama kapsamlı, üç tuşlu: yanlışlıkla basılmasın)."""
        st = self.session_tab

        def app_sc(seq: str, fn):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(fn)
            return sc
        self._rec_shortcuts = [
            app_sc("Ctrl+Shift+R", lambda: st._on_start() if st.start_button.isEnabled() else st._on_stop()),
            app_sc("Ctrl+Shift+P", lambda: st.pause_button.click() if st.pause_button.isEnabled() else None),
            app_sc("Ctrl+Shift+M", lambda: st.marker_button.click() if st.marker_button.isEnabled() else None),
        ]
        st.start_button.setToolTip("Kaydı başlatır (Ctrl+Shift+R)")
        st.stop_button.setToolTip("Kaydı bitirir (Ctrl+Shift+R)")
        st.pause_button.setToolTip("Kaydı duraklatır / sürdürür (Ctrl+Shift+P)")
        st.marker_button.setToolTip("Kayda olay işareti ekler (Ctrl+Shift+M)")

    def _on_backend_mode_changed(self, mode: str):
        """Mod değişince (yalnızca bağlı değilken mümkün) açık kayıt güvenle kapatılır; REAL/MIL kayıtları karışmaz."""
        self.backend_mode = mode
        self.dashboard_tab.sim_panel.setVisible(mode == "MIL")
        if self.session_recorder.is_active:
            self.session_tab._on_stop()
            self._log_event("OTURUM", f"Mod {mode} olarak değişti: açık kayıt güvenle kapatıldı")
