"""Canlı Trend sinyal tablosu (renk tablosu + imleç değer paneli).

Her sinyal için: renk, ad, anlık değer (imleç açıkken Main/A değeri), B değeri, ΔY, ΔY/Δt, A–B aralığı
min/max/ortalama, birim, görünür, freeze, kaynak, dikey ofset. Satırlar sürükle-bırak ile yeniden sıralanır;
gruplar üst düğümdür. Tablo veri tutmaz: ``TrendPanel`` durumu ``sync`` ile iter, kullanıcı etkileşimini
sinyallerle bildirir.
"""
from __future__ import annotations

from PySide6.QtCore import QSignalBlocker, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QColorDialog, QHeaderView, QInputDialog, QMenu, QTreeWidget, QTreeWidgetItem,
)

(C_NAME, C_VALUE, C_B, C_DY, C_DYDT, C_MIN, C_MAX, C_MEAN, C_UNIT, C_SHOW, C_FREEZE, C_SOURCE, C_OFFSET) = range(13)
HEADERS = ["Sinyal", "Değer / A", "B", "ΔY (B−A)", "ΔY/Δt", "Min", "Max", "Ort.", "Birim", "Göster", "Dondur",
           "Kaynak", "Ofset"]
CURSOR_COLS = (C_B, C_DY, C_DYDT, C_MIN, C_MAX, C_MEAN)
ROLE_KEY = Qt.UserRole
ROLE_GROUP = Qt.UserRole + 1
NO_DATA = "veri yok"


def swatch(color: str, size: int = 12) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(color) if color else QColor("#888"))
    return QIcon(pm)


def fmt(v, digits: int = 5) -> str:
    return "—" if v is None else f"{v:.{digits}g}"


class SignalTable(QTreeWidget):
    order_changed = Signal(list)              # sinyal anahtarları, yeni sıra
    visibility_changed = Signal(str, bool)
    freeze_changed = Signal(str, bool)
    color_changed = Signal(str, str)
    offset_changed = Signal(str, float)
    scale_requested = Signal(str)
    own_strip_changed = Signal(str, bool)
    group_changed = Signal(str, str)
    remove_requested = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setColumnCount(len(HEADERS))
        self.setHeaderLabels(HEADERS)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(True)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.itemChanged.connect(self._on_item_changed)
        self.itemDoubleClicked.connect(self._on_double_click)
        h = self.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(QHeaderView.Interactive)
        for col, w in ((C_NAME, 150), (C_VALUE, 80), (C_B, 70), (C_DY, 80), (C_DYDT, 80), (C_MIN, 64), (C_MAX, 64),
                       (C_MEAN, 64), (C_UNIT, 48), (C_SHOW, 56), (C_FREEZE, 62), (C_SOURCE, 80), (C_OFFSET, 64)):
            self.setColumnWidth(col, w)
        self._items: dict[str, QTreeWidgetItem] = {}
        self._building = False
        self.set_cursor_columns(False)

    # ---- dışarıdan kurma ---------------------------------------------------------------
    def set_cursor_columns(self, on: bool):
        for c in CURSOR_COLS:
            self.setColumnHidden(c, not on)
        self.headerItem().setText(C_VALUE, "Değer / A" if on else "Değer")

    def sync(self, rows: list[dict]):
        """rows: sırayla {key,label,unit,color,visible,frozen,source,offset,group,own_strip,editable}."""
        self._building = True
        try:
            self.clear()
            self._items = {}
            groups: dict[str, QTreeWidgetItem] = {}
            for r in rows:
                parent = self.invisibleRootItem()
                if r.get("group"):
                    parent = groups.get(r["group"])
                    if parent is None:
                        parent = QTreeWidgetItem(self.invisibleRootItem(), [r["group"]])
                        parent.setData(C_NAME, ROLE_GROUP, True)
                        parent.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled)
                        parent.setExpanded(True)
                        groups[r["group"]] = parent
                it = QTreeWidgetItem(parent)
                it.setData(C_NAME, ROLE_KEY, r["key"])
                it.setText(C_NAME, r["label"])
                it.setIcon(C_NAME, swatch(r.get("color", "")))
                it.setText(C_UNIT, r.get("unit", ""))
                it.setText(C_SOURCE, r.get("source", ""))
                it.setText(C_OFFSET, "" if not r.get("offset") else f"{r['offset']:g}")
                it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled
                            | Qt.ItemIsUserCheckable | Qt.ItemIsEditable)
                it.setCheckState(C_SHOW, Qt.Checked if r.get("visible", True) else Qt.Unchecked)
                it.setCheckState(C_FREEZE, Qt.Checked if r.get("frozen") else Qt.Unchecked)
                it.setData(C_NAME, Qt.ToolTipRole, f"{r['label']}  [{r.get('unit', '')}]  · kaynak: {r.get('source') or '—'}"
                           "\nSürükleyerek sırayı değiştirin; çift tık: renk; sağ tık: ofset/ölçek/şerit/grup.")
                self._items[r["key"]] = it
        finally:
            self._building = False
        self.expandAll()

    def keys_in_order(self) -> list[str]:
        out = []

        def walk(node):
            for i in range(node.childCount()):
                ch = node.child(i)
                k = ch.data(C_NAME, ROLE_KEY)
                if k:
                    out.append(k)
                walk(ch)
        walk(self.invisibleRootItem())
        return out

    def set_value(self, key: str, col: int, text: str, color: str | None = None):
        it = self._items.get(key)
        if it is None or it.text(col) == text and color is None:
            return
        with QSignalBlocker(self):
            it.setText(col, text)
            it.setForeground(col, QBrush(QColor(color)) if color else QBrush())
            it.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)

    def item_text(self, key: str, col: int) -> str:
        it = self._items.get(key)
        return it.text(col) if it is not None else ""

    # ---- etkileşim ---------------------------------------------------------------------
    def dropEvent(self, event):  # noqa: N802
        super().dropEvent(event)
        if self._building:
            return
        # yaprak olmayan (grup) düğümler yaprak altına bırakılamaz: grup etiketi yeni üst düğümden okunur
        for key, it in self._items.items():
            parent = it.parent()
            grp = parent.text(C_NAME) if parent is not None and parent.data(C_NAME, ROLE_GROUP) else ""
            self.group_changed.emit(key, grp)
        self.order_changed.emit(self.keys_in_order())

    def _on_item_changed(self, item, col):
        if self._building:
            return
        key = item.data(C_NAME, ROLE_KEY)
        if not key:
            return
        if col == C_SHOW:
            self.visibility_changed.emit(key, item.checkState(C_SHOW) == Qt.Checked)
        elif col == C_FREEZE:
            self.freeze_changed.emit(key, item.checkState(C_FREEZE) == Qt.Checked)
        elif col == C_OFFSET:
            text = item.text(C_OFFSET).strip().replace(",", ".")
            try:
                val = float(text) if text else 0.0
            except ValueError:
                val = None
            if val is None or val != val or val in (float("inf"), float("-inf")):
                with QSignalBlocker(self):
                    item.setText(C_OFFSET, "")
                return
            self.offset_changed.emit(key, val)

    def _on_double_click(self, item, col):
        key = item.data(C_NAME, ROLE_KEY)
        if key and col == C_NAME:
            c = QColorDialog.getColor(parent=self, title="Sinyal rengi")
            if c.isValid():
                self.color_changed.emit(key, c.name())

    def _menu(self, pos):
        item = self.itemAt(pos)
        if item is None:
            return
        key = item.data(C_NAME, ROLE_KEY)
        if not key:
            return
        m = QMenu(self)
        m.addAction("Renk değiştir…", lambda: self._on_double_click(item, C_NAME))
        m.addAction("Dikey ofset…", lambda: self._ask_offset(key, item))
        m.addAction("Dikey ölçek…", lambda: self.scale_requested.emit(key))
        m.addAction("Ayrı şeride taşı / birleştir", lambda: self.own_strip_changed.emit(key, True))
        m.addAction("Gruba ekle…", lambda: self._ask_group(key))
        m.addAction("Gruptan çıkar", lambda: (self.group_changed.emit(key, ""), self.order_changed.emit(self.keys_in_order())))
        m.addSeparator()
        m.addAction("Grafikten çıkar", lambda: self.remove_requested.emit(key))
        m.exec(self.viewport().mapToGlobal(pos))

    def _ask_offset(self, key, item):
        cur = item.text(C_OFFSET)
        val, ok = QInputDialog.getDouble(self, "Dikey ofset", "Eğriyi dikeyde kaydır (yalnızca görünüm; veri değişmez):",
                                         float(cur) if cur else 0.0, -1e12, 1e12, 6)
        if ok:
            self.offset_changed.emit(key, val)

    def _ask_group(self, key):
        name, ok = QInputDialog.getText(self, "Gruba ekle", "Grup adı:")
        if ok and name.strip():
            self.group_changed.emit(key, name.strip())
