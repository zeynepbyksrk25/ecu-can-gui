from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QListWidget, QMessageBox, QPushButton,
    QSizePolicy, QSpinBox, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from app.ui.noscroll import no_wheel
from app.bitpack import BitFieldError, pack_fields
from app.dbc import DbcDatabase
from app.ui.bitfield_dialog import BitFieldDialog
from app.ui.signal_dialog import SignalInputDialog
from app.validators import validate_can_id

MODE_RAW = "Ham (hex ID + bit alanları)"
MODE_DBC = "DBC mesajı"

PERIODIC_COLUMNS = ["Aktif", "Mod", "ID / Mesaj", "Frame Type / Sinyaller",
                    "Data", "Periyot (ms)", "Durum"]


MIN_SAFE_PERIOD_MS = 5   # bunun altındaki periyotlarda kullanıcıdan onay istenir


def _empty_row_state() -> dict:
    return {"message": None, "values": {}, "bitfields": [], "dlc": 8}


class TransmitTab(QWidget):
    manual_send_requested = Signal(int, bytes, bool)              # id, data, extended
    periodic_start_requested = Signal(str, int, bytes, bool, int)  # row_key, id, data, extended, period_ms
    periodic_stop_requested = Signal(str)
    dbc_loaded = Signal()  # İzleme sekmesinin mesaj-adı filtresini güncellemesi için

    def __init__(self):
        super().__init__()
        self._row_counter = 0
        self._start_failed: dict[str, bool] = {}
        self._manual_state = _empty_row_state()
        self._periodic_state: dict = {}  # row_key -> {"message", "values", "bitfields"}

        self.dbc = DbcDatabase()

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_dbc_group())
        layout.addWidget(self._build_manual_group())
        layout.addWidget(self._build_periodic_group())

    # ---- DBC dosyası yükleme -----------------------------------------
    def _build_dbc_group(self) -> QGroupBox:
        box = QGroupBox("DBC dosyası")
        self.dbc_status_label = QLabel(
            "Yüklü DBC yok"
        )
        load_button = QPushButton("DBC Yükle...")
        load_button.clicked.connect(self._on_load_dbc)

        row = QHBoxLayout()
        row.addWidget(load_button)
        row.addWidget(self.dbc_status_label, stretch=1)
        box.setLayout(row)
        return box

    def _on_load_dbc(self):
        path, _ = QFileDialog.getOpenFileName(self, "DBC dosyası seç", "", "DBC dosyaları (*.dbc)")
        if not path:
            return
        try:
            self.dbc.load(path)
        except Exception as exc:
            QMessageBox.critical(self, "DBC yüklenemedi", str(exc))
            return

        names = self.dbc.message_names()
        self.dbc_status_label.setText(f"Yüklü: {path.split('/')[-1]}  ({len(names)} mesaj)")
        self.manual_message_combo.clear()
        self.manual_message_combo.addItems(names)
        self.dbc_loaded.emit()

    # ---- Manuel gönderim -------------------------------------------------
    def _build_manual_group(self) -> QGroupBox:
        box = QGroupBox("Manuel gönderim")

        self.manual_mode_combo = QComboBox()
        self.manual_mode_combo.addItems([MODE_RAW, MODE_DBC])
        self.manual_mode_combo.currentTextChanged.connect(self._on_manual_mode_changed)

        # -- Ham mod alanları --
        self.manual_id_edit = QLineEdit()
        self.manual_id_edit.setPlaceholderText("CAN ID (hex, örn. 100)")
        self.manual_frame_combo = QComboBox()
        self.manual_frame_combo.addItems(["Standard", "Extended"])
        manual_bitfields_button = QPushButton("Bit alanları...")
        manual_bitfields_button.clicked.connect(self._on_manual_bitfields_clicked)
        self.manual_dlc_spin = QSpinBox()
        self.manual_dlc_spin.setRange(0, 8)
        self.manual_dlc_spin.setValue(8)
        self.manual_dlc_spin.setPrefix("DLC ")
        self.manual_dlc_spin.setToolTip("Veri uzunluğu (bayt). ECU mesajı kısa tanımlıysa ona göre ayarlayın.")
        self.manual_bitfields_summary = QLabel("Alan girilmedi (data: tüm sıfır).")

        raw_row = QHBoxLayout()
        raw_row.addWidget(self.manual_id_edit)
        raw_row.addWidget(self.manual_frame_combo)
        raw_row.addWidget(manual_bitfields_button)
        raw_row.addWidget(self.manual_dlc_spin)
        raw_row.addWidget(self.manual_bitfields_summary, stretch=1)
        raw_widget = QWidget()
        raw_widget.setLayout(raw_row)

        # -- DBC mod alanları --
        self.manual_message_combo = QComboBox()
        self.manual_message_combo.currentTextChanged.connect(self._on_manual_message_changed)

        self.manual_signal_list = QListWidget()
        self.manual_signal_list.setMaximumHeight(90)
        self.manual_signal_list.setToolTip("Eklemek için bir sinyale tıklayın.")
        self.manual_signal_list.itemClicked.connect(self._on_manual_signal_picked)

        self.manual_selected_table = QTableWidget(0, 3)
        self.manual_selected_table.setHorizontalHeaderLabels(["Sinyal", "Değer", ""])
        self.manual_selected_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.manual_selected_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.manual_selected_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.manual_selected_table.verticalHeader().setVisible(False)
        self.manual_selected_table.setMaximumHeight(150)

        dbc_layout = QVBoxLayout()
        message_row = QHBoxLayout()
        message_row.addWidget(QLabel("Mesaj:"))
        message_row.addWidget(self.manual_message_combo, stretch=1)
        dbc_layout.addLayout(message_row)
        dbc_layout.addWidget(QLabel("Eklemek için bir sinyale tıklayın (girilmeyenler varsayılan/minimum değerle gider):"))
        dbc_layout.addWidget(self.manual_signal_list)
        dbc_layout.addWidget(self.manual_selected_table)
        dbc_widget = QWidget()
        dbc_widget.setLayout(dbc_layout)

        self.manual_stack = QStackedWidget()
        self.manual_stack.addWidget(raw_widget)   # index 0 = Ham
        self.manual_stack.addWidget(dbc_widget)   # index 1 = DBC
        # QStackedWidget varsayılan olarak dikeyde büyüyebilir (Grow) ve
        # kutuda kalan tüm boş alanı kendine çeker; bunu Fixed yaparak
        # engelliyoruz ki fazla boşluk periyodik tabloya gitsin.
        self.manual_stack.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        send_button = QPushButton("Gönder")
        send_button.clicked.connect(self._on_manual_send)

        top = QHBoxLayout()
        top.addWidget(QLabel("Mod:"))
        top.addWidget(self.manual_mode_combo)
        top.addStretch()
        top.addWidget(send_button)

        layout = QVBoxLayout()
        layout.addLayout(top)
        layout.addWidget(self.manual_stack)
        box.setLayout(layout)
        return box

    def _on_manual_mode_changed(self, mode: str):
        self.manual_stack.setCurrentIndex(1 if mode == MODE_DBC else 0)

    def _on_manual_message_changed(self, name: str):
        self._manual_state["message"] = name
        self._manual_state["values"] = {}
        self.manual_signal_list.clear()
        self.manual_selected_table.setRowCount(0)
        message = self.dbc.get_message(name) if name else None
        if message:
            for signal in message.signals:
                self.manual_signal_list.addItem(signal.name)

    def _on_manual_signal_picked(self, item):
        signal_name = item.text()
        if signal_name in self._manual_state["values"]:
            return  # zaten eklenmiş, tekrar ekleme

        message = self.dbc.get_message(self.manual_message_combo.currentText())
        signal = next((s for s in message.signals if s.name == signal_name), None)
        default_value = signal.minimum if (signal and signal.minimum is not None) else 0.0
        self._manual_state["values"][signal_name] = default_value

        row = self.manual_selected_table.rowCount()
        self.manual_selected_table.insertRow(row)
        self.manual_selected_table.setItem(row, 0, QTableWidgetItem(signal_name))

        value_spin = QDoubleSpinBox()
        minimum = signal.minimum if (signal and signal.minimum is not None) else -1_000_000.0
        maximum = signal.maximum if (signal and signal.maximum is not None) else 1_000_000.0
        value_spin.setRange(minimum, maximum)
        value_spin.setDecimals(4)
        if signal and signal.unit:
            value_spin.setSuffix(f" {signal.unit}")
        value_spin.setValue(default_value)
        value_spin.valueChanged.connect(
            lambda v, name=signal_name: self._manual_state["values"].__setitem__(name, v)
        )
        self.manual_selected_table.setCellWidget(row, 1, value_spin)

        remove_button = QPushButton("×")
        remove_button.setFixedWidth(28)
        remove_button.clicked.connect(lambda _=False, name=signal_name: self._remove_manual_signal(name))
        self.manual_selected_table.setCellWidget(row, 2, remove_button)

    def _remove_manual_signal(self, signal_name: str):
        self._manual_state["values"].pop(signal_name, None)
        for row in range(self.manual_selected_table.rowCount()):
            if self.manual_selected_table.item(row, 0).text() == signal_name:
                self.manual_selected_table.removeRow(row)
                break

    def _on_manual_bitfields_clicked(self):
        dialog = BitFieldDialog(self._manual_state["bitfields"], parent=self)
        if dialog.exec():
            self._manual_state["bitfields"] = dialog.fields()
            count = len(self._manual_state["bitfields"])
            self.manual_bitfields_summary.setText(
                f"{count} alan tanımlı." if count else "Alan girilmedi (data: tüm sıfır)."
            )

    def _on_manual_send(self):
        self._manual_state["dlc"] = self.manual_dlc_spin.value()
        try:
            can_id, data, extended = self._resolve_frame(
                mode=self.manual_mode_combo.currentText(),
                id_edit=self.manual_id_edit,
                frame_combo=self.manual_frame_combo,
                state=self._manual_state,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Geçersiz girdi", str(exc))
            return
        self.manual_send_requested.emit(can_id, data, extended)

    def _resolve_frame(self, mode, id_edit, frame_combo, state):
        """Ham ve DBC modlarının ortak çıkışı: (can_id, data, extended).
        state = {"message", "values", "bitfields"} (satıra veya manuel bloğa ait)."""
        if mode == MODE_DBC:
            if not self.dbc.is_loaded:
                raise ValueError("Önce bir DBC dosyası yükleyin.")
            if not state["message"]:
                raise ValueError("Bir DBC mesajı seçin.")
            return self.dbc.encode(state["message"], state["values"])

        extended = frame_combo.currentText() == "Extended"
        can_id = validate_can_id(id_edit.text(), extended)
        try:
            data = pack_fields(state["bitfields"], state.get("dlc", 8))
        except BitFieldError as exc:
            raise ValueError(str(exc))
        return can_id, data, extended

    # ---- Periyodik gönderim ----------------------------------------------
    def _build_periodic_group(self) -> QGroupBox:
        box = QGroupBox("Periyodik gönderim")

        self.periodic_table = QTableWidget(0, len(PERIODIC_COLUMNS))
        self.periodic_table.setHorizontalHeaderLabels(PERIODIC_COLUMNS)
        header = self.periodic_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(110)
        header.setTextElideMode(Qt.ElideNone)
        self.periodic_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.periodic_table.resizeColumnsToContents()

        add_button = QPushButton("Satır ekle")
        add_button.clicked.connect(self.add_row)
        remove_button = QPushButton("Satırı sil")
        remove_button.clicked.connect(self._remove_selected_row)

        buttons = QHBoxLayout()
        buttons.addWidget(add_button)
        buttons.addWidget(remove_button)
        buttons.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(buttons)
        layout.addWidget(self.periodic_table)
        box.setLayout(layout)
        return box

    def add_row(self):
        row = self.periodic_table.rowCount()
        self.periodic_table.insertRow(row)
        self._row_counter += 1
        row_key = f"row_{self._row_counter}"
        self._periodic_state[row_key] = _empty_row_state()

        key_item = QTableWidgetItem()
        key_item.setData(Qt.UserRole, row_key)
        self.periodic_table.setItem(row, 0, key_item)

        active_checkbox = QCheckBox()
        active_checkbox.toggled.connect(
            lambda checked, k=row_key: self._on_row_toggled(self._row_of(k), checked))
        self.periodic_table.setCellWidget(row, 0, active_checkbox)

        mode_combo = QComboBox()
        mode_combo.addItems([MODE_RAW, MODE_DBC])
        mode_combo.currentTextChanged.connect(
            lambda mode, k=row_key: self._set_row_mode(self._row_of(k), mode))
        self.periodic_table.setCellWidget(row, 1, mode_combo)

        period_spin = no_wheel(QSpinBox())
        period_spin.setRange(1, 60_000)
        period_spin.setValue(100)
        period_spin.setSuffix(" ms")
        self.periodic_table.setCellWidget(row, 5, period_spin)

        status_label = QLabel("Durduruldu")
        self.periodic_table.setCellWidget(row, 6, status_label)

        self._set_row_mode(row, MODE_RAW)
        self.periodic_table.resizeColumnsToContents()

    def _row_key(self, row: int) -> str:
        return self.periodic_table.item(row, 0).data(Qt.UserRole)

    def _row_of(self, row_key: str) -> int:
        """Satırın GÜNCEL indeksi. Satır silinince indeksler kayar; bu yüzden
        widget bağlantıları sabit indeks değil satır anahtarı taşır. -1: yok."""
        for r in range(self.periodic_table.rowCount()):
            item = self.periodic_table.item(r, 0)
            if item is not None and item.data(Qt.UserRole) == row_key:
                return r
        return -1

    def _set_row_mode(self, row: int, mode: str):
        """'ID / Mesaj', 'Frame Type / Sinyaller' ve 'Data' hücrelerini
        seçilen moda göre yeniden kurar (Ham <-> DBC)."""
        if row < 0:
            return
        row_key = self._row_key(row)

        if mode == MODE_RAW:
            id_edit = QLineEdit("100")
            id_edit.setPlaceholderText("hex, örn. 100")
            self.periodic_table.setCellWidget(row, 2, id_edit)

            frame_combo = QComboBox()
            frame_combo.addItems(["Standard", "Extended"])
            self.periodic_table.setCellWidget(row, 3, frame_combo)

            bitfields_button = QPushButton("Bit alanları...")
            bitfields_button.setObjectName("bitfields_button")
            bitfields_button.clicked.connect(
                lambda _=False, k=row_key: self._on_periodic_bitfields_clicked(self._row_of(k)))
            dlc_spin = no_wheel(QSpinBox())
            dlc_spin.setObjectName("dlc_spin")
            dlc_spin.setRange(0, 8)
            dlc_spin.setValue(self._periodic_state[row_key].get("dlc", 8))
            dlc_spin.setPrefix("DLC ")
            dlc_spin.setToolTip("Veri uzunluğu (bayt). ECU mesajı kısa tanımlıysa ona göre ayarlayın.")
            dlc_spin.valueChanged.connect(
                lambda v, k=row_key: self._periodic_state.get(k, {}).__setitem__("dlc", int(v)))
            cell = QWidget()
            cell_lay = QHBoxLayout(cell)
            cell_lay.setContentsMargins(0, 0, 0, 0)
            cell_lay.addWidget(bitfields_button)
            cell_lay.addWidget(dlc_spin)
            self.periodic_table.setCellWidget(row, 4, cell)
        else:
            message_combo = QComboBox()
            message_combo.addItems(self.dbc.message_names())
            message_combo.currentTextChanged.connect(
                lambda name, k=row_key: self._on_periodic_message_changed(self._row_of(k), name)
            )
            self.periodic_table.setCellWidget(row, 2, message_combo)

            signals_button = QPushButton("Sinyaller...")
            signals_button.clicked.connect(
                lambda _=False, k=row_key: self._on_periodic_signals_clicked(self._row_of(k)))
            self.periodic_table.setCellWidget(row, 3, signals_button)

            preview_label = QLabel("DBC'den otomatik")
            self.periodic_table.setCellWidget(row, 4, preview_label)

            if message_combo.count():
                self._periodic_state[row_key]["message"] = message_combo.currentText()

        self.periodic_table.resizeColumnsToContents()

    def _on_periodic_message_changed(self, row: int, name: str):
        if row < 0:
            return
        row_key = self._row_key(row)
        self._periodic_state[row_key] = {"message": name, "values": {}, "bitfields": []}

    def _on_periodic_signals_clicked(self, row: int):
        if row < 0:
            return
        row_key = self._row_key(row)
        state = self._periodic_state[row_key]
        message = self.dbc.get_message(state["message"]) if state["message"] else None
        if message is None:
            QMessageBox.warning(self, "Mesaj seçilmedi", "Önce bu satır için bir DBC mesajı seçin.")
            return
        dialog = SignalInputDialog(message, state["values"], parent=self)
        if dialog.exec():
            state["values"] = dialog.values()

    def _on_periodic_bitfields_clicked(self, row: int):
        if row < 0:
            return
        row_key = self._row_key(row)
        state = self._periodic_state[row_key]
        row_cb = self.periodic_table.cellWidget(row, 0)
        if row_cb is not None and row_cb.isChecked():
            QMessageBox.information(self, "Satır çalışıyor",
                                    "Çalışan satırın bit alanları değiştirilemez; önce satırı durdurun.")
            return
        dialog = BitFieldDialog(state["bitfields"], parent=self)
        if dialog.exec():
            state["bitfields"] = dialog.fields()
            button = self.periodic_table.cellWidget(row, 4).findChild(QPushButton, "bitfields_button")
            count = len(state["bitfields"])
            button.setText(f"Bit alanları... ({count})" if count else "Bit alanları...")

    def _on_row_toggled(self, row: int, checked: bool):
        if row < 0:
            return
        row_key = self._row_key(row)
        mode_combo = self.periodic_table.cellWidget(row, 1)
        period_spin = self.periodic_table.cellWidget(row, 5)
        status_label = self.periodic_table.cellWidget(row, 6)

        if checked:
            try:
                mode = mode_combo.currentText()
                state = self._periodic_state[row_key]
                if mode == MODE_DBC:
                    can_id, data, extended = self._resolve_frame(
                        mode=MODE_DBC, id_edit=None, frame_combo=None, state=state,
                    )
                else:
                    id_edit = self.periodic_table.cellWidget(row, 2)
                    frame_combo = self.periodic_table.cellWidget(row, 3)
                    can_id, data, extended = self._resolve_frame(
                        mode=MODE_RAW, id_edit=id_edit, frame_combo=frame_combo, state=state,
                    )
            except ValueError as exc:
                QMessageBox.warning(self, "Geçersiz girdi", str(exc))
                self.periodic_table.cellWidget(row, 0).setChecked(False)
                return

            if period_spin.value() < MIN_SAFE_PERIOD_MS:
                ans = QMessageBox.question(
                    self, "Çok kısa periyot",
                    f"{period_spin.value()} ms periyot hattı yoğun şekilde doldurabilir ve ECU'yu etkileyebilir. "
                    f"Devam edilsin mi?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
                if ans != QMessageBox.Yes:
                    checkbox = self.periodic_table.cellWidget(row, 0)
                    checkbox.blockSignals(True)
                    checkbox.setChecked(False)
                    checkbox.blockSignals(False)
                    return
            self.periodic_start_requested.emit(row_key, can_id, data, extended, period_spin.value())
            if self._start_failed.pop(row_key, False):
                # MainWindow gönderimi reddetti (rol/bağlantı/hata): satır çalışıyor GÖSTERİLMEZ.
                checkbox = self.periodic_table.cellWidget(row, 0)
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                return
            status_label.setText("Çalışıyor")
            mode_combo.setEnabled(False)
            period_spin.setEnabled(False)
            self.periodic_table.cellWidget(row, 2).setEnabled(False)
            self.periodic_table.cellWidget(row, 3).setEnabled(False)
        else:
            self.periodic_stop_requested.emit(row_key)
            status_label.setText("Durduruldu")
            mode_combo.setEnabled(True)
            period_spin.setEnabled(True)
            self.periodic_table.cellWidget(row, 2).setEnabled(True)
            self.periodic_table.cellWidget(row, 3).setEnabled(True)

    def mark_start_failed(self, row_key: str):
        """MainWindow, periyodik gönderimi başlatamadığında çağırır."""
        self._start_failed[row_key] = True

    def _remove_selected_row(self):
        row = self.periodic_table.currentRow()
        if row < 0:
            return
        checkbox = self.periodic_table.cellWidget(row, 0)
        row_key = self._row_key(row)
        if checkbox is not None and checkbox.isChecked():
            self.periodic_stop_requested.emit(row_key)
        self._periodic_state.pop(row_key, None)
        self._start_failed.pop(row_key, None)
        self.periodic_table.removeRow(row)

    def stop_all_rows(self):
        """Bağlantı kesildiğinde tüm periyodik gönderimleri arayüzde de durdurulmuş göster."""
        for row in range(self.periodic_table.rowCount()):
            checkbox = self.periodic_table.cellWidget(row, 0)
            if checkbox is not None and checkbox.isChecked():
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                self.periodic_table.cellWidget(row, 6).setText("Durduruldu")
                # Başlatırken kilitlenen alanlar yeniden düzenlenebilir olsun
                for col in (1, 2, 3, 5):
                    widget = self.periodic_table.cellWidget(row, col)
                    if widget is not None:
                        widget.setEnabled(True)
