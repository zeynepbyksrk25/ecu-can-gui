"""Test Oturumu Yönetimi (SRS Faz 4): bir test oturumunu başlatma/bitirme,
oturum boyunca oluşan olayları (bağlantı, CCP, kalibrasyon yazma vb.)
görüntüleme ve PDF test raporu oluşturma.
"""

import time

from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLineEdit,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget,
)

from app.report import build_session_report


class SessionTab(QWidget):
    def __init__(self):
        super().__init__()
        self.event_log = None  # MainWindow tarafından paylaşılır (app.eventlog.EventLog)
        self._session_name = ""
        self._operator = ""
        self._started_at: float | None = None
        self._ended_at: float | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_session_group())
        layout.addWidget(self._build_log_table(), stretch=1)

    def _build_session_group(self) -> QGroupBox:
        box = QGroupBox("Test oturumu")
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("örn. Soğutma testi #3")
        self.operator_edit = QLineEdit()
        self.operator_edit.setPlaceholderText("Operatör ismi")

        self.start_button = QPushButton("Oturumu Başlat")
        self.start_button.clicked.connect(self._on_start)
        self.stop_button = QPushButton("Oturumu Bitir")
        self.stop_button.clicked.connect(self._on_stop)
        self.stop_button.setEnabled(False)
        self.pdf_button = QPushButton("PDF Rapor Oluştur")
        self.pdf_button.clicked.connect(self._on_export_pdf)

        form = QFormLayout()
        form.addRow("Test ismi:", self.name_edit)
        form.addRow("Operatör:", self.operator_edit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        buttons.addWidget(self.pdf_button)
        buttons.addStretch()

        outer = QVBoxLayout()
        outer.addLayout(form)
        outer.addLayout(buttons)
        box.setLayout(outer)
        return box

    def _build_log_table(self) -> QGroupBox:
        box = QGroupBox("Olay günlüğü")
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Zaman", "Kullanıcı / Rol", "Kategori", "Mesaj"])
        self.table.horizontalHeader().setStretchLastSection(True)
        layout = QVBoxLayout()
        layout.addWidget(self.table)
        box.setLayout(layout)
        return box

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

    def _on_stop(self):
        if self.event_log is None:
            return
        self._ended_at = time.time()
        self.event_log.add("OTURUM", f"Oturum bitti: '{self._session_name or '(adsız)'}'")
        self.refresh_log()
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.name_edit.setEnabled(True)
        self.operator_edit.setEnabled(True)

    def refresh_log(self):
        if self.event_log is None:
            return
        entries = self.event_log.entries
        self.table.setRowCount(len(entries))
        for row, e in enumerate(entries):
            self.table.setItem(row, 0, QTableWidgetItem(time.strftime("%H:%M:%S", time.localtime(e.timestamp))))
            self.table.setItem(row, 1, QTableWidgetItem(f"{e.user} / {e.role}"))
            self.table.setItem(row, 2, QTableWidgetItem(e.category))
            self.table.setItem(row, 3, QTableWidgetItem(e.message))
        self.table.scrollToBottom()

    def _on_export_pdf(self):
        if self.event_log is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "PDF rapor kaydet", "test_raporu.pdf", "PDF (*.pdf)")
        if not path:
            return
        try:
            build_session_report(
                path, self._session_name, self._operator,
                self._started_at, self._ended_at, self.event_log,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Rapor oluşturulamadı", str(exc))
            return
        QMessageBox.information(self, "Rapor oluşturuldu", f"PDF kaydedildi:\n{path}")
