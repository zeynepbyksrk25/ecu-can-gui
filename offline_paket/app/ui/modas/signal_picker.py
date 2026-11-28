"""Scope için sinyal seçici: DBC sinyalleri, göstergeler, girişler, matematik sinyalleri ve içe aktarılan kayıtlar
(A2L etiketleri Variable list'ten sürüklenir). Arama kutusu + gruplar; işaretlenenler grafiğe eklenir."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)


class SignalPickerDialog(QDialog):
    def __init__(self, groups: list, already: list | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Sinyal seç")
        self.resize(460, 540)
        taken = set(already or [])
        self.search = QLineEdit()
        self.search.setPlaceholderText("İsme göre ara…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        for title, sids in groups:
            root = QTreeWidgetItem([f"{title} ({len(sids)})"])
            root.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(root)
            for sid in sids:
                it = QTreeWidgetItem([sid.split(":", 1)[-1] + ("   (grafikte)" if sid in taken else "")])
                it.setData(0, Qt.UserRole, sid)
                it.setToolTip(0, sid)
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable if sid not in taken else Qt.NoItemFlags)
                it.setCheckState(0, Qt.Unchecked)
                root.addChild(it)
            root.setExpanded(len(sids) <= 12)
        self.empty = QLabel("Seçilebilir sinyal yok: DBC yükleyin, matematik sinyali tanımlayın ya da CSV açın.")
        self.empty.setWordWrap(True)
        self.empty.setVisible(not groups)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Ekle")
        bb.button(QDialogButtonBox.Cancel).setText("Vazgeç")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addWidget(self.tree, 1)
        lay.addWidget(self.empty)
        lay.addWidget(bb)

    def _filter(self, text: str):
        t = text.strip().lower()
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            shown = 0
            for j in range(root.childCount()):
                it = root.child(j)
                hide = bool(t) and t not in it.toolTip(0).lower()
                it.setHidden(hide)
                shown += 0 if hide else 1
            root.setHidden(shown == 0)
            if t and shown:
                root.setExpanded(True)

    def selected(self) -> list:
        out = []
        for i in range(self.tree.topLevelItemCount()):
            root = self.tree.topLevelItem(i)
            for j in range(root.childCount()):
                it = root.child(j)
                if it.checkState(0) == Qt.Checked and not it.isHidden():
                    out.append(it.data(0, Qt.UserRole))
        return out
