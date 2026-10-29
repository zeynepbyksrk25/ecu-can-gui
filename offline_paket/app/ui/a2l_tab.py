from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from app.a2l import A2LDatabase

# Ağaçtaki öğenin gerçek nesnesini (MeasurementInfo/CharacteristicInfo) UserRole'de taşıyoruz.
ROLE_OBJECT = Qt.UserRole


class A2LTab(QWidget):
    """SRS Bölüm 14-15: A2L yükleme + nesne tarayıcı (Measurements,
    Characteristics -> Scalar/Curve/Map). Henüz CCP bağlantısı olmadığı
    için Değer sütunu yok; bu ekran sadece A2L içeriğini gösterir."""

    a2l_loaded = Signal()

    def __init__(self):
        super().__init__()
        self.db = A2LDatabase()

        layout = QVBoxLayout(self)
        layout.addWidget(self._build_load_group())

        browser_row = QHBoxLayout()
        browser_row.addWidget(self._build_tree_panel(), stretch=1)
        browser_row.addWidget(self._build_detail_panel(), stretch=1)
        layout.addLayout(browser_row, stretch=1)

    # ---- Yükleme -----------------------------------------------------
    def _build_load_group(self) -> QGroupBox:
        box = QGroupBox("A2L dosyası")
        self.status_label = QLabel("Yüklü A2L yok.")
        load_button = QPushButton("A2L Yükle...")
        load_button.clicked.connect(self._on_load)

        row = QHBoxLayout()
        row.addWidget(load_button)
        row.addWidget(self.status_label, stretch=1)
        box.setLayout(row)
        return box

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(self, "A2L dosyası seç", "", "A2L dosyaları (*.a2l)")
        if not path:
            return
        try:
            summary = self.db.load(path)
        except ValueError as exc:
            QMessageBox.critical(self, "A2L yüklenemedi", str(exc))
            return

        filename = path.split("/")[-1]
        self.status_label.setText(
            f"Yüklü: {filename}  |  Proje: {summary.project_name}  |  Modül: {summary.module_name}  |  "
            f"{len(summary.measurements)} ölçüm, {len(summary.characteristics)} kalibrasyon nesnesi"
        )
        self._populate_tree(summary)
        self.a2l_loaded.emit()

    # ---- Ağaç (nesne tarayıcı) --------------------------------------
    def _build_tree_panel(self) -> QGroupBox:
        box = QGroupBox("Nesne tarayıcı")

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("İsme göre ara...")
        self.search_edit.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_item_clicked)

        layout = QVBoxLayout()
        layout.addWidget(self.search_edit)
        layout.addWidget(self.tree)
        box.setLayout(layout)
        return box

    def _populate_tree(self, summary):
        self.tree.clear()

        measurements_root = QTreeWidgetItem(["Measurements"])
        for m in summary.measurements:
            item = QTreeWidgetItem([m.name])
            item.setData(0, ROLE_OBJECT, ("measurement", m))
            measurements_root.addChild(item)
        self.tree.addTopLevelItem(measurements_root)

        characteristics_root = QTreeWidgetItem(["Characteristics"])
        groups = {"SCALAR": QTreeWidgetItem(["Scalar"]),
                  "CURVE": QTreeWidgetItem(["Curves (1D)"]),
                  "MAP": QTreeWidgetItem(["Maps (2D)"]),
                  "ARRAY": QTreeWidgetItem(["Arrays (VAL_BLK)"])}
        for kind_item in groups.values():
            characteristics_root.addChild(kind_item)
        for c in summary.characteristics:
            item = QTreeWidgetItem([c.name])
            item.setData(0, ROLE_OBJECT, ("characteristic", c))
            groups.get(c.kind, groups["SCALAR"]).addChild(item)
        self.tree.addTopLevelItem(characteristics_root)

        self.tree.expandAll()

    def _apply_filter(self, text: str):
        text = text.strip().lower()

        def filter_children(parent: QTreeWidgetItem) -> bool:
            any_visible = False
            for i in range(parent.childCount()):
                child = parent.child(i)
                if child.childCount() > 0:
                    visible = filter_children(child)
                else:
                    visible = text in child.text(0).lower()
                child.setHidden(not visible)
                any_visible = any_visible or visible
            return any_visible

        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            top.setHidden(not filter_children(top) and bool(text))

    # ---- Detay paneli --------------------------------------------------
    def _build_detail_panel(self) -> QGroupBox:
        box = QGroupBox("Nesne bilgisi")
        self.detail_name = QLabel("-")
        self.detail_desc = QLabel("-")
        self.detail_type = QLabel("-")
        self.detail_address = QLabel("-")
        self.detail_unit = QLabel("-")
        self.detail_range = QLabel("-")
        self.detail_readonly = QLabel("-")
        for lbl in (self.detail_name, self.detail_desc, self.detail_type,
                    self.detail_address, self.detail_unit, self.detail_range,
                    self.detail_readonly):
            lbl.setWordWrap(True)

        form = QFormLayout()
        form.addRow("İsim:", self.detail_name)
        form.addRow("Açıklama:", self.detail_desc)
        form.addRow("Tip:", self.detail_type)
        form.addRow("Adres:", self.detail_address)
        form.addRow("Birim:", self.detail_unit)
        form.addRow("Min / Max:", self.detail_range)
        form.addRow("Yazılabilir mi:", self.detail_readonly)
        box.setLayout(form)
        return box

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int):
        payload = item.data(0, ROLE_OBJECT)
        if payload is None:
            return
        kind, obj = payload

        self.detail_name.setText(obj.name)
        self.detail_desc.setText(obj.description or "-")
        self.detail_unit.setText(obj.unit or "-")
        self.detail_range.setText(
            f"{obj.minimum} / {obj.maximum}" if obj.minimum is not None else "-"
        )

        if kind == "measurement":
            self.detail_type.setText(f"MEASUREMENT ({obj.datatype})")
            self.detail_address.setText("-")
            self.detail_readonly.setText("Evet (ölçüm, yazılamaz)")
        else:
            self.detail_type.setText(f"{obj.kind} ({obj.datatype})")
            self.detail_address.setText(f"0x{obj.address:X}")
            self.detail_readonly.setText("Evet" if obj.read_only else "Hayır")
