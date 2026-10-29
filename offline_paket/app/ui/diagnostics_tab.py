"""Diagnostics sekmesi (SRS Faz 4). M220 ECU'sunun kendine özel arıza
kodu/tanı protokolü bu proje kapsamında doğrulanmadığı için burada
"arıza listesi" gibi ECU'ya özel bir yorumlama YAPILMAZ — bunun yerine
CCP'nin standart TEST komutuyla bağlantı canlılığı kontrolü ve
DIAG_SERVICE için ham bir istek/cevap (passthrough) aracı sunulur.
Gerçek arıza kodu formatı netleştiğinde bu ekran üzerine inşa edilebilir.
"""

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

class DiagnosticsTab(QWidget):
    test_requested = Signal()                 # CCP TEST komutu (bağlantı canlılığı)
    diag_requested = Signal(int, bytes)        # service_number, params (<=4 bayt)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(self._build_test_group())
        layout.addWidget(self._build_diag_group())
        layout.addStretch()

    def _build_test_group(self) -> QGroupBox:
        box = QGroupBox("Bağlantı testi")
        self.test_button = QPushButton("ECU'yu Test Et")
        self.test_button.clicked.connect(self.test_requested.emit)
        self.test_result_label = QLabel("-")

        row = QHBoxLayout()
        row.addWidget(self.test_button)
        row.addWidget(self.test_result_label, stretch=1)
        box.setLayout(row)
        return box

    def _build_diag_group(self) -> QGroupBox:
        box = QGroupBox("DIAG_SERVICE")
        self.service_edit = QLineEdit("0000")
        self.service_edit.setPlaceholderText("servis no (hex)")
        self.service_edit.setMaximumWidth(160)
        self.params_edit = QLineEdit()
        self.params_edit.setPlaceholderText("hex, en fazla 4 bayt: 01 02")
        self.params_edit.setMaximumWidth(360)

        self.send_button = QPushButton("Servisi Çalıştır")
        self.send_button.clicked.connect(self._on_send_clicked)

        self.diag_result_label = QLabel("-")
        self.diag_result_label.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Servis no:", self.service_edit)
        form.addRow("Parametreler:", self.params_edit)

        self.log_table = QTableWidget(0, 5)
        self.log_table.setHorizontalHeaderLabels(
            ["Zaman", "Servis no", "Parametreler", "Cevap (hex)", "Sonuç"]
        )
        self.log_table.horizontalHeader().setStretchLastSection(True)
        self.log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.log_table.setMinimumHeight(140)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.send_button, 0, Qt.AlignLeft)
        layout.addWidget(self.diag_result_label)
        layout.addWidget(self.log_table)
        box.setLayout(layout)
        return box

    def _on_send_clicked(self):
        try:
            service_number = int(self.service_edit.text().strip().replace("0x", ""), 16)
        except ValueError:
            QMessageBox.warning(self, "Geçersiz değer", "Servis no geçerli bir hex değer değil.")
            return
        params_text = self.params_edit.text().strip()
        params = b""
        if params_text:
            try:
                params = bytes(int(b, 16) for b in params_text.split())
            except ValueError:
                QMessageBox.warning(self, "Geçersiz değer", "Parametreler geçerli hex baytlar olmalı (örn: 01 02).")
                return
            if len(params) > 4:
                QMessageBox.warning(self, "Geçersiz değer", "En fazla 4 parametre baytı girilebilir.")
                return
        self.diag_requested.emit(service_number, params)

    # ---- MainWindow'un çağırdığı erişimciler -------------------------
    def set_test_result(self, ok: bool, message: str):
        self.test_result_label.setText(message)
        self.test_result_label.setStyleSheet("color: green;" if ok else "color: #b00020;")

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
        self.diag_result_label.setStyleSheet("color: black;" if ok else "color: #b00020;")
