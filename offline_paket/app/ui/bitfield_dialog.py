from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget,
    QVBoxLayout,
)

from app.bitpack import BitFieldError, pack_fields

COLUMNS = ["İsim (opsiyonel)", "Başlangıç bit", "Uzunluk (bit)", "İşaretli mi", "Değer (decimal)"]


class BitFieldDialog(QDialog):
    """DBC yokken bile 'start bit 0 uzunluk 1', 'start bit 8 uzunluk 8' gibi
    alanları açıkça, hata yapmadan tanımlamak için. Her satır bir alan;
    en altta canlı önizleme ile sonuç byte'ları hemen görülür."""

    def __init__(self, existing_fields: list | None = None, byte_count: int = 8, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bit alanları (start bit / uzunluk / değer)")
        self.byte_count = byte_count
        self.resize(760, 320)

        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)

        add_button = QPushButton("Alan ekle")
        add_button.clicked.connect(lambda: self._add_row())
        remove_button = QPushButton("Alanı sil")
        remove_button.clicked.connect(self._remove_selected)

        buttons_row = QHBoxLayout()
        buttons_row.addWidget(add_button)
        buttons_row.addWidget(remove_button)
        buttons_row.addStretch()

        self.preview_label = QLabel(f"Önizleme: {'00 ' * byte_count}".strip())
        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #b00000;")

        dialog_buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        dialog_buttons.accepted.connect(self._on_accept)
        dialog_buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(buttons_row)
        layout.addWidget(self.table)
        layout.addWidget(self.preview_label)
        layout.addWidget(self.error_label)
        layout.addWidget(dialog_buttons)

        for field in (existing_fields or []):
            self._add_row(field)
        if not existing_fields:
            self._add_row()
        self._update_preview()

    def _add_row(self, field: dict | None = None):
        field = field or {"name": "", "start": 0, "length": 8, "signed": False, "value": 0}
        row = self.table.rowCount()
        self.table.insertRow(row)

        name_edit = QLineEdit(field.get("name", ""))
        name_edit.textChanged.connect(self._update_preview)
        self.table.setCellWidget(row, 0, name_edit)

        start_spin = QSpinBox()
        start_spin.setRange(0, self.byte_count * 8 - 1)
        start_spin.setValue(field["start"])
        start_spin.valueChanged.connect(self._update_preview)
        self.table.setCellWidget(row, 1, start_spin)

        length_spin = QSpinBox()
        length_spin.setRange(1, self.byte_count * 8)
        length_spin.setValue(field["length"])
        length_spin.valueChanged.connect(self._update_preview)
        self.table.setCellWidget(row, 2, length_spin)

        signed_check = QCheckBox()
        signed_check.setChecked(field.get("signed", False))
        signed_check.toggled.connect(self._update_preview)
        self.table.setCellWidget(row, 3, signed_check)

        value_spin = QDoubleSpinBox()
        value_spin.setDecimals(0)
        value_spin.setRange(-(2**31), 2**31 - 1)
        value_spin.setValue(field.get("value", 0))
        value_spin.valueChanged.connect(self._update_preview)
        self.table.setCellWidget(row, 4, value_spin)

    def _remove_selected(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)
        self._update_preview()

    def _collect_fields(self) -> list:
        fields = []
        for row in range(self.table.rowCount()):
            fields.append({
                "name": self.table.cellWidget(row, 0).text().strip(),
                "start": self.table.cellWidget(row, 1).value(),
                "length": self.table.cellWidget(row, 2).value(),
                "signed": self.table.cellWidget(row, 3).isChecked(),
                "value": int(self.table.cellWidget(row, 4).value()),
            })
        return fields

    def _update_preview(self, *_args):
        try:
            data = pack_fields(self._collect_fields(), self.byte_count)
            self.preview_label.setText("Önizleme: " + data.hex(" ").upper())
            self.error_label.setText("")
        except BitFieldError as exc:
            self.error_label.setText(str(exc))

    def _on_accept(self):
        try:
            pack_fields(self._collect_fields(), self.byte_count)
        except BitFieldError as exc:
            self.error_label.setText(str(exc))
            return
        self.accept()

    def fields(self) -> list:
        return self._collect_fields()
