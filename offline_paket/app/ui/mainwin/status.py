"""Durum çubuğu ve bekleyen değişiklik şeridi (Modas tarzı): ECU durumu, ölçüm, kayıt süresi, bus yükü, çalışma tabanı ve
YAZILMAMIŞ (bekleyen) değişiklik sayısı her zaman görünür; bekleyen değişiklik varken ribbon altında tek tıkla
"ECU'ya yaz / Geri al" şeridi çıkar."""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

from app import theme
from app.ccp.worker import IDLE
from app.ui.mainwin.modas import ECU_STATES

REFRESH_MS = 500


def format_elapsed(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


class StatusMixin:

    def _build_status_widgets(self):
        sb = self.statusBar()
        self.status_labels = {}
        for key in ("ecu", "measure", "rec", "bus", "workbase", "pending"):
            lab = QLabel("")
            lab.setObjectName("statusField")
            self.status_labels[key] = lab
            sb.addPermanentWidget(lab)
        self.status_labels["pending"].setToolTip("ECU'ya yazılmamış (sarı) değişiklik sayısı")
        self.status_labels["workbase"].setToolTip("Açık proje / çalışma tabanı")
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(REFRESH_MS)
        self._status_timer.timeout.connect(self._refresh_status_widgets)
        self._status_timer.start()

    def _build_pending_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("pendingBar")
        bar.setStyleSheet(theme.paint(
            "QFrame#pendingBar { background: @@PENDING_BG@@; border-bottom: 1px solid @@MODAS_ORANGE_LINE@@; }"
            "QFrame#pendingBar QLabel { background: transparent; color: @@INK@@; font-size: 12px; font-weight: 700; }"
            "QFrame#pendingBar QPushButton { background: @@MODAS_RIBBON_BG@@; border: 1px solid @@MODAS_RIBBON_LINE@@; "
            "border-radius: 3px; padding: 1px 10px; font-size: 12px; }"
            "QFrame#pendingBar QPushButton:hover { background: @@MODAS_RIBBON_HOVER@@; border-color: @@MODAS_ORANGE_LINE@@; }"))
        lay = QHBoxLayout(bar)
        lay.setContentsMargins(10, 2, 10, 2)
        lay.setSpacing(8)
        self.pending_text = QLabel("")
        self.pending_write_button = QPushButton("ECU'ya yaz")
        self.pending_write_button.setToolTip("Bekleyen (sarı) değerleri ECU RAM'ine yazar (yedek + geri okuma doğrulamasıyla)")
        self.pending_write_button.clicked.connect(self._modas_write_pending)
        self.pending_revert_button = QPushButton("Geri al")
        self.pending_revert_button.setToolTip("Yazılmamış düzenlemeleri atar; ECU'ya hiçbir şey gönderilmez")
        self.pending_revert_button.clicked.connect(self._modas_discard_pending)
        lay.addWidget(self.pending_text)
        lay.addStretch(1)
        lay.addWidget(self.pending_write_button)
        lay.addWidget(self.pending_revert_button)
        bar.setVisible(False)
        self.pending_bar = bar
        return bar

    # ---- veri ------------------------------------------------------------------------------------
    def pending_counts(self) -> tuple[int, int]:
        """(bekleyen değer penceresi, değiştirilmiş tablo penceresi) — yalnızca YAZILMAMIŞ düzenlemeler."""
        values = sum(1 for w in self.modas_tab.value_windows() if w.has_pending)
        tables = sum(1 for t in self.modas_tab.table_windows() if t.is_modified())
        return values, tables

    def _modas_discard_pending(self):
        for w in self.modas_tab.value_windows():
            if w.has_pending:
                w.discard_pending()
        for t in self.modas_tab.table_windows():
            if t.is_modified():
                t.discard_edits()
        self.statusBar().showMessage("Bekleyen düzenlemeler atıldı (ECU'ya yazılmadı).", 3000)
        self._refresh_status_widgets()

    def _measure_detail(self, measuring: bool) -> str:
        """Ölçüm açıkken gerçek tur hızı ve atlanan okuma sayısı (geciken tur + okunamayan değer)."""
        st = self.measure_stats
        if not measuring or st.rate_hz is None:
            return ""
        skipped = f" · <b style='color:{theme.DANGER}'>atlanan {st.skipped}</b>" if st.skipped else " · atlanan 0"
        return f" · {st.rate_hz:.1f} Hz (hedef {1000 / self.modas_tab.interval_ms:.1f}){skipped}"

    def _refresh_status_widgets(self):
        labels = getattr(self, "status_labels", None)
        if not labels:
            return
        state = self.ccp_session.state
        led, text = ECU_STATES.get(state, ("off", "ÇEVRİMDIŞI"))
        color = {"on": theme.OK, "wait": theme.WARN_INK, "off": theme.DANGER}[led]
        labels["ecu"].setText(f"ECU: <b style='color:{color}'>{text}</b>")
        measuring = self.modas_tab.is_measuring
        labels["measure"].setText(f"Ölçüm: <b>{'AÇIK' if measuring else 'KAPALI'}</b>" + self._measure_detail(measuring))
        rec = self.session_recorder
        if rec.is_active:
            tag = "DURAKLATILDI" if rec.is_paused else "KAYIT"
            labels["rec"].setText(f"<b style='color:{theme.DANGER}'>● {tag} {format_elapsed(rec.elapsed_s())}</b>")
        else:
            labels["rec"].setText("Kayıt yok")
        load = self.monitor_tab.stats.bus_load_percent()
        labels["bus"].setText(f"Bus yükü: {'—' if load is None else f'{load:.1f}%'}")
        wbk = getattr(self, "_modas_workbase", None)
        labels["workbase"].setText(f"Çalışma tabanı: {wbk[0].name} / {wbk[1].name}" if wbk is not None else "Çalışma tabanı: —")
        values, tables = self.pending_counts()
        n = values + tables
        labels["pending"].setText(f"Bekleyen: <b style='color:{theme.WARN_INK if n else theme.INK}'>{n}</b>")
        for lab in labels.values():
            lab.setTextFormat(Qt.RichText)
        bar = getattr(self, "pending_bar", None)
        if bar is not None:
            bar.setVisible(n > 0)
            if n:
                parts = []
                if values:
                    parts.append(f"{values} değer")
                if tables:
                    parts.append(f"{tables} tablo")
                self.pending_text.setText(f"⚠ ECU'ya yazılmamış değişiklik: {', '.join(parts)}")
            self.pending_write_button.setEnabled(state != IDLE and self.ccp_client is not None)
