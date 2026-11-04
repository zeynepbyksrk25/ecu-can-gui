"""A2L sayfası (Ana Sayfa ile aynı koyu tasarım): üstte yükleme şeridi (A2L Yükle + dosya/sayı çipleri),
altta solda **Nesne tarayıcı** kartı, sağda **Nesne bilgisi** kartı. Ağaçtaki öğenin gerçek nesnesi
(MeasurementInfo/CharacteristicInfo) UserRole'de taşınır."""
import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from app.a2l import A2LDatabase
from app.ui.dash_widgets import DK_CYAN, IconLabel

ROLE_OBJECT = Qt.UserRole


class A2LTab(QWidget):
    a2l_loaded = Signal()

    def __init__(self):
        super().__init__()
        self.db = A2LDatabase()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 8, 14, 8)
        layout.setSpacing(10)
        layout.addWidget(self._build_load_strip())

        split = QSplitter(Qt.Horizontal)
        split.addWidget(self._build_tree_panel())
        split.addWidget(self._build_detail_panel())
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setChildrenCollapsible(False)
        layout.addWidget(split, 1)

    # ---- kart yardımcısı ------------------------------------------------------
    @staticmethod
    def _card(title: str, icon: str):
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(14, 10, 14, 12)
        v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(IconLabel(icon, DK_CYAN, 18))
        t = QLabel(title.upper())
        t.setObjectName("cardTitle")
        head.addWidget(t)
        head.addStretch(1)
        v.addLayout(head)
        return card, v

    # ---- Yükleme şeridi --------------------------------------------------------
    def _build_load_strip(self) -> QFrame:
        strip = QFrame()
        strip.setObjectName("stripBar")
        row = QHBoxLayout(strip)
        row.setContentsMargins(14, 8, 14, 8)
        row.setSpacing(10)
        load_button = QPushButton("A2L Yükle…")
        load_button.setProperty("tone", "go")
        load_button.clicked.connect(self._on_load)
        self.file_chip = QLabel("Yüklü A2L yok")
        self.file_chip.setObjectName("chipDim")
        self.project_chip = QLabel("")
        self.module_chip = QLabel("")
        self.meas_chip = QLabel("")
        self.char_chip = QLabel("")
        for c in (self.project_chip, self.module_chip, self.meas_chip, self.char_chip):
            c.setObjectName("chipBlue")
            c.setVisible(False)
        # MainWindow/eski kod uyumu: tek satırlık özet metni
        self.status_label = QLabel("Yüklü A2L yok.")
        self.status_label.setVisible(False)
        row.addWidget(load_button)
        row.addWidget(self.file_chip)
        row.addWidget(self.project_chip)
        row.addWidget(self.module_chip)
        row.addWidget(self.meas_chip)
        row.addWidget(self.char_chip)
        row.addStretch(1)
        return strip

    def _on_load(self):
        path, _ = QFileDialog.getOpenFileName(self.window(), "A2L dosyası seç", "", "A2L dosyaları (*.a2l)")
        if not path:
            return
        try:
            summary = self.db.load(path)
        except ValueError as exc:
            QMessageBox.critical(self.window(), "A2L yüklenemedi", str(exc))
            return
        self.show_loaded(path, summary)
        self.a2l_loaded.emit()

    def show_loaded(self, path: str, summary):
        """Yüklenen A2L'in özetini şeritte ve ağaçta gösterir (profil uygulanırken de kullanılır)."""
        filename = os.path.basename(path)
        self.file_chip.setText(filename)
        self.file_chip.setToolTip(path)
        tun = len(summary.tunable_scalars()) if hasattr(summary, "tunable_scalars") else 0
        for chip, text in ((self.project_chip, f"Proje: {summary.project_name or '—'}"),
                           (self.module_chip, f"Modül: {summary.module_name or '—'}"),
                           (self.meas_chip, f"{len(summary.measurements)} ölçüm"),
                           (self.char_chip, f"{len(summary.characteristics)} kalibrasyon nesnesi · {tun} ayarlanabilir skaler")):
            chip.setText(text)
            chip.setVisible(True)
        self.status_label.setText(
            f"Yüklü: {filename}  |  Proje: {summary.project_name}  |  Modül: {summary.module_name}  |  "
            f"{len(summary.measurements)} ölçüm, {len(summary.characteristics)} kalibrasyon nesnesi")
        self._populate_tree(summary)

    # ---- Ağaç (nesne tarayıcı) --------------------------------------------
    def _build_tree_panel(self) -> QFrame:
        card, v = self._card("Nesne tarayıcı", "sliders")
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("İsme göre ara… (ör. clbc_)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemClicked.connect(self._on_item_clicked)
        v.addWidget(self.search_edit)
        v.addWidget(self.tree, 1)
        return card

    def _populate_tree(self, summary):
        self.tree.clear()

        measurements_root = QTreeWidgetItem([f"Measurements ({len(summary.measurements)})"])
        for m in summary.measurements:
            item = QTreeWidgetItem([m.name])
            item.setData(0, ROLE_OBJECT, ("measurement", m))
            measurements_root.addChild(item)
        self.tree.addTopLevelItem(measurements_root)

        characteristics_root = QTreeWidgetItem([f"Characteristics ({len(summary.characteristics)})"])
        groups = {"SCALAR": QTreeWidgetItem(["Scalar"]),
                  "CURVE": QTreeWidgetItem(["Curves (1D)"]),
                  "MAP": QTreeWidgetItem(["Maps (2D)"]),
                  "ARRAY": QTreeWidgetItem(["Arrays (VAL_BLK)"])}
        counts = {k: 0 for k in groups}
        for kind_item in groups.values():
            characteristics_root.addChild(kind_item)
        for c in summary.characteristics:
            item = QTreeWidgetItem([c.name])
            item.setData(0, ROLE_OBJECT, ("characteristic", c))
            key = c.kind if c.kind in groups else "SCALAR"
            groups[key].addChild(item)
            counts[key] += 1
        for key, item in groups.items():
            item.setText(0, f"{item.text(0)} ({counts[key]})")
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

    # ---- Detay paneli ---------------------------------------------------------
    _DETAIL_ROWS = [
        ("detail_name", "İsim"), ("detail_desc", "Açıklama"), ("detail_type", "Tip"),
        ("detail_address", "Adres"), ("detail_datatype", "Veri tipi / bayt sırası"),
        ("detail_unit", "Birim"), ("detail_range", "Min / Max"), ("detail_readonly", "Yazılabilir mi"),
        ("detail_use", "Kullanım"),
    ]

    def _build_detail_panel(self) -> QFrame:
        card, v = self._card("Nesne bilgisi", "gauge")
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for r, (attr, label) in enumerate(self._DETAIL_ROWS):
            key = QLabel(label)
            key.setObjectName("kvKey")
            val = QLabel("-")
            val.setObjectName("kvVal")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            setattr(self, attr, val)
            grid.addWidget(key, r, 0, Qt.AlignTop)
            grid.addWidget(val, r, 1)
        grid.setColumnMinimumWidth(0, 150)
        grid.setColumnStretch(1, 1)
        v.addLayout(grid)
        v.addStretch(1)
        return card

    def _on_item_clicked(self, item: QTreeWidgetItem, _column: int):
        payload = item.data(0, ROLE_OBJECT)
        if payload is None:
            return
        kind, obj = payload

        self.detail_name.setText(obj.name)
        self.detail_desc.setText(obj.description or "-")
        self.detail_unit.setText(obj.unit or "-")
        self.detail_range.setText(f"{obj.minimum} / {obj.maximum}" if obj.minimum is not None else "-")
        address = getattr(obj, "address", None)
        self.detail_address.setText(f"0x{address:X}" if address is not None else "- (A2L'de tanımsız)")
        self.detail_datatype.setText(f"{obj.datatype or '-'}  ·  {getattr(obj, 'byte_order', None) or 'varsayılan'}")

        if kind == "measurement":
            self.detail_type.setText(f"MEASUREMENT ({obj.datatype})")
            self.detail_readonly.setText("Hayır (ölçüm, ECU'dan okunur)")
            self.detail_use.setText("Ana Sayfa / Grafik / Çalışma Alanı / Performans'ta sürekli çizilebilir")
        else:
            self.detail_type.setText(f"{obj.kind} ({obj.datatype})")
            self.detail_readonly.setText("Hayır (salt okunur)" if obj.read_only else "Evet (kalibrasyon)")
            tunable = obj.kind == "SCALAR" and not obj.read_only
            self.detail_use.setText(
                "Kalibrasyon > Parametre Listesi'nde değiştirilir; grafik/trend'de 'Ayarlanabilir parametreler' "
                "grubundan çizilebilir" if tunable else
                "Kalibrasyon > Harita Editörü'nde düzenlenir" if obj.kind in ("CURVE", "MAP", "ARRAY") else "-")
