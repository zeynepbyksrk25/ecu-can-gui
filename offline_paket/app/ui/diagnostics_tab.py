"""Diagnostics (SRS Faz 4). M220 ECU'sunun kendine özel arıza kodu/tanı protokolü bu proje kapsamında
doğrulanmadığı için burada ECU'ya özel bir yorumlama YAPILMAZ — bunun yerine CCP'nin standart TEST
komutuyla bağlantı canlılığı kontrolü ve DIAG_SERVICE için ham bir istek/cevap (passthrough) aracı sunulur.
Koyu tema: "Bağlantı testi" ve "DIAG_SERVICE" kartları."""

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget,
)

from app.ui.dash_widgets import make_card


class DiagnosticsTab(QWidget):
    test_requested = Signal()                 # CCP TEST komutu (bağlantı canlılığı)
    diag_requested = Signal(int, bytes)        # service_number, params (<=4 bayt)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(self._build_test_card())
        layout.addWidget(self._build_diag_card(), 1)

    def _build_test_card(self):
        card, v, _head = make_card("CCP bağlantı testi", "gauge")
        self.test_button = QPushButton("ECU'yu Test Et")
        self.test_button.setProperty("tone", "go")
        self.test_button.clicked.connect(self.test_requested.emit)
        self.test_result_label = QLabel("-")
        self.test_result_label.setObjectName("mutedSmall")
        self.test_result_label.setWordWrap(True)
        row = QHBoxLayout()
        row.setSpacing(12)
        row.addWidget(self.test_button)
        row.addWidget(self.test_result_label, stretch=1)
        v.addLayout(row)
        return card

    def _build_diag_card(self):
        card, v, _head = make_card("DIAG_SERVICE", "settings")
        self.service_edit = QLineEdit("0000")
        self.service_edit.setPlaceholderText("servis no (hex)")
        self.service_edit.setMaximumWidth(160)
        self.params_edit = QLineEdit()
        self.params_edit.setPlaceholderText("hex, en fazla 4 bayt: 01 02")
        self.params_edit.setMaximumWidth(360)
        self.send_button = QPushButton("Servisi Çalıştır")
        self.send_button.clicked.connect(self._on_send_clicked)
        self.diag_result_label = QLabel("-")
        self.diag_result_label.setObjectName("mutedSmall")
        self.diag_result_label.setWordWrap(True)

        form = QFormLayout()
        form.setHorizontalSpacing(12)
        form.addRow("Servis no:", self.service_edit)
        form.addRow("Parametreler:", self.params_edit)
        top = QHBoxLayout()
        top.addLayout(form)
        top.addWidget(self.send_button, 0, Qt.AlignBottom)
        top.addStretch(1)

        self.log_table = QTableWidget(0, 5)
        self.log_table.setHorizontalHeaderLabels(["Zaman", "Servis no", "Parametreler", "Cevap (hex)", "Sonuç"])
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.log_table.verticalHeader().setVisible(False)
        self.log_table.setAlternatingRowColors(True)
        self.log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.log_table.setMinimumHeight(120)

        v.addLayout(top)
        v.addWidget(self.diag_result_label)
        v.addWidget(self.log_table, 1)
        return card

    def _on_send_clicked(self):
        try:
            service_number = int(self.service_edit.text().strip().replace("0x", ""), 16)
        except ValueError:
            QMessageBox.warning(self.window(), "Geçersiz değer", "Servis no geçerli bir hex değer değil.")
            return
        params_text = self.params_edit.text().strip()
        params = b""
        if params_text:
            try:
                params = bytes(int(b, 16) for b in params_text.split())
            except ValueError:
                QMessageBox.warning(self.window(), "Geçersiz değer", "Parametreler geçerli hex baytlar olmalı (örn: 01 02).")
                return
            if len(params) > 4:
                QMessageBox.warning(self.window(), "Geçersiz değer", "En fazla 4 parametre baytı girilebilir.")
                return
        self.diag_requested.emit(service_number, params)

    # ---- MainWindow'un çağırdığı erişimciler -------------------------
    @staticmethod
    def _restyle(label: QLabel, name: str):
        label.setObjectName(name)
        label.style().unpolish(label)
        label.style().polish(label)

    def set_test_result(self, ok: bool, message: str):
        self.test_result_label.setText(message)
        self._restyle(self.test_result_label, "chipGreen" if ok else "chipBad")

    def add_diag_log(self, service_number: int, params: bytes, data: bytes | None, error: str = ""):
        """Her DIAG_SERVICE çağrısını (başarılı/hatalı) listeye ekler."""
        row = self.log_table.rowCount()
        self.log_table.insertRow(row)
        if data is not None:
            words = [int.from_bytes(data[i:i + 2], "little") for i in (0, 2) if len(data) >= i + 2]
            result = "Tamam  (LE 16-bit: " + ", ".join(f"{w} / 0x{w:04X}" for w in words) + ")"
        else:
            result = f"HATA: {error}"
        cells = [time.strftime("%H:%M:%S"), f"0x{service_number:04X}", params.hex(" ") or "-",
                 data.hex(" ") if data is not None else "-", result]
        for col, text in enumerate(cells):
            self.log_table.setItem(row, col, QTableWidgetItem(text))
        self.log_table.scrollToBottom()

    def set_diag_result(self, text: str, ok: bool = True):
        self.diag_result_label.setText(text)
        self._restyle(self.diag_result_label, "okSmall" if ok else "errSmall")
