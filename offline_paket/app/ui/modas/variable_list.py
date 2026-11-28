"""Variable list (Modas: F2 ile açılıp kapanan sağ panel) ve Log penceresi (F3).

Değişken listesi: ``Label | Description`` iki sütunu, değişken süzgeci (``ALL MEASUREMENTS`` / ``ALL CHARACTERISTICS`` →
values / curves / maps / text) ve arama kutusu. Satır çift tıklanınca / Enter ile ya da sürüklenip çalışma alanına
bırakılınca ``add_requested`` yayılır. A2L özetinden (``A2LSummary``) beslenir; ECU ile konuşmaz.
"""

from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMenu, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from app import theme
from app.ui.modas.kind_icons import kind_icon

MIME = "application/x-openecu-label"

# (görünen ad, süzgeç anahtarı)
FILTERS = [
    ("<No variable filter>", ""),
    ("- ALL MEASUREMENTS", "meas"),
    ("- ALL CHARACTERISTICS", "char"),
    ("   - values", "value"),
    ("   - curves", "curve"),
    ("   - maps", "map"),
    ("   - text", "text"),
]


def classify(obj) -> str:
    """Nesnenin Variable list türü: meas | value | curve | map | text."""
    if not hasattr(obj, "kind") or not hasattr(obj, "read_only"):
        return "meas"
    ctype = (getattr(obj, "char_type", "") or "").upper()
    if ctype == "ASCII":
        return "text"
    kind = obj.kind
    if kind == "SCALAR":
        return "value"
    if kind == "CURVE":
        return "curve"
    if kind == "MAP":
        return "map"
    if kind == "ARRAY":                      # VAL_BLK: tek boyutlu → eğri gibi, iki boyutlu → harita gibi
        dims = getattr(obj, "dims", None) or (1,)
        return "curve" if len(dims) == 1 else "map"
    return "text"


def passes_filter(kind: str, key: str) -> bool:
    if not key:
        return True
    if key == "char":
        return kind != "meas"
    return kind == key


class _VarTable(QTableWidget):
    """Satırları ``MIME`` ile sürüklemeye izin veren tablo (bırakma hedefi: çalışma alanı)."""
    activated_row = Signal(int)

    def mimeData(self, items):  # noqa: N802
        rows = sorted({i.row() for i in items})
        mime = QMimeData()
        names = [self.item(r, 0).text() for r in rows]
        mime.setData(MIME, "\n".join(names).encode("utf-8"))
        mime.setText("\n".join(names))
        return mime

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            row = self.currentRow()
            if row >= 0:
                self.activated_row.emit(row)
            return
        super().keyPressEvent(event)


class VariableListPanel(QFrame):
    add_requested = Signal(object)         # A2L nesnesi
    info_requested = Signal(object)
    refresh_requested = Signal()           # F5

    def __init__(self):
        super().__init__()
        self.setObjectName("modasVarPanel")
        self.setMinimumWidth(260)
        self.setMaximumWidth(460)
        self._summary = None
        self._objects: list = []           # satır -> nesne
        self._kinds: list = []

        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(3)
        title = QLabel("Değişken listesi:")
        title.setObjectName("modasPanelTitle")
        v.addWidget(title)
        self.filter_combo = QComboBox()
        self.filter_combo.setObjectName("modasFilter")
        for text, key in FILTERS:
            self.filter_combo.addItem(text, key)
        self.filter_combo.currentIndexChanged.connect(self.apply_filter)
        v.addWidget(self.filter_combo)
        self.search = QLineEdit()
        self.search.setObjectName("modasSearch")
        self.search.setPlaceholderText("Etiket / Açıklama ara…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        v.addWidget(self.search)

        self.table = _VarTable(0, 2)
        self.table.setObjectName("modasVarList")
        self.table.setHorizontalHeaderLabels(["Etiket", "Açıklama"])
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(18)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setDragEnabled(True)
        self.table.setDragDropMode(QAbstractItemView.DragOnly)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setColumnWidth(0, 170)
        self.table.cellDoubleClicked.connect(lambda r, _c: self._add_row(r))
        self.table.activated_row.connect(self._add_row)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_menu)
        v.addWidget(self.table, 1)
        self.count_label = QLabel("")
        self.count_label.setObjectName("modasPanelTitle")
        v.addWidget(self.count_label)

    # ---- veri -----------------------------------------------------------------------
    def set_summary(self, summary):
        """A2L özetini (ya da None) yükler ve listeyi yeniden kurar."""
        self._summary = summary
        objs = []
        if summary is not None:
            objs = sorted(list(summary.measurements) + list(summary.characteristics), key=lambda o: o.name.lower())
        self._objects = objs
        self._kinds = [classify(o) for o in objs]
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(objs))
            for r, (o, k) in enumerate(zip(objs, self._kinds)):
                a = QTableWidgetItem(kind_icon(k), o.name)
                a.setToolTip(f"{o.name} — {k}")
                b = QTableWidgetItem(getattr(o, "description", "") or "")
                self.table.setItem(r, 0, a)
                self.table.setItem(r, 1, b)
        finally:
            self.table.setUpdatesEnabled(True)
        self.apply_filter()

    def apply_filter(self, *_):
        key = self.filter_combo.currentData() or ""
        text = self.search.text().strip().lower()
        shown = 0
        for r, (o, k) in enumerate(zip(self._objects, self._kinds)):
            ok = passes_filter(k, key)
            if ok and text:
                ok = text in o.name.lower() or text in (getattr(o, "description", "") or "").lower()
            self.table.setRowHidden(r, not ok)
            shown += ok
        self.count_label.setText(f"{shown} / {len(self._objects)}" if self._objects else "A2L yüklenmedi")

    def visible_names(self) -> list:
        return [o.name for r, o in enumerate(self._objects) if not self.table.isRowHidden(r)]

    def object_at(self, row: int):
        return self._objects[row] if 0 <= row < len(self._objects) else None

    def selected_objects(self) -> list:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._objects[r] for r in rows if 0 <= r < len(self._objects)]

    # ---- etkileşim ------------------------------------------------------------------
    def _add_row(self, row: int):
        obj = self.object_at(row)
        if obj is not None:
            self.add_requested.emit(obj)

    def _on_menu(self, pos):
        row = self.table.rowAt(pos.y())
        obj = self.object_at(row)
        if obj is None:
            return
        menu = QMenu(self)
        act_add = menu.addAction("Etiketi çalışma sayfasına ekle")
        act_info = menu.addAction("Değişken bilgisi…   Ctrl+I")
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is act_add:
            self.add_requested.emit(obj)
        elif chosen is act_info:
            self.info_requested.emit(obj)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_F5:
            self.refresh_requested.emit()
            return
        if event.key() == Qt.Key_I and event.modifiers() & Qt.ControlModifier:
            objs = self.selected_objects()
            if objs:
                self.info_requested.emit(objs[0])
            return
        super().keyPressEvent(event)


class LogPanel(QFrame):
    """Alt Log penceresi (F3): olay günlüğünün canlı akışı (en yeni altta, Modas'taki gibi)."""
    MAX = 500
    COLORS = {"HATA": theme.DANGER, "KALIBRASYON": theme.ACCENT_INK, "BAGLANTI": theme.OK, "CCP": theme.BLUE,
              "OTURUM": theme.PURPLE, "KULLANICI": theme.MUTED}

    def __init__(self):
        super().__init__()
        self.setObjectName("modasLogPanel")
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 2, 4, 2)
        v.setSpacing(1)
        head = QHBoxLayout()
        title = QLabel("Günlük")
        title.setObjectName("modasPanelTitle")
        head.addWidget(title)
        head.addStretch(1)
        v.addLayout(head)
        self.list = QListWidget()
        self.list.setObjectName("modasLog")
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        v.addWidget(self.list, 1)
        self.setMinimumHeight(70)
        self.setMaximumHeight(170)

    def add_entry(self, entry):
        import time as _t
        text = f"{_t.strftime('%H:%M:%S', _t.localtime(entry.timestamp))}  {entry.category}: {entry.message}"
        item = QListWidgetItem(text)
        item.setForeground(QColor(self.COLORS.get(entry.category, theme.INK)))
        item.setToolTip(f"{entry.user} / {entry.role}")
        self.list.addItem(item)
        while self.list.count() > self.MAX:
            self.list.takeItem(0)
        self.list.scrollToBottom()

    def add_text(self, text: str):
        self.list.addItem(QListWidgetItem(text))
        self.list.scrollToBottom()

    def texts(self) -> list:
        return [self.list.item(i).text() for i in range(self.list.count())]
