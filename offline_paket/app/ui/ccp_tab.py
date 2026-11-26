"""CCP (kalibrasyon) sekmesi: CCP CONNECT/DISCONNECT kontrolü ve A2L
nesne tarayıcısı üzerinden canlı Measurement okuma / Characteristic
okuma-yazma.

Gerçek CAN/CCP işlemleri (client.connect(), upload(), write_memory()...)
burada YAPILMAZ — bu widget sadece isteği sinyal olarak dışarı bildirir;
MainWindow CCPClient'ı çağırıp sonucu set_* metotlarıyla geri bildirir.
Bu, projenin geri kalanındaki (ConnectionTab, TransmitTab...) tasarım
düzenine uyar ve CCP client'ın tek bir yerde (MainWindow) yaşamasını
sağlar.
"""

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from app import theme
from app.ui.dash_widgets import make_card
from app.ui.a2l_tree import ROLE_OBJECT, filter_tree, measurements_root, new_tree, payload_item  # noqa: F401 (ROLE_OBJECT: eski içe aktarma yolu)

POLL_INTERVAL_MS = 250   # seçili nesne HER ZAMAN canlı okunur (önbellekten; bloklamaz)


class CCPTab(QWidget):
    connect_requested = Signal(int, int, int)   # cro_id, dto_id, station_address
    disconnect_requested = Signal()
    read_requested = Signal()                   # o an seçili nesneyi oku
    write_requested = Signal(bool)               # persistent mi (Kalıcı Kaydet)?
    open_in_modas_requested = Signal(object)  # dizi/tablo nesnesini Worksheets (Modas) sayfasında aç

    def __init__(self):
        super().__init__()
        self.a2l_db = None  # MainWindow tarafından A2LTab.db ile paylaşılır
        self._selected = None  # ("measurement"|"characteristic", info_obj)

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_connection_group())

        browser_row = QHBoxLayout()
        browser_row.addWidget(self._build_tree_panel(), stretch=1)
        browser_row.addWidget(self._build_value_panel(), stretch=1)
        layout.addLayout(browser_row, stretch=1)

        self._session_active = False
        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self.read_requested.emit)

    # ---- Bağlantı -------------------------------------------------------
    def _build_connection_group(self) -> QWidget:
        box, body, _head = make_card("CCP bağlantısı", "spark")

        self.cro_edit = QLineEdit("6F9")
        self.dto_edit = QLineEdit("6F8")
        self.station_edit = QLineEdit("0000")
        for edit in (self.cro_edit, self.dto_edit, self.station_edit):
            edit.setPlaceholderText("hex")

        self.connect_button = QPushButton("CCP Bağlan")
        self.disconnect_button = QPushButton("CCP Bağlantıyı Kes")
        self.disconnect_button.setEnabled(False)
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.disconnect_button.clicked.connect(self.disconnect_requested.emit)

        self.status_label = QLabel("● CCP bağlı değil")
        self.status_label.setStyleSheet(f"color: {theme.DANGER}; font-weight: bold;")

        # CAN hattına bağlanınca CCP'yi de otomatik bağlamak için. Manuel
        # "CCP Bağlan" / "CCP Bağlantıyı Kes" düğmeleri bundan bağımsız
        # olarak her zaman kullanılabilir.
        self.auto_connect_checkbox = QCheckBox("CAN'a bağlanınca CCP'yi otomatik bağla")
        self.auto_connect_checkbox.setChecked(True)
        self.auto_connect_checkbox.setToolTip(
            "İşaretliyse, CAN Monitor sekmesinden CAN hattına bağlandığınızda "
            "CCP bağlantısı da (yukarıdaki CRO/DTO/istasyon ile) kendiliğinden "
            "kurulur. ECU cevap vermezse sessizce vazgeçilir; yine de "
            "aşağıdaki düğmelerle elle bağlanıp kesebilirsiniz."
        )

        form = QFormLayout()
        form.addRow("CRO ID (Master→Slave):", self.cro_edit)
        form.addRow("DTO ID (Slave→Master):", self.dto_edit)
        form.addRow("İstasyon adresi:", self.station_edit)

        buttons = QHBoxLayout()
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)
        buttons.addStretch()
        buttons.addWidget(self.status_label)

        outer = QVBoxLayout()
        outer.addLayout(form)
        outer.addWidget(self.auto_connect_checkbox)
        outer.addLayout(buttons)
        body.addLayout(outer)
        return box

    def auto_connect_enabled(self) -> bool:
        return self.auto_connect_checkbox.isChecked()

    def parsed_connection_params(self):
        """(cro_id, dto_id, istasyon) döner; geçersizse ValueError."""
        return (
            self._parse_hex(self.cro_edit.text(), "CRO ID"),
            self._parse_hex(self.dto_edit.text(), "DTO ID"),
            self._parse_hex(self.station_edit.text(), "İstasyon adresi"),
        )

    @staticmethod
    def _parse_hex(text: str, field_name: str) -> int:
        text = text.strip().replace("0x", "").replace("0X", "")
        try:
            return int(text, 16)
        except ValueError:
            raise ValueError(f"{field_name} geçerli bir onaltılık (hex) değer değil: {text!r}")

    def _on_connect_clicked(self):
        try:
            cro_id = self._parse_hex(self.cro_edit.text(), "CRO ID")
            dto_id = self._parse_hex(self.dto_edit.text(), "DTO ID")
            station = self._parse_hex(self.station_edit.text(), "İstasyon adresi")
        except ValueError as exc:
            QMessageBox.warning(self, "Geçersiz değer", str(exc))
            return
        self.connect_requested.emit(cro_id, dto_id, station)

    def set_connected(self, connected: bool, info: str = ""):
        self.connect_button.setEnabled(not connected)
        self.disconnect_button.setEnabled(connected)
        self.cro_edit.setEnabled(not connected)
        self.dto_edit.setEnabled(not connected)
        self.station_edit.setEnabled(not connected)
        if connected:
            self.status_label.setText(f"● CCP bağlı  {info}".rstrip())
            self.status_label.setStyleSheet(f"color: {theme.OK}; font-weight: bold;")
        else:
            self.status_label.setText("● CCP bağlı değil")
            self.status_label.setStyleSheet(f"color: {theme.DANGER}; font-weight: bold;")
            self._session_active = False
            self._update_live()

    def set_session_state(self, state: str, text: str):
        """Arka plan CCP oturumunun durumu (idle/connecting/online/lost; bkz. app/ccp/worker.py):
        düğmeler ve durum etiketi buna göre. Bağlanırken 'Bağlantıyı kes' aynı zamanda iptaldir."""
        active = state != "idle"
        self._session_active = state in ("online", "lost")
        self.connect_button.setEnabled(not active)
        self.disconnect_button.setEnabled(active)
        for w in (self.cro_edit, self.dto_edit, self.station_edit):
            w.setEnabled(not active)
        color = {"idle": theme.DANGER, "connecting": theme.WARN_INK, "online": theme.OK, "lost": theme.DANGER}[state]
        self.status_label.setText(f"● {text}")
        self.status_label.setStyleSheet(f"color: {color}; font-weight: bold;")
        self._update_live()

    def set_auto_connect_failed(self, message: str):
        self.status_label.setText(f"● CCP otomatik bağlanamadı: {message}")
        self.status_label.setStyleSheet(f"color: {theme.WARN_INK}; font-weight: bold;")

    # ---- Nesne tarayıcı ---------------------------------------------------
    def _build_tree_panel(self) -> QWidget:
        box, body, _head = make_card("Nesne tarayıcı (A2L)", "sliders")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("İsme göre ara...")
        self.search_edit.textChanged.connect(self._apply_filter)

        self.tree = new_tree(self._on_item_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.search_edit)
        layout.addWidget(self.tree)
        body.addLayout(layout, 1)
        return box

    def refresh_objects(self):
        # Yeni A2L yüklendi: eski nesne (eski adres!) seçili kalmamalı; aksi
        # halde Yaz/Oku düğmeleri önceki revizyonun adresini kullanırdı.
        self._selected = None
        self.poll_checkbox.setChecked(False)
        self.poll_checkbox.setEnabled(False)
        self.read_button.setEnabled(False)
        self.flash_enable_checkbox.setChecked(False)
        self._set_write_enabled(False)
        self.tree.clear()
        if self.a2l_db is None or self.a2l_db.summary is None:
            return
        summary = self.a2l_db.summary

        self.tree.addTopLevelItem(measurements_root("Measurements (salt okunur)", summary.measurements))

        # Değiştirilebilir (tuneable) ve salt okunur Characteristic'leri ayrı
        # alt gruplarda gösteriyoruz — kullanıcının hangi parametreleri
        # değiştirebileceğini, hangilerini sadece görüntüleyebileceğini tek
        # bakışta ayırt edebilmesi için.
        characteristics_root = QTreeWidgetItem(["Characteristics (kalibrasyon)"])
        tuneable_root = QTreeWidgetItem(["Değiştirilebilir (tuneable)"])
        readonly_root = QTreeWidgetItem(["Salt okunur"])
        for c in summary.characteristics:
            item = payload_item(f"{c.name}  [{c.kind}]", ("characteristic", c))
            (readonly_root if c.read_only else tuneable_root).addChild(item)
        characteristics_root.addChild(tuneable_root)
        characteristics_root.addChild(readonly_root)
        self.tree.addTopLevelItem(characteristics_root)
        self.tree.expandAll()

    def _apply_filter(self, text: str):
        filter_tree(self.tree, text)

    # ---- Değer paneli ------------------------------------------------------
    def _build_value_panel(self) -> QWidget:
        box, body, _head = make_card("Canlı değer", "gauge")

        self.sel_name = QLabel("-")
        self.sel_kind = QLabel("-")
        self.sel_address = QLabel("-")
        self.sel_unit = QLabel("-")
        for lbl in (self.sel_name, self.sel_kind, self.sel_address, self.sel_unit):
            lbl.setWordWrap(True)

        form = QFormLayout()
        form.addRow("İsim:", self.sel_name)
        form.addRow("Tip:", self.sel_kind)
        form.addRow("Adres:", self.sel_address)
        form.addRow("Birim:", self.sel_unit)

        self.value_display = QLabel("-")
        self.value_display.setStyleSheet(f"font-size: 16px; font-weight: bold; color: {theme.INK};")
        form.addRow("Okunan değer:", self.value_display)

        # "Oku" ve "Sürekli oku" kaldırıldı: nesne seçilince ve CCP çevrimiçiyken değer sürekli güncellenir.
        self.read_button = QPushButton("Oku")
        self.poll_checkbox = QCheckBox("Sürekli oku")
        for hidden in (self.read_button, self.poll_checkbox):
            hidden.setVisible(False)
        self.live_hint = QLabel("● Canlı: seçili değer sürekli okunur")
        self.live_hint.setStyleSheet(f"color: {theme.MUTED};")
        read_row = QHBoxLayout()
        read_row.addWidget(self.live_hint)
        read_row.addStretch()

        self.array_hint_label = QLabel("")
        self.array_hint_label.setWordWrap(True)
        self.array_hint_label.setStyleSheet(f"color: {theme.WARN_INK};")
        self.array_hint_label.setVisible(False)
        self.open_map_button = QPushButton("Worksheets'te Aç (tüm elemanları gör/düzenle)")
        self.open_map_button.setVisible(False)
        self.open_map_button.clicked.connect(self._on_open_map_clicked)

        self.write_edit = QLineEdit()
        self.write_edit.setPlaceholderText("Yazılacak değer (fiziksel birimde)")
        self.write_ram_button = QPushButton("RAM'e Yaz (Geçici)")
        self.write_ram_button.clicked.connect(lambda: self.write_requested.emit(False))

        self.flash_enable_checkbox = QCheckBox("Deneysel flaş yazmayı etkinleştir (RİSKLİ)")
        self.flash_enable_checkbox.setToolTip(
            "CCP PROGRAM/PROGRAM_6/CLEAR_MEMORY komut dizilimi ASAM CCP 2.1 "
            "spesifikasyonuna göre uygulanmıştır, ancak M220 ECU'sunun "
            "GERÇEK flaş programlama akışı bu projede donanımla "
            "DOĞRULANMADI. Önce test ortamında (simülatör / yedek ECU) "
            "deneyin. Yanlış bir varsayım donanıma zarar verebilir."
        )
        self.flash_enable_checkbox.toggled.connect(self._on_flash_enable_toggled)

        self.write_flash_button = QPushButton("Kalıcı Kaydet (Flaş)")
        self.write_flash_button.setProperty("danger", True)
        self.write_flash_button.clicked.connect(self._on_write_flash_clicked)
        self.write_flash_button.setEnabled(False)

        write_row = QHBoxLayout()
        write_row.addWidget(self.write_ram_button)
        write_row.addWidget(self.write_flash_button)

        self.op_status_label = QLabel("")
        self.op_status_label.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addLayout(read_row)
        layout.addWidget(self.array_hint_label)
        layout.addWidget(self.open_map_button)
        layout.addWidget(self.write_edit)
        layout.addLayout(write_row)
        layout.addWidget(self.flash_enable_checkbox)
        layout.addWidget(self.op_status_label)
        layout.addStretch()
        body.addLayout(layout, 1)

        self._set_write_enabled(False)
        return box

    def _set_write_enabled(self, enabled: bool):
        self.write_edit.setEnabled(enabled)
        self.write_ram_button.setEnabled(enabled)
        self.flash_enable_checkbox.setEnabled(enabled)
        self.write_flash_button.setEnabled(enabled and self.flash_enable_checkbox.isChecked())

    def _on_flash_enable_toggled(self, checked: bool):
        self.write_flash_button.setEnabled(checked and self.write_edit.isEnabled())

    def _update_live(self):
        """Seçili nesne + çevrimiçi/ECU-yok oturumu varsa canlı okuma zamanlayıcısı çalışır."""
        want = self._selected is not None and self._session_active
        if want and not self.poll_timer.isActive():
            self.poll_timer.start()
        elif not want and self.poll_timer.isActive():
            self.poll_timer.stop()

    def _on_write_flash_clicked(self):
        sel = self._selected[1] if self._selected else None
        what = ""
        if sel is not None:
            addr = getattr(sel, "address", None)
            what = (f"Nesne: {sel.name}\nAdres: {('0x%X' % addr) if addr is not None else '-'}\n"
                    f"Yeni değer: {self.entered_value_text()} {getattr(sel, 'unit', '') or ''}\n\n")
        confirm = QMessageBox.warning(
            self, "KALICI (FLAŞ) YAZMA — devam edilsin mi?",
            what +
            "Bu işlem seçili değeri ECU'nun KALICI (flaş) belleğine "
            "yazacak; RAM yazmadan farklı olarak güç kesilse bile kalır.\n\n"
            "M220'nin gerçek flaş programlama akışı bu uygulamada "
            "donanımla doğrulanmamıştır — beklenmedik bir sonuç ECU'ya "
            "zarar verebilir. Eski değer, geri alma için Kalibrasyon "
            "Geçmişi'ne kaydedilecek.\n\n"
            "Gerçekten devam etmek istediğinizden emin misiniz?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        self.write_requested.emit(True)

    def _on_open_map_clicked(self):
        if self._selected is not None and self._selected[0] == "characteristic":
            self.open_in_modas_requested.emit(self._selected[1])

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int):
        # Seçim değişince flaş "etkinleştir" kutusu sıfırlanır: önceki nesne
        # için verilen izin yeni nesneye taşınmasın.
        self.flash_enable_checkbox.setChecked(False)
        payload = item.data(0, ROLE_OBJECT)
        if payload is None:
            self._selected = None
            self._update_live()
            self._set_write_enabled(False)
            return
        kind, obj = payload
        self._selected = (kind, obj)

        self.sel_name.setText(obj.name)
        self.sel_unit.setText(obj.unit or "-")
        address = getattr(obj, "address", None)
        self.sel_address.setText(f"0x{address:X}" if address else "- (A2L'de tanımsız)")

        multi = kind == "characteristic" and getattr(obj, "kind", "SCALAR") != "SCALAR"
        self.array_hint_label.setVisible(multi)
        self.open_map_button.setVisible(multi)
        if multi:
            from app.ccp.mapio import grid_shape
            rows, cols = grid_shape(obj)
            self.array_hint_label.setText(
                f"Bu nesne tek değer DEĞİL: {obj.kind} ({rows} satır × {cols} sütun = "
                f"{rows * cols} eleman). Bu panel yalnızca İLK elemanı okur/yazar; "
                "tüm elemanları görmek ve düzenlemek için Worksheets (Modas) sayfasını kullanın."
            )
        if kind == "measurement":
            self.sel_kind.setText(f"MEASUREMENT ({obj.datatype})")
            self._set_write_enabled(False)
        else:
            self.sel_kind.setText(f"CHARACTERISTIC/{obj.kind} ({obj.datatype})")
            # Dizi/tablo nesnelerinde tek-değer yazma kapalı: yalnızca ilk
            # elemanı yazıp geri kalanını bozmasın.
            self._set_write_enabled((not obj.read_only) and not multi)

        self.value_display.setText("-")
        self.op_status_label.setText("")
        self._update_live()

    # ---- MainWindow'un kullandığı erişimciler ----------------------------
    def selected_object(self):
        return self._selected

    def entered_value_text(self) -> str:
        return self.write_edit.text().strip()

    def set_read_value(self, text: str):
        self.value_display.setText(text)

    def set_write_result(self, ok: bool, message: str):
        # Her yazma denemesinden sonra flaş izni kapanır (tek seferlik izin).
        self.flash_enable_checkbox.setChecked(False)
        self.op_status_label.setText(message)
        self.op_status_label.setStyleSheet(f"color: {theme.OK};" if ok else f"color: {theme.DANGER};")
