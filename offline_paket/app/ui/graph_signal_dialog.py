"""Ana Sayfa > Canlı Grafik için sinyal seçim penceresi.

Sinyal sayısı ve türü serbesttir: 8 gösterge sinyali (RPM, İtki, PLA ...) ve
yüklü A2L dosyasındaki TÜM ölçümler (Measurement) listelenir; istenen sayıda
işaretlenebilir. Üstteki "İsme göre ara..." kutusu listeyi süzer; süzme
işaretleri etkilemez (gizli olanlar işaretli kalır).

Sinyal kimlikleri:  "g:<gösterge anahtarı>"  |  "m:<A2L ölçüm adı>"
"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

ROLE_ID = Qt.UserRole + 1


def signal_label(sig_id: str) -> str:
    """Kimlikten ekranda gösterilecek ad ("g:RPM" -> "RPM")."""
    return sig_id.split(":", 1)[1] if ":" in sig_id else sig_id


class GraphSignalDialog(QDialog):
    def __init__(self, gauge_keys, measurement_names, selected, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Canlı Grafik — sinyalleri seç")
        self.resize(460, 560)
        self._selected = list(selected)

        self.search = QLineEdit()
        self.search.setPlaceholderText("İsme göre ara...")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(True)

        self._gauge_root = QTreeWidgetItem(["Göstergeler"])
        self._meas_root = QTreeWidgetItem(["A2L ölçümleri"])
        for root in (self._gauge_root, self._meas_root):
            root.setFlags(root.flags() & ~Qt.ItemIsUserCheckable)
            self.tree.addTopLevelItem(root)

        chosen = set(selected)
        for key in gauge_keys:
            self._add_leaf(self._gauge_root, key, f"g:{key}", chosen)
        for name in measurement_names:
            self._add_leaf(self._meas_root, name, f"m:{name}", chosen)
        if not measurement_names:
            hint = QTreeWidgetItem(["(A2L yüklenince ölçümler burada listelenir)"])
            hint.setFlags(Qt.NoItemFlags)
            self._meas_root.addChild(hint)
        self.tree.expandAll()
        self.tree.itemChanged.connect(self._update_count)

        # A2L'de olmayan ama daha önce seçilmiş (kayıtlı) ölçümler de görünsün
        # ki kullanıcı onları kaldırabilsin.
        known = {f"m:{n}" for n in measurement_names} | {f"g:{k}" for k in gauge_keys}
        for sid in selected:
            if sid not in known and sid.startswith("m:"):
                self._add_leaf(self._meas_root, signal_label(sid) + "  (A2L'de yok)", sid, chosen)

        self.count_label = QLabel("")
        clear_btn = QPushButton("Tümünü temizle")
        clear_btn.clicked.connect(self._clear_all)
        bottom = QHBoxLayout()
        bottom.addWidget(self.count_label, 1)
        bottom.addWidget(clear_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Uygula")
        buttons.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addLayout(bottom)
        lay.addWidget(buttons)
        self._update_count()

    def _add_leaf(self, root, text, sig_id, chosen):
        item = QTreeWidgetItem([text])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Checked if sig_id in chosen else Qt.Unchecked)
        item.setData(0, ROLE_ID, sig_id)
        root.addChild(item)

    def _leaves(self):
        for root in (self._gauge_root, self._meas_root):
            for i in range(root.childCount()):
                child = root.child(i)
                if child.data(0, ROLE_ID):
                    yield child

    def _apply_filter(self, text: str):
        text = text.strip().lower()
        for root in (self._gauge_root, self._meas_root):
            any_visible = False
            for i in range(root.childCount()):
                child = root.child(i)
                visible = (not text) or text in child.text(0).lower()
                child.setHidden(not visible)
                any_visible = any_visible or visible
            root.setHidden(bool(text) and not any_visible)

    def _clear_all(self):
        self.tree.blockSignals(True)
        for leaf in self._leaves():
            leaf.setCheckState(0, Qt.Unchecked)
        self.tree.blockSignals(False)
        self._update_count()

    def _update_count(self, *_):
        n = len(self.selected_ids())
        self.count_label.setText(f"{n} sinyal seçili")

    def selected_ids(self) -> list:
        """İşaretli sinyal kimlikleri; önce önceki sıra korunur, yeniler sona eklenir."""
        checked = {leaf.data(0, ROLE_ID) for leaf in self._leaves()
                   if leaf.checkState(0) == Qt.Checked}
        ordered = [s for s in self._selected if s in checked]
        for leaf in self._leaves():
            sid = leaf.data(0, ROLE_ID)
            if sid in checked and sid not in ordered:
                ordered.append(sid)
        return ordered
