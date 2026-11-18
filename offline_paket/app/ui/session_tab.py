"""Test Oturumu Yönetimi (SRS Faz 4): bir test oturumunu başlatma/bitirme,
oturum boyunca oluşan olayları (bağlantı, CCP, kalibrasyon yazma vb.)
görüntüleme ve PDF test raporu oluşturma.
"""

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from app.report import build_session_report
from app.ui.dash_widgets import make_card
from app.ui.event_log_table import EventLogTable


class SessionTab(QWidget):
    session_started = Signal(str, str)     # test ismi, operatör
    session_stopped = Signal()
    excel_requested = Signal()             # elle Excel'e aktar (MainWindow dosyayı yazar)

    def __init__(self):
        super().__init__()
        self.event_log = None  # MainWindow tarafından paylaşılır (app.eventlog.EventLog)
        self._session_name = ""
        self._operator = ""
        self._started_at: float | None = None
        self._ended_at: float | None = None
        self.trend_provider = None      # MainWindow: callable -> (veri, olaylar) (Canlı Trendler anlık görüntüsü)
        self._trend_snapshot = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)
        layout.addWidget(self._build_session_card())
        layout.addWidget(self._build_log_card(), stretch=1)

    def _build_session_card(self):
        card, v, head = make_card("Test oturumu", "flag")
        self.state_chip = QLabel("Oturum yok")
        self.state_chip.setObjectName("chipDim")
        head.addWidget(self.state_chip)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("örn. Soğutma testi #3")
        self.operator_edit = QLineEdit()
        self.operator_edit.setPlaceholderText("Operatör ismi")
        self.start_button = QPushButton("Oturumu Başlat")
        self.start_button.setProperty("tone", "go")
        self.start_button.clicked.connect(self._on_start)
        self.stop_button = QPushButton("Oturumu Bitir")
        self.stop_button.clicked.connect(self._on_stop)
        self.stop_button.setEnabled(False)
        self.pdf_button = QPushButton("PDF Rapor Oluştur")
        self.pdf_button.clicked.connect(self._on_export_pdf)
        self.excel_button = QPushButton("Excel'e Aktar")
        self.excel_button.setToolTip("Olay günlüğü, kalibrasyon yazımları ve son parametre kaydını Excel (.xlsx) "
                                     "dosyası olarak BİLGİSAYARA kaydeder (ECU'ya hiçbir şey yazılmaz).")
        self.excel_button.clicked.connect(self.excel_requested.emit)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(6)
        for col, text in ((0, "TEST İSMİ"), (1, "OPERATÖR")):
            lab = QLabel(text)
            lab.setObjectName("colHead")
            grid.addWidget(lab, 0, col)
        grid.addWidget(self.name_edit, 1, 0)
        grid.addWidget(self.operator_edit, 1, 1)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.pdf_button)
        buttons.addWidget(self.excel_button)
        grid.addLayout(buttons, 1, 2)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        v.addLayout(grid)
        self.record_label = QLabel("Parametre kaydı: oturum başlayınca izlenen değerler CSV'ye yazılır.")
        self.record_label.setObjectName("colHead")
        self.record_label.setWordWrap(True)
        self.record_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self.record_label)
        return card

    def set_record_info(self, text: str):
        self.record_label.setText(text)

    def _build_log_card(self):
        card, v, _head = make_card("Olay günlüğü", "trend")
        self.log_table = EventLogTable()
        self.table = self.log_table.table      # eski erişim yolu
        v.addWidget(self.log_table, 1)
        return card

    def _on_start(self):
        if self.event_log is None:
            return
        self._session_name = self.name_edit.text().strip()
        self._operator = self.operator_edit.text().strip()
        self._started_at = time.time()
        self._ended_at = None
        self.event_log.add(
            "OTURUM", f"Oturum başladı: '{self._session_name or '(adsız)'}' (operatör: {self._operator or '-'})"
        )
        self.refresh_log()
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.name_edit.setEnabled(False)
        self.operator_edit.setEnabled(False)
        self.session_started.emit(self._session_name, self._operator)
        self._set_chip(f"● Oturum açık · {time.strftime('%H:%M', time.localtime(self._started_at))}'den beri", True)

    def _on_stop(self):
        if self.event_log is None:
            return
        self._ended_at = time.time()
        self._trend_snapshot = self._take_trend()     # PDF sonradan üretilse de 1 saatlik tampon düşmesin
        self.event_log.add("OTURUM", f"Oturum bitti: '{self._session_name or '(adsız)'}'")
        self.refresh_log()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.name_edit.setEnabled(True)
        self.operator_edit.setEnabled(True)
        self.session_stopped.emit()
        self._set_chip("Oturum bitti", False)

    def _set_chip(self, text: str, active: bool):
        self.state_chip.setText(text)
        self.state_chip.setObjectName("chipGreen" if active else "chipDim")
        self.state_chip.style().unpolish(self.state_chip)
        self.state_chip.style().polish(self.state_chip)

    def refresh_log(self):
        if self.event_log is None:
            return
        self.log_table.set_entries(self.event_log.entries)

    def _take_trend(self):
        if self.trend_provider is None:
            return None
        try:
            return self.trend_provider()
        except Exception:  # noqa: BLE001 - grafik alınamazsa rapor yine de üretilsin
            return None

    def _on_export_pdf(self):
        if self.event_log is None:
            return
        path, _ = QFileDialog.getSaveFileName(self.window(), "PDF rapor kaydet", "test_raporu.pdf", "PDF (*.pdf)")
        if not path:
            return
        trend = self._trend_snapshot if self._ended_at else self._take_trend()
        try:
            build_session_report(
                path, self._session_name, self._operator,
                self._started_at, self._ended_at, self.event_log, trend_data=trend,
            )
        except Exception as exc:
            QMessageBox.critical(self.window(), "Rapor oluşturulamadı", str(exc))
            return
        QMessageBox.information(self.window(), "Rapor oluşturuldu", f"PDF kaydedildi:\n{path}")
