"""Kontrol Paneli: en dış bloğun tüm girişlerini, çıkışlarını ve sinyallerini
TEK sayfada gösterir. Sinyal listesi kullanıcıdan istenmez: DBC ve A2L
yüklenince katalog otomatik çıkarılır (bkz. app/control_panel.py); kullanıcı
kataloğdan "çalışma listesine" sinyal ekler.

Gruplar:  UÇAK GİRİŞLERİ (DBC, periyodik CAN) · SENSÖR GİRİŞLERİ (A2L
_Ovr_Val + _Ovr_En, CCP) · ÇIKIŞLAR (CAN veya CCP) · İÇ SİNYALLER.

Girişler anında gitmez: hücre sarı (bekleyen) olur, "Uygula" hepsini birlikte
gönderir. Bu widget gerçek CAN/CCP işini YAPMAZ; MainWindow'a sinyal yayar
(apply_requested, kill_overrides_requested, poll_requested, ...) ve sonuçları
set_*/apply_finished metotlarıyla alır.
"""

from __future__ import annotations

import os
import time
from collections import deque

from PySide6.QtCore import QRectF, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QMenu,
    QMessageBox, QPushButton, QSplitter, QStyledItemDelegate, QTableWidget,
    QTableWidgetItem, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget, QApplication,
)

from app import control_panel as cp
from app.control_panel import (
    ROLE_AIRCRAFT_IN, ROLE_INTERNAL, ROLE_OUTPUT, ROLE_SENSOR_OVR, ROLE_TITLES,
    SignalDef,
)

C_PEND_ROW = QColor("#FFF1CC")
C_PEND_CELL = QColor("#FFE8A8")
C_FAULT_ROW = QColor("#FBE3E0")
C_CHANGED_ROW = QColor("#E1EEF6")
C_OK = QColor("#1B8A4C")
C_WARN = QColor("#B9790F")
C_BAD = QColor("#C22A1D")
C_MUTED = QColor("#51616F")
C_PRIMARY = "#0E6E8C"

ROLE_CHOICES = Qt.UserRole + 2
ROLE_SPARK = Qt.UserRole + 1
ROW_H = 30
ROW_H_COMPACT = 24
HIST_SECONDS = 30.0

SECTION_SUBTITLES = {
    ROLE_AIRCRAFT_IN: "DBC · arayüz → ECU · periyodik gönderim",
    ROLE_SENSOR_OVR: "A2L · _Ovr_Val + _Ovr_En çiftleri · CCP",
    ROLE_OUTPUT: "ECU → arayüz · canlı · CAN (DBC) veya CCP (A2L)",
    ROLE_INTERNAL: "A2L · iç sinyaller · açıkken okunur",
}

COLUMNS = {
    ROLE_AIRCRAFT_IN: ["", "İsim", "Değer", "Birim", "Aralık", "Mesaj · periyot", "Gönderim"],
    ROLE_SENSOR_OVR: ["", "İsim", "Override", "Değer", "ECU'nun gördüğü", "Birim", "A2L parametresi"],
    ROLE_OUTPUT: ["", "İsim", "Değer", "Önceki", "Δ", "Birim", "Kaynak", "Son 30 sn"],
    ROLE_INTERNAL: ["", "İsim", "Değer", "Önceki", "Δ", "Birim", "Kaynak", "Son 30 sn"],
}
# değer düzenlenen sütun
VALUE_COL = {ROLE_AIRCRAFT_IN: 2, ROLE_SENSOR_OVR: 3}


def _fmt_num(v) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.6g}"
    except (TypeError, ValueError):
        return str(v)


# ---- Delegeler ----------------------------------------------------------------
class _SparkDelegate(QStyledItemDelegate):
    """"Son 30 sn" mini çizgi grafiği (hücre verisi: [(t, değer), ...])."""

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        data = index.data(ROLE_SPARK)
        if not data or len(data) < 2:
            return
        vals = [v for _t, v in data]
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or 1.0
        r = option.rect.adjusted(6, 5, -6, -5)
        t0, t1 = data[0][0], data[-1][0]
        tspan = (t1 - t0) or 1.0
        pts = [QPointF(r.left() + (t - t0) / tspan * r.width(),
                       r.bottom() - ((v - lo) / span) * r.height() if hi != lo else r.center().y())
               for t, v in data]
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QPen(QColor(C_PRIMARY), 1.5))
        for a, b in zip(pts, pts[1:]):
            painter.drawLine(a, b)
        painter.restore()


class _ChoiceDelegate(QStyledItemDelegate):
    """Durum listesi (DBC VAL_) olan satırlarda değer kutusu açılır liste olur."""

    def createEditor(self, parent, option, index):
        choices = index.data(ROLE_CHOICES)
        if not choices:
            return super().createEditor(parent, option, index)
        box = QComboBox(parent)
        for k, label in choices.items():
            box.addItem(label, k)
        return box

    def setEditorData(self, editor, index):
        if isinstance(editor, QComboBox):
            cur = (index.data(Qt.EditRole) or "").split(" · ")[-1]
            i = editor.findText(cur)
            editor.setCurrentIndex(max(0, i))
        else:
            super().setEditorData(editor, index)

    def setModelData(self, editor, model, index):
        if isinstance(editor, QComboBox):
            model.setData(index, editor.currentText(), Qt.EditRole)
        else:
            super().setModelData(editor, model, index)


# ---- Grup tablosu -----------------------------------------------------------------
class _GroupTable(QTableWidget):
    paste_requested = Signal()

    def __init__(self, role: str):
        super().__init__()
        self.role = role
        cols = COLUMNS[role]
        self.setColumnCount(len(cols))
        self.setHorizontalHeaderLabels(cols)
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                             | QAbstractItemView.AnyKeyPressed)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setFrameShape(QFrame.NoFrame)
        self.setShowGrid(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        h.setMinimumSectionSize(40)
        self.setColumnWidth(0, 26)
        widths = {ROLE_AIRCRAFT_IN: [26, 190, 150, 60, 110, 150, 100],
                  ROLE_SENSOR_OVR: [26, 190, 120, 130, 150, 60, 170],
                  ROLE_OUTPUT: [26, 190, 120, 100, 80, 60, 110, 130],
                  ROLE_INTERNAL: [26, 190, 120, 100, 80, 60, 110, 130]}[role]
        for i, w in enumerate(widths):
            self.setColumnWidth(i, w)
        if role in VALUE_COL:
            self.setItemDelegateForColumn(VALUE_COL[role], _ChoiceDelegate(self))
        if role in (ROLE_OUTPUT, ROLE_INTERNAL):
            self.setItemDelegateForColumn(7, _SparkDelegate(self))
        sc = QShortcut(QKeySequence.Paste, self)
        sc.setContext(Qt.WidgetShortcut)
        sc.activated.connect(self.paste_requested.emit)

    def fit_height(self, compact: bool):
        rh = ROW_H_COMPACT if compact else ROW_H
        visible = sum(1 for r in range(self.rowCount()) if not self.isRowHidden(r))
        for r in range(self.rowCount()):
            self.setRowHeight(r, rh)
        hh = self.horizontalHeader().height() or 26
        sb = self.horizontalScrollBar().sizeHint().height() if self.horizontalScrollBar().isVisible() else 0
        self.setFixedHeight(hh + visible * rh + 4 + sb)


class _Section(QWidget):
    """Daraltılabilir grup: başlık (ok + başlık + alt başlık) + tablo."""
    toggled = Signal(str, bool)

    def __init__(self, role: str):
        super().__init__()
        self.role = role
        self.table = _GroupTable(role)
        self.button = QToolButton()
        self.button.setCheckable(True)
        self.button.setChecked(True)
        self.button.setArrowType(Qt.DownArrow)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setStyleSheet("QToolButton{border:0;font-weight:700;color:#243442;text-align:left;}")
        self.button.toggled.connect(self._on_toggle)
        self.title = ROLE_TITLES[role]
        self.subtitle = QLabel("")
        self.subtitle.setStyleSheet("color:#51616F;")
        self.empty_label = QLabel("Henüz sinyal yok — “+ Sinyal kataloğu”ndan ekleyin.")
        self.empty_label.setStyleSheet("color:#51616F;padding:10px 14px;")
        head = QWidget()
        head.setStyleSheet("background:#E3EAF0;")
        hl = QHBoxLayout(head)
        hl.setContentsMargins(10, 4, 10, 4)
        hl.addWidget(self.button)
        hl.addWidget(self.subtitle, 1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 6)
        lay.setSpacing(0)
        lay.addWidget(head)
        lay.addWidget(self.empty_label)
        lay.addWidget(self.table)
        self.set_summary(0, "")

    def set_summary(self, count: int, extra: str):
        self.button.setText(f"{self.title}  ·  {count}")
        self.subtitle.setText(extra or "")
        self.empty_label.setVisible(count == 0 and self.button.isChecked())
        self.table.setVisible(count > 0 and self.button.isChecked())   # boşken yalnızca başlık satırı görünmesin

    def _on_toggle(self, on: bool):
        self.button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.table.setVisible(on and self.table.rowCount() > 0)
        self.empty_label.setVisible(on and self.table.rowCount() == 0)
        self.toggled.emit(self.role, on)


# ---- Katalog çekmecesi ---------------------------------------------------------------
class CatalogPanel(QWidget):
    add_requested = Signal(list)              # [anahtar]
    role_change_requested = Signal(str, str)  # anahtar, rol ("" = otomatik)
    closed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumWidth(340)
        self._catalog: list[SignalDef] = []
        self._pinned: set = set()
        self._new: set = set()
        self._leaves: dict[str, QTreeWidgetItem] = {}
        self._building = False

        title = QLabel("Sinyal kataloğu")
        title.setStyleSheet("font-size:15px;font-weight:700;")
        self.counts_label = QLabel("")
        self.counts_label.setStyleSheet("color:#51616F;")
        close = QPushButton("✕")
        close.setFixedWidth(30)
        close.clicked.connect(self.closed.emit)
        top = QHBoxLayout()
        top.addWidget(title)
        top.addStretch()
        top.addWidget(self.counts_label)
        top.addWidget(close)

        self.search = QLineEdit()
        self.search.setPlaceholderText("İsme göre ara...")
        self.search.textChanged.connect(self._apply_filter)

        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        chips = QHBoxLayout()
        chips.setSpacing(4)
        self._chip_keys = {}
        for key, label in (("all", "Tümü"), ("in", "Girişler"), ("out", "Çıkışlar"),
                           ("ovr", "Override çiftleri"), ("new", "Yeni"), ("free", "Panelde olmayanlar")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setStyleSheet("QPushButton{padding:3px 8px;border:1px solid #D6DEE6;border-radius:11px;background:#FFFFFF;color:#243442;}"
                            "QPushButton:checked{background:#0E6E8C;color:#FFFFFF;border-color:#0E6E8C;}")
            self._filter_group.addButton(b)
            self._chip_keys[b] = key
            chips.addWidget(b)
            if key == "all":
                b.setChecked(True)
        chips.addStretch()
        self._filter_group.buttonClicked.connect(lambda _b: self._apply_filter())

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        self.tree.itemChanged.connect(self._on_item_changed)

        self.selected_label = QLabel("0 sinyal seçili")
        clear = QPushButton("Seçimi temizle")
        clear.clicked.connect(self.clear_selection)
        self.add_button = QPushButton("Panele ekle (0)")
        self.add_button.setStyleSheet("QPushButton{background:#0E6E8C;color:#FFFFFF;font-weight:700;padding:6px 14px;border-radius:6px;}"
                                      "QPushButton:disabled{background:#9AA8B5;}")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._emit_add)
        bottom = QHBoxLayout()
        bottom.addWidget(self.selected_label)
        bottom.addStretch()
        bottom.addWidget(clear)
        bottom.addWidget(self.add_button)

        lay = QVBoxLayout(self)
        lay.addLayout(top)
        lay.addWidget(self.search)
        lay.addLayout(chips)
        lay.addWidget(self.tree, 1)
        lay.addLayout(bottom)

    # -- doldurma --
    def set_catalog(self, catalog: list[SignalDef], pinned, new_keys=()):
        self._catalog = catalog
        self._pinned = set(pinned)
        self._new = set(new_keys)
        self._rebuild()

    def set_pinned(self, pinned):
        self._pinned = set(pinned)
        self._rebuild()

    def _rebuild(self):
        self._building = True
        expanded = {self.tree.topLevelItem(i).text(0): self.tree.topLevelItem(i).isExpanded()
                    for i in range(self.tree.topLevelItemCount())}
        self.tree.clear()
        self._leaves.clear()
        tops: dict[str, QTreeWidgetItem] = {}

        def top(label):
            if label not in tops:
                it = QTreeWidgetItem([label, ""])
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                it.setCheckState(0, Qt.Unchecked)
                it.setBackground(0, QColor("#E1EEF6"))
                it.setBackground(1, QColor("#E1EEF6"))
                self.tree.addTopLevelItem(it)
                tops[label] = it
            return tops[label]

        def sub(parent, label, store):
            if (id(parent), label) not in store:
                it = QTreeWidgetItem(parent, [label, ""])
                f = it.font(0)
                f.setBold(True)
                it.setFont(0, f)
                it.setFlags(it.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsAutoTristate)
                it.setCheckState(0, Qt.Unchecked)
                store[(id(parent), label)] = it
            return store[(id(parent), label)]

        store: dict = {}
        n_dbc = sum(1 for s in self._catalog if s.source == "CAN")
        n_a2l = len(self._catalog) - n_dbc
        self.counts_label.setText(f"DBC: {n_dbc} sinyal · A2L: {n_a2l} sinyal")
        for s in self._catalog:
            if s.source == "CAN":
                is_in = s.role == ROLE_AIRCRAFT_IN
                parent = top("DBC · Girişler (uçak/arayüz → ECU)" if is_in else "DBC · Çıkışlar (ECU → arayüz)")
                snd = f" · {', '.join(s.senders)}" if s.senders else ""
                msg_item = sub(parent, f"{s.message}  0x{(s.frame_id or 0):X} · {s.cycle_ms or '—'} ms{snd}", store)
                msg_item.setData(0, Qt.UserRole, "msg")
                leaf_parent = msg_item
            elif s.role == ROLE_SENSOR_OVR:
                parent = top("A2L · Override çiftleri")
                leaf_parent = parent
            else:
                parent = top("A2L · Measurement (izleme)")
                leaf_parent = sub(parent, f"{s.group}_  ", store)
                leaf_parent.setData(0, Qt.UserRole, "msg")
            label = s.name
            if s.role == ROLE_SENSOR_OVR:
                label += "   (_Ovr_Val + _Ovr_En)" if s.ovr_en is not None else "   (_Ovr_En yok!)"
            leaf = QTreeWidgetItem(leaf_parent, [label, ""])
            leaf.setFlags(leaf.flags() | Qt.ItemIsUserCheckable)
            leaf.setCheckState(0, Qt.Unchecked)
            leaf.setData(0, Qt.UserRole, s.key)
            tag, color = "", None
            if s.key in self._pinned:
                tag, color = "panelde", C_OK
            elif s.key in self._new:
                tag, color = "yeni", C_WARN
            if s.role == ROLE_INTERNAL:
                tag = (tag + " · " if tag else "") + "iç sinyal"
            if s.role != s.default_role:
                tag = (tag + " · " if tag else "") + "elle sınıf"
            leaf.setText(1, tag)
            if color is not None:
                leaf.setForeground(1, color)
            leaf.setToolTip(0, s.description or s.key)
            self._leaves[s.key] = leaf
        for i in range(self.tree.topLevelItemCount()):
            it = self.tree.topLevelItem(i)
            it.setExpanded(expanded.get(it.text(0), True))
        self._building = False
        self._apply_filter()
        self._update_selection_ui()

    # -- süzgeç / seçim --
    def _current_chip(self) -> str:
        b = self._filter_group.checkedButton()
        return self._chip_keys.get(b, "all")

    def _apply_filter(self, *_):
        text = self.search.text().strip().lower()
        chip = self._current_chip()
        by_key = {s.key: s for s in self._catalog}

        def leaf_visible(key):
            s = by_key[key]
            if text and text not in s.name.lower():
                return False
            if chip == "in":
                return s.role in (ROLE_AIRCRAFT_IN, ROLE_SENSOR_OVR)
            if chip == "out":
                return s.role in (ROLE_OUTPUT, ROLE_INTERNAL)
            if chip == "ovr":
                return s.role == ROLE_SENSOR_OVR
            if chip == "new":
                return key in self._new
            if chip == "free":
                return key not in self._pinned
            return True

        def walk(item):
            if item.childCount() == 0:
                key = item.data(0, Qt.UserRole)
                vis = isinstance(key, str) and key in by_key and leaf_visible(key)
                item.setHidden(not vis)
                return vis
            any_vis = False
            for i in range(item.childCount()):
                any_vis = walk(item.child(i)) or any_vis
            item.setHidden(not any_vis)
            return any_vis

        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))

    def selected_keys(self) -> list:
        return [k for k, it in self._leaves.items()
                if it.checkState(0) == Qt.Checked and not it.isHidden()]

    def _update_selection_ui(self):
        n = len([k for k in self.selected_keys() if k not in self._pinned])
        self.selected_label.setText(f"{len(self.selected_keys())} sinyal seçili")
        self.add_button.setText(f"Panele ekle ({n})")
        self.add_button.setEnabled(n > 0)

    def _on_item_changed(self, item, col):
        if self._building or col != 0:
            return
        self._update_selection_ui()

    def clear_selection(self):
        self._building = True
        for it in self._leaves.values():
            it.setCheckState(0, Qt.Unchecked)
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setCheckState(0, Qt.Unchecked)
        self._building = False
        self._update_selection_ui()

    def _emit_add(self):
        keys = [k for k in self.selected_keys() if k not in self._pinned]
        if keys:
            self.add_requested.emit(keys)
            self.clear_selection()

    def _context_menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        key = item.data(0, Qt.UserRole)
        s = {x.key: x for x in self._catalog}.get(key) if isinstance(key, str) else None
        if s is None:
            return
        menu = QMenu(self)
        if s.source == "CAN":
            menu.addAction("Giriş olarak işaretle", lambda: self.role_change_requested.emit(s.key, ROLE_AIRCRAFT_IN))
            menu.addAction("Çıkış olarak işaretle", lambda: self.role_change_requested.emit(s.key, ROLE_OUTPUT))
        else:
            menu.addAction("Çıkış olarak işaretle", lambda: self.role_change_requested.emit(s.key, ROLE_OUTPUT))
        menu.addAction("İç sinyal olarak işaretle", lambda: self.role_change_requested.emit(s.key, ROLE_INTERNAL))
        menu.addAction("Otomatik sınıfa döndür", lambda: self.role_change_requested.emit(s.key, ""))
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ---- Fark özeti kutusu ------------------------------------------------------------------
class DiffDialog(QDialog):
    def __init__(self, diff: cp.CatalogDiff, parent=None):
        super().__init__(parent)
        self.setWindowTitle("DBC ve A2L dosyaları değişti")
        self.setMinimumWidth(640)
        lay = QVBoxLayout(self)
        t = QLabel("<b style='font-size:15px'>DBC ve A2L dosyaları değişti</b><br>"
                   "Çalışma listeniz ve görünümleriniz isme göre korunur.")
        lay.addWidget(t)
        cards = QHBoxLayout()
        for n, text, color in ((len(diff.added), "yeni sinyal", "#1B8A4C"),
                               (len(diff.changed), "aralık/birim/adres değişti", "#B9790F"),
                               (len(diff.removed), "artık yok", "#C22A1D")):
            lbl = QLabel(f"<span style='font-size:22px;font-weight:700;color:{color}'>{n}</span><br>{text}")
            lbl.setStyleSheet("background:#FFFFFF;border-radius:8px;padding:10px;")
            cards.addWidget(lbl, 1)
        lay.addLayout(cards)
        table = QTableWidget(0, 3)
        table.setHorizontalHeaderLabels(["Sinyal", "Kaynak", "Değişiklik"])
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        rows = ([(s.name, "DBC" if s.source == "CAN" else "A2L", "yeni sinyal", C_OK) for s in diff.added]
                + [(s.name, "DBC" if s.source == "CAN" else "A2L", t, C_WARN) for s, t in diff.changed]
                + [(s.name, "DBC" if s.source == "CAN" else "A2L", "dosyada artık yok", C_BAD) for s in diff.removed])
        table.setRowCount(len(rows))
        for r, (n, src, ch, color) in enumerate(rows):
            for c, text in enumerate((n, src, ch)):
                it = QTableWidgetItem(text)
                if c == 2:
                    it.setForeground(color)
                table.setItem(r, c, it)
        table.setMinimumHeight(180)
        lay.addWidget(table)
        ok = QPushButton("Tamam")
        ok.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(ok)
        lay.addLayout(row)


# ---- Ana sekme -------------------------------------------------------------------------------
class ControlPanelTab(QWidget):
    apply_requested = Signal(dict)            # {"can": {msg: {sig: val}}, "ccp": [{key, field, info, value}]}
    kill_overrides_requested = Signal(list)   # [CharacteristicInfo _Ovr_En]
    poll_requested = Signal()
    tx_toggle_requested = Signal(bool)        # True = durdur
    reload_requested = Signal()

    POLL_MS = 250
    UI_MS = 500

    def __init__(self, config: cp.ControlPanelConfig | None = None):
        super().__init__()
        self.config = config or cp.ControlPanelConfig(None)
        self._dbc = None
        self._a2l_db = None
        self._catalog: list[SignalDef] = []
        self._index: dict[str, SignalDef] = {}
        self._new_keys: set = set()
        self._state: dict[str, dict] = {}
        self._rows: dict[str, tuple] = {}         # anahtar -> (tablo, satır)
        self._building = False
        self._dirty: set = set()
        self._snapshot: dict = {}
        self._last_apply: float | None = None
        self._ccp_connected = False
        self._can_connected = False
        self._lost = False
        self._can_allowed = True
        self._tx_running: set = set()
        self._tx_paused = False
        self._src_mtimes: dict = {}
        self._files_changed_text = ""
        self.last_diff: cp.CatalogDiff | None = None
        self._diff_dialog = None
        self._can_out_by_frame: dict[int, list] = {}

        self._build_ui()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(self.POLL_MS)
        self._poll_timer.timeout.connect(self._on_poll_tick)
        self._poll_timer.start()
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(self.UI_MS)
        self._ui_timer.timeout.connect(self._on_ui_tick)
        self._ui_timer.start()
        self._file_timer = QTimer(self)
        self._file_timer.setInterval(2000)
        self._file_timer.timeout.connect(self._check_source_files)
        self._file_timer.start()
        self._reload_views_combo()
        self._rebuild_tables()

    # ======================= Arayüz kurulumu =======================
    def _build_ui(self):
        # --- araç çubuğu ---
        self.catalog_button = QPushButton("+ Sinyal kataloğu")
        self.catalog_button.setCheckable(True)
        self.catalog_button.setStyleSheet("QPushButton{border:1px solid #0E6E8C;color:#0E6E8C;background:#FFFFFF;font-weight:700;padding:6px 12px;border-radius:6px;}"
                                          "QPushButton:checked{background:#0E6E8C;color:#FFFFFF;}")
        self.catalog_button.toggled.connect(self._toggle_catalog)

        self.view_combo = QComboBox()
        self.view_combo.setMinimumWidth(150)
        self.view_combo.activated.connect(self._on_view_selected)
        self.view_save = QPushButton("Görünümü kaydet…")
        self.view_save.clicked.connect(self._save_view)
        self.view_delete = QPushButton("Görünümü sil")
        self.view_delete.setToolTip("Seçili kayıtlı görünümü (sinyal listesi) siler; senaryolarla ilgisi yoktur")
        self.view_delete.clicked.connect(self._delete_view)

        self.search = QLineEdit()
        self.search.setPlaceholderText("İsme göre ara...")
        self.search.setMaximumWidth(220)
        self.search.textChanged.connect(self._apply_filters)

        self.apply_button = QPushButton("Uygula (0)")
        self.apply_button.setStyleSheet("QPushButton{background:#0E6E8C;color:#FFFFFF;font-weight:700;padding:7px 18px;border-radius:6px;}"
                                        "QPushButton:disabled{background:#9AA8B5;}")
        self.apply_button.clicked.connect(self._on_apply_clicked)
        self.revert_button = QPushButton("Bekleyenleri geri al")
        self.revert_button.clicked.connect(self.revert_pending)
        self.kill_button = QPushButton("Tüm override'ları kapat")
        self.kill_button.setStyleSheet("QPushButton{border:1px solid #C22A1D;color:#C22A1D;background:#FBE3E0;font-weight:700;padding:6px 12px;border-radius:6px;}")
        self.kill_button.clicked.connect(self._on_kill_clicked)

        bar = QHBoxLayout()
        bar.addWidget(self.catalog_button)
        lbl_view = QLabel("Görünüm:")
        lbl_view.setToolTip("Görünüm = panelde hangi sinyallerin listelendiği (isimle kaydedilir)")
        bar.addWidget(lbl_view)
        bar.addWidget(self.view_combo)
        bar.addWidget(self.view_save)
        bar.addWidget(self.view_delete)
        bar.addWidget(self.search)
        bar.addStretch()
        bar.addWidget(self.kill_button)
        bar.addWidget(self.revert_button)
        bar.addWidget(self.apply_button)

        # --- süzgeç çipleri ---
        self._role_group = QButtonGroup(self)
        self._role_group.setExclusive(True)
        self._state_chips: dict[str, QPushButton] = {}
        self._role_chips: dict[str, QPushButton] = {}
        chip_css = ("QPushButton{padding:3px 10px;border:1px solid #D6DEE6;border-radius:12px;background:#FFFFFF;color:#243442;font-weight:600;}"
                    "QPushButton:checked{background:#0E6E8C;color:#FFFFFF;border-color:#0E6E8C;}")
        chips = QHBoxLayout()
        chips.setSpacing(6)
        lbl_show = QLabel("Göster:")
        lbl_show.setToolTip("Tek seçim: hangi grup listelensin")
        chips.addWidget(lbl_show)
        for key, label in (("all", "Tümü"), (ROLE_AIRCRAFT_IN, "Uçak girişleri"),
                           (ROLE_SENSOR_OVR, "Sensör girişleri"), (ROLE_OUTPUT, "Çıkışlar")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setStyleSheet(chip_css)
            self._role_group.addButton(b)
            self._role_chips[key] = b
            chips.addWidget(b)
            if key == "all":
                b.setChecked(True)
        self._role_group.buttonClicked.connect(lambda _b: self._apply_filters())
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color:#C9D3DC;")
        chips.addSpacing(6)
        chips.addWidget(sep)
        chips.addSpacing(6)
        lbl_state = QLabel("Süz:")
        lbl_state.setToolTip("Birlikte geçerli: seçilen koşulların hepsini sağlayan satırlar kalır")
        chips.addWidget(lbl_state)
        for key, label in (("pending", "Bekleyenler"), ("changed", "Değişenler"),
                           ("fault", "Arızalı"), ("ovr", "Override açık")):
            b = QPushButton(label)
            b.setCheckable(True)
            b.setStyleSheet(chip_css)
            b.toggled.connect(lambda _on: self._apply_filters())
            self._state_chips[key] = b
            chips.addWidget(b)
        self.compact_check = QPushButton("Sıkı görünüm")
        self.compact_check.setCheckable(True)
        self.compact_check.setStyleSheet(chip_css)
        self.compact_check.setChecked(self.config.compact)
        self.compact_check.toggled.connect(self._on_compact)
        chips.addStretch()
        chips.addWidget(self.compact_check)      # "Süz" grubundan ayrı: yalnızca satır yüksekliği

        # --- özet şeridi ---
        self.pending_label = QLabel("")
        self.apply_info_label = QLabel("Son uygulama: —")
        self.tx_label = QLabel("")
        self.ovr_label = QLabel("")
        self.tx_toggle = QPushButton("Gönderimi durdur")
        self.tx_toggle.setFlat(True)
        self.tx_toggle.setStyleSheet("QPushButton{color:#0E6E8C;font-weight:700;text-decoration:underline;border:0;}")
        self.tx_toggle.clicked.connect(self._on_tx_toggle)
        self.files_label = QLabel("")
        self.reload_button = QPushButton("Yeniden yükle")
        self.reload_button.setFlat(True)
        self.reload_button.setStyleSheet("QPushButton{color:#0E6E8C;font-weight:700;text-decoration:underline;border:0;}")
        self.reload_button.clicked.connect(self.reload_requested.emit)
        self.reload_button.setVisible(False)
        strip = QHBoxLayout()
        for w in (self.pending_label, self.apply_info_label, self.tx_label, self.tx_toggle,
                  self.ovr_label, self.files_label, self.reload_button):
            strip.addWidget(w)
            strip.addSpacing(10)
        strip.addStretch()

        self.banner = QLabel("")
        self.banner.setStyleSheet("background:#FBE3E0;color:#C22A1D;font-weight:700;padding:6px 10px;border-radius:6px;")
        self.banner.setVisible(False)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)

        # --- boş durum yönlendirmesi (hiç sinyal yokken 4 boş bölüm yerine) ---
        self.onboarding = QLabel(
            "<b>Kontrol Paneli — ECU'ya test girdisi verin ve çıkışları izleyin</b><br><br>"
            "1. DBC (CAN Monitor sekmesi) ve A2L (Kalibrasyon &gt; A2L) dosyalarını yükleyin.<br>"
            "2. <b>+ Sinyal kataloğu</b> ile istediğiniz sinyalleri panele ekleyin.<br>"
            "3. Değer hücresine yazın (sarı = bekleyen), sensör için <b>Override</b> kutusunu işaretleyin.<br>"
            "4. <b>Uygula</b> ile gönderin; sonucu <b>ECU'nun gördüğü</b> ve çıkış tablosunda izleyin.<br>"
            "5. İşiniz bitince <b>Tüm override'ları kapat</b>.<br><br>"
            "<span style='color:#51616F'>Değer göndermek için Mühendis veya Yönetici rolü gerekir.</span>")
        self.onboarding.setTextFormat(Qt.RichText)
        self.onboarding.setWordWrap(True)
        self.onboarding.setStyleSheet("background:#FFFFFF;border:1px solid #C9D3DC;border-radius:10px;"
                                      "padding:16px 20px;color:#121A22;")
        self.onboarding.setVisible(False)

        # --- bölümler ---
        self.sections: dict[str, _Section] = {}
        sec_lay = QVBoxLayout()
        sec_lay.setSpacing(4)
        for role in (ROLE_AIRCRAFT_IN, ROLE_SENSOR_OVR, ROLE_OUTPUT, ROLE_INTERNAL):
            sec = _Section(role)
            sec.toggled.connect(self._on_section_toggled)
            sec.table.itemChanged.connect(self._on_item_changed)
            sec.table.customContextMenuRequested.connect(lambda pos, t=sec.table: self._row_menu(t, pos))
            sec.table.paste_requested.connect(lambda t=sec.table: self._paste_into(t))
            self.sections[role] = sec
            sec_lay.addWidget(sec)
            if role in self.config.collapsed:
                sec.button.setChecked(False)
        sec_lay.insertWidget(0, self.onboarding)
        sec_lay.addStretch()
        sec_box = QWidget()
        sec_box.setLayout(sec_lay)

        # --- sağ panel ---
        self.pending_list = QListWidget()
        self.pending_list.setMinimumHeight(70)
        self.effects_list = QListWidget()
        self.effects_list.setMinimumHeight(70)
        self.effects_title = QLabel("Son uygulamanın etkisi")
        self.scenario_combo = QComboBox()
        self.scenario_combo.setEditable(True)
        self.scenario_combo.setPlaceholderText("senaryo ismi")
        b_load = QPushButton("Yükle")
        b_load.clicked.connect(self._scenario_load)
        b_save = QPushButton("Kaydet")
        b_save.clicked.connect(self._scenario_save)
        b_del = QPushButton("Sil")
        b_del.setToolTip("Seçili senaryoyu siler")
        b_del.clicked.connect(self._scenario_delete)
        srow = QHBoxLayout()
        srow.addWidget(b_load)
        srow.addWidget(b_save)
        srow.addWidget(b_del)
        right = QVBoxLayout()
        for title, w in (("Bekleyen değişiklikler", self.pending_list),):
            lab = QLabel(f"<b>{title}</b>")
            right.addWidget(lab)
            right.addWidget(w)
        self.effects_title.setText("<b>Son uygulamanın etkisi</b>")
        right.addWidget(self.effects_title)
        right.addWidget(self.effects_list)
        scen_lab = QLabel("<b>Senaryo</b>")
        scen_lab.setToolTip("Senaryo = sinyal DEĞERLERİ seti. Yükle, değerleri bekleyen olarak koyar; Uygula'ya basılana dek gönderilmez.")
        right.addWidget(scen_lab)
        right.addWidget(self.scenario_combo)
        right.addLayout(srow)
        right.addStretch()
        right_box = QWidget()
        self.right_box = right_box
        right_box.setLayout(right)
        right_box.setMinimumWidth(250)
        right_box.setMaximumWidth(330)

        main = QVBoxLayout()
        main.addLayout(bar)
        main.addLayout(chips)
        main.addLayout(strip)
        main.addWidget(self.banner)
        main.addWidget(self.status_label)
        body = QHBoxLayout()
        body.addWidget(sec_box, 1)
        body.addWidget(right_box)
        main.addLayout(body)
        main_box = QWidget()
        main_box.setLayout(main)

        self.catalog_panel = CatalogPanel()
        self.catalog_panel.setVisible(False)
        self.catalog_panel.add_requested.connect(self.add_signals)
        self.catalog_panel.role_change_requested.connect(self._set_role_override)
        self.catalog_panel.closed.connect(lambda: self.catalog_button.setChecked(False))

        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.addWidget(self.catalog_panel)
        self.splitter.addWidget(main_box)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        outer = QHBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.addWidget(self.splitter)

    # ======================= Kaynaklar (DBC / A2L) =======================
    def refresh_sources(self, dbc=None, a2l_db=None):
        """DBC/A2L (yeniden) yüklenince çağrılır: kataloğu yeniden çıkarır,
        öncekiyle farkı bulur (ilk yüklemede fark kutusu açılmaz)."""
        if dbc is not None:
            self._dbc = dbc
        if a2l_db is not None:
            self._a2l_db = a2l_db
        old = self._catalog
        summary = getattr(self._a2l_db, "summary", None) if self._a2l_db is not None else None
        dbc_ok = self._dbc if (self._dbc is not None and getattr(self._dbc, "is_loaded", False)) else None
        self._catalog = cp.build_catalog(dbc_ok, summary, self.config.input_nodes,
                                         self.config.role_overrides, self.config.cycle_overrides)
        self._index = cp.catalog_index(self._catalog)
        self._record_mtimes()
        diff = cp.diff_catalogs(old, self._catalog) if old else None
        self._new_keys = {s.key for s in diff.added} if diff else set()
        self.last_diff = diff
        self.catalog_panel.set_catalog(self._catalog, self.config.pinned, self._new_keys)
        self._rebuild_tables()
        if diff is not None and not diff.empty:
            self._diff_dialog = DiffDialog(diff, self)
            self._diff_dialog.open()
        self._set_files_changed(False)

    def _record_mtimes(self):
        self._src_mtimes = {}
        for kind, obj in (("dbc", self._dbc), ("a2l", self._a2l_db)):
            path = getattr(obj, "path", None) if obj is not None else None
            if path and os.path.exists(path):
                self._src_mtimes[kind] = (path, os.path.getmtime(path))

    def _check_source_files(self):
        changed = []
        for kind, (path, mt) in self._src_mtimes.items():
            try:
                if os.path.getmtime(path) != mt:
                    changed.append(kind.upper())
            except OSError:
                pass
        if changed:
            self._set_files_changed(True, " ve ".join(changed))

    def _set_files_changed(self, on: bool, which: str = ""):
        self.reload_button.setVisible(on)
        self.files_label.setText(f"{which} dosyası değişti" if on else "")
        self.files_label.setStyleSheet("color:#9A6208;font-weight:700;" if on else "")
        self._files_changed_text = which if on else ""

    def _set_role_override(self, key: str, role: str):
        if role:
            self.config.role_overrides[key] = role
        else:
            self.config.role_overrides.pop(key, None)
        self.config.save()
        self.refresh_sources()

    # ======================= Çalışma listesi =======================
    def add_signals(self, keys: list):
        added = 0
        for k in keys:
            if k not in self.config.pinned:
                self.config.pinned.append(k)
                added += 1
        if added:
            self._on_pinned_changed()
            self._set_status(f"{added} sinyal çalışma listesine eklendi.", True)

    def remove_signals(self, keys: list):
        for k in keys:
            if k in self.config.pinned:
                self.config.pinned.remove(k)
            self._state.pop(k, None)
        self._on_pinned_changed()

    def _on_pinned_changed(self):
        self.config.current_view = self.config.current_view if self.config.current_view in self.config.views else ""
        self.config.save()
        self.catalog_panel.set_pinned(self.config.pinned)
        self._rebuild_tables()
        self._reload_views_combo()

    def _sig(self, key: str) -> SignalDef:
        s = self._index.get(key)
        if s is None:
            return SignalDef(key=key, name=key.split(":", 1)[-1].split(".")[-1], role=ROLE_OUTPUT,
                             source="CAN", missing=True)
        return s

    def _st(self, key: str) -> dict:
        st = self._state.get(key)
        if st is None:
            st = {"applied": None, "pending": None, "en": False, "en_pending": None,
                  "live": None, "seen": None, "prev": None, "error": "", "hist": deque(maxlen=120)}
            self._state[key] = st
        return st

    def _default_value(self, s: SignalDef) -> float:
        if s.initial is not None:
            return s.initial
        if s.minimum is not None and s.minimum > 0:
            return s.minimum
        return 0.0

    # ======================= Tabloları oluştur =======================
    def _rebuild_tables(self):
        self._building = True
        self._rows.clear()
        by_role: dict[str, list] = {r: [] for r in cp.ALL_ROLES}
        for key in self.config.pinned:
            s = self._sig(key)
            by_role[s.role].append(s)
        self._can_out_by_frame = {}
        for role, sec in self.sections.items():
            t = sec.table
            t.setRowCount(0)
            t.setRowCount(len(by_role[role]))
            for r, s in enumerate(by_role[role]):
                self._rows[s.key] = (t, r)
                self._init_row(t, r, s)
                self._st(s.key)
                if s.source == "CAN" and role in (ROLE_OUTPUT, ROLE_INTERNAL) and s.frame_id is not None:
                    self._can_out_by_frame.setdefault(s.frame_id, []).append(s.key)
        self._building = False
        for key in list(self._rows):
            self._refresh_row(key)
        self._apply_filters()
        self._refresh_summary()

    def _init_row(self, t: _GroupTable, r: int, s: SignalDef):
        ncol = t.columnCount()
        for c in range(ncol):
            it = QTableWidgetItem("")
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            t.setItem(r, c, it)
        t.item(r, 1).setText(s.name + ("  (bulunamadı)" if s.missing else ""))
        f = t.item(r, 1).font()
        f.setBold(True)
        t.item(r, 1).setFont(f)
        t.item(r, 1).setToolTip(s.description or s.key)
        role = t.role
        if role == ROLE_AIRCRAFT_IN:
            t.item(r, 3).setText(s.unit)
            t.item(r, 4).setText(s.range_text())
            t.item(r, 5).setText(f"0x{(s.frame_id or 0):X} · {s.cycle_ms or '—'} ms  {s.message}")
            vi = t.item(r, 2)
            vi.setData(ROLE_CHOICES, s.choices)
            vi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if self._can_allowed and not s.missing:
                vi.setFlags(vi.flags() | Qt.ItemIsEditable)
        elif role == ROLE_SENSOR_OVR:
            vi = t.item(r, 3)
            vi.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if self._can_allowed and not s.missing and s.ovr_val is not None:
                vi.setFlags(vi.flags() | Qt.ItemIsEditable)
            oi = t.item(r, 2)
            if s.ovr_en is not None and self._can_allowed and not s.missing:
                oi.setFlags(oi.flags() | Qt.ItemIsUserCheckable)
                oi.setCheckState(Qt.Unchecked)
            else:
                oi.setToolTip("A2L'de _Ovr_En parametresi yok" if s.ovr_en is None else "Yetki yok")
            t.item(r, 5).setText(s.unit)
            t.item(r, 6).setText(f"{s.ovr_val.name if s.ovr_val else '—'} / "
                                 f"{s.ovr_en.name.rsplit('_', 1)[-1] if s.ovr_en else '—'}")
        else:
            t.item(r, 5).setText(s.unit)
            t.item(r, 6).setText(f"CAN · 0x{(s.frame_id or 0):X}" if s.source == "CAN" else "CCP · A2L")
            for c in (2, 3, 4):
                t.item(r, c).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    # ======================= Satır gösterimi =======================
    def _format_value(self, s: SignalDef, v) -> str:
        if v is None:
            return "—"
        if s.choices:
            label = s.choices.get(int(round(v)))
            return f"{int(round(v))} · {label}" if label else _fmt_num(v)
        if s.is_fault_like:
            return "ARIZA" if v else "ARIZA YOK"
        return _fmt_num(v)

    def _is_fault_active(self, s: SignalDef, v) -> bool:
        return v is not None and s.is_fault_like and bool(v)

    def _display_input_value(self, s: SignalDef, st: dict):
        if st["pending"] is not None:
            return st["pending"]
        if st["applied"] is not None:
            return st["applied"]
        return self._default_value(s)

    def _refresh_row(self, key: str):
        if key not in self._rows:
            return
        t, r = self._rows[key]
        s = self._sig(key)
        st = self._st(key)
        was = self._building
        self._building = True
        try:
            role = t.role
            pend_row = False
            fault_row = False
            changed_row = False
            dot = C_MUTED
            if role == ROLE_AIRCRAFT_IN:
                v = self._display_input_value(s, st)
                vi = t.item(r, 2)
                text = self._format_value(s, v) if s.choices else _fmt_num(v)
                if vi.text() != text and not self._is_editing(t, r, 2):
                    vi.setText(text)
                pend_row = st["pending"] is not None
                oor = self._out_of_range(s, v)
                vi.setForeground(C_BAD if oor else QColor("#121A22"))
                vi.setToolTip(f"Aralık dışı ({s.range_text()})" if oor else
                              (f"önce {self._format_value(s, st['applied'])}" if pend_row and st["applied"] is not None else ""))
                vi.setBackground(C_PEND_CELL if pend_row else QColor("#F7F9FB"))
                running = s.message in self._tx_running
                if self._lost:
                    gtxt, gcol = "durdu", C_BAD
                elif running:
                    gtxt, gcol = "● gidiyor", C_OK
                elif self._tx_paused:
                    gtxt, gcol = "duraklatıldı", C_WARN
                else:
                    gtxt, gcol = "○ bekliyor", C_MUTED
                gi = t.item(r, 6)
                gi.setText(gtxt)
                gi.setForeground(gcol)
                dot = C_OK if running else C_MUTED
            elif role == ROLE_SENSOR_OVR:
                oi = t.item(r, 2)
                en_eff = st["en_pending"] if st["en_pending"] is not None else st["en"]
                if s.ovr_en is not None and (oi.flags() & Qt.ItemIsUserCheckable):
                    oi.setCheckState(Qt.Checked if en_eff else Qt.Unchecked)
                if st["en_pending"] is not None:
                    label, col = ("AÇILACAK" if st["en_pending"] else "KAPATILACAK"), C_WARN
                else:
                    label, col = ("AÇIK", C_OK) if st["en"] else ("KAPALI", C_MUTED)
                oi.setText(label)
                oi.setForeground(col)
                vi = t.item(r, 3)
                if st["pending"] is not None:
                    shown = st["pending"]
                elif st["applied"] is not None:
                    shown = st["applied"]
                else:
                    shown = None
                text = _fmt_num(shown) if shown is not None else "—"
                if vi.text() != text and not self._is_editing(t, r, 3):
                    vi.setText(text)
                vi.setBackground(C_PEND_CELL if st["pending"] is not None else QColor("#F7F9FB"))
                vi.setForeground(QColor("#121A22") if en_eff else C_MUTED)
                seen = st["seen"]
                t.item(r, 4).setText(_fmt_num(seen) if seen is not None else "—")
                pend_row = st["pending"] is not None or st["en_pending"] is not None
                dot = C_OK if st["en"] else C_MUTED
            else:
                live = st["live"]
                vi = t.item(r, 2)
                vi.setText("bulunamadı" if s.missing else self._format_value(s, live))
                fault = self._is_fault_active(s, live)
                f = vi.font()
                f.setBold(True)
                vi.setFont(f)
                vi.setForeground(C_BAD if (fault or s.missing) else (C_OK if (s.is_fault_like and live is not None) else QColor("#121A22")))
                prev = self._snapshot.get(key)
                t.item(r, 3).setText(self._format_value(s, prev) if (key in self._snapshot) else "—")
                dtxt, dcol = "—", C_MUTED
                if key in self._snapshot and live is not None and prev is not None:
                    d = live - prev
                    if abs(d) > 1e-9:
                        changed_row = True
                        if s.choices or s.is_boolean:
                            dtxt = "değişti"
                        else:
                            dtxt = f"{d:+.4g}"
                        dcol = C_BAD if fault else C_WARN
                t.item(r, 4).setText(dtxt)
                t.item(r, 4).setForeground(dcol)
                fault_row = fault or s.missing
                dot = C_BAD if fault_row else (C_OK if live is not None else C_MUTED)
                hist = [(tt, vv) for tt, vv in st["hist"]]
                t.item(r, 7).setData(ROLE_SPARK, hist)
                if st["error"]:
                    vi.setToolTip(st["error"])
            # satır arka planı + nokta
            row_bg = (C_PEND_ROW if pend_row else C_FAULT_ROW if fault_row else
                      C_CHANGED_ROW if changed_row else QColor("#F7F9FB"))
            for c in range(t.columnCount()):
                it = t.item(r, c)
                if it is None:
                    continue
                if not (role == ROLE_AIRCRAFT_IN and c == 2 and pend_row) and not (role == ROLE_SENSOR_OVR and c == 3 and st["pending"] is not None):
                    it.setBackground(row_bg)
            dot_item = t.item(r, 0)
            dot_item.setText("●")
            dot_item.setForeground(dot)
            dot_item.setTextAlignment(Qt.AlignCenter)
        finally:
            self._building = was
        # filtre durumu satır özelliğine bağlı olabilir
        t._row_flags = getattr(t, "_row_flags", {})
        t._row_flags[r] = {"pending": pend_row, "changed": changed_row, "fault": fault_row,
                           "ovr": bool(role == ROLE_SENSOR_OVR and (st["en"] or st["en_pending"]))}

    @staticmethod
    def _is_editing(t: QTableWidget, r: int, c: int) -> bool:
        return t.state() == QAbstractItemView.EditingState and t.currentRow() == r and t.currentColumn() == c

    @staticmethod
    def _out_of_range(s: SignalDef, v) -> bool:
        if v is None:
            return False
        if s.minimum is not None and v < s.minimum - 1e-12:
            return True
        if s.maximum is not None and v > s.maximum + 1e-12:
            return True
        return False

    # ======================= Düzenleme =======================
    def _row_key_of(self, t: QTableWidget, r: int) -> str | None:
        for k, (tt, rr) in self._rows.items():
            if tt is t and rr == r:
                return k
        return None

    def _on_item_changed(self, item: QTableWidgetItem):
        if self._building:
            return
        t = item.tableWidget()
        key = self._row_key_of(t, item.row())
        if key is None:
            return
        s, st = self._sig(key), self._st(key)
        role = t.role
        if role == ROLE_AIRCRAFT_IN and item.column() == 2:
            self._edit_value(s, st, item.text(), t, item.row(), 2)
        elif role == ROLE_SENSOR_OVR and item.column() == 3:
            self._edit_value(s, st, item.text(), t, item.row(), 3)
        elif role == ROLE_SENSOR_OVR and item.column() == 2 and (item.flags() & Qt.ItemIsUserCheckable):
            want = item.checkState() == Qt.Checked
            st["en_pending"] = None if want == st["en"] else want
            self._refresh_row(key)
            self._refresh_summary()

    def _edit_value(self, s, st, text, t, r, c):
        v = cp.parse_input_value(text, s.choices)
        if v is None:
            self._set_status(f"{s.name}: “{text}” geçerli bir sayı değil.", False)
            st_text = None
            self._refresh_row(s.key)
            self._building = True
            cur = self._display_input_value(s, st) if s.role == ROLE_AIRCRAFT_IN else (st["pending"] if st["pending"] is not None else st["applied"])
            t.item(r, c).setText(self._format_value(s, cur) if (s.choices and cur is not None) else _fmt_num(cur))
            self._building = False
            return
        base = st["applied"] if st["applied"] is not None else (None if s.role == ROLE_SENSOR_OVR else self._default_value(s))
        if base is not None and abs(v - base) < 1e-12 and not (s.role == ROLE_AIRCRAFT_IN and st["applied"] is None and s.message not in self._tx_running):
            st["pending"] = None
        else:
            st["pending"] = v
        self._building = True
        t.item(r, c).setText(self._format_value(s, v) if s.choices else _fmt_num(v))
        self._building = False
        self._refresh_row(s.key)
        self._refresh_summary()

    def _paste_into(self, t: _GroupTable):
        if t.role not in VALUE_COL:
            return
        text = QApplication.clipboard().text()
        if not text.strip():
            return
        lines = [ln.split("\t")[0] for ln in text.replace("\r\n", "\n").split("\n") if ln.strip() != ""]
        start = max(0, t.currentRow())
        n = 0
        for i, val in enumerate(lines):
            r = start + i
            if r >= t.rowCount() or t.isRowHidden(r):
                continue
            key = self._row_key_of(t, r)
            if key is None:
                continue
            s, st = self._sig(key), self._st(key)
            v = cp.parse_input_value(val, s.choices)
            if v is None:
                continue
            st["pending"] = v
            self._refresh_row(key)
            n += 1
        self._refresh_summary()
        self._set_status(f"{n} hücre yapıştırıldı (bekleyen).", True)

    def _row_menu(self, t: _GroupTable, pos):
        rows = sorted({i.row() for i in t.selectedIndexes()})
        if not rows:
            idx = t.indexAt(pos)
            rows = [idx.row()] if idx.isValid() else []
        keys = [k for k in (self._row_key_of(t, r) for r in rows) if k]
        if not keys:
            return
        menu = QMenu(self)
        if t.role in VALUE_COL:
            menu.addAction("Seçili satırlara değer ata…", lambda: self._assign_value(t, keys))
            menu.addAction("Başlangıç değerine döndür", lambda: self._reset_to_default(keys))
        menu.addAction("Panelden çıkar", lambda: self.remove_signals(keys))
        sub = menu.addMenu("Sınıfını değiştir")
        for role, label in ((ROLE_AIRCRAFT_IN, "Giriş (uçak/arayüz)"), (ROLE_OUTPUT, "Çıkış"),
                            (ROLE_INTERNAL, "İç sinyal")):
            sub.addAction(label, lambda r=role: [self._set_role_override(k, r) for k in keys])
        sub.addAction("Otomatik sınıfa döndür", lambda: [self._set_role_override(k, "") for k in keys])
        menu.exec(t.viewport().mapToGlobal(pos))

    def _assign_value(self, t, keys):
        text, ok = QInputDialog.getText(self, "Değer ata", f"{len(keys)} satıra atanacak değer:")
        if not ok:
            return
        for k in keys:
            s, st = self._sig(k), self._st(k)
            v = cp.parse_input_value(text, s.choices)
            if v is not None:
                st["pending"] = v
                self._refresh_row(k)
        self._refresh_summary()

    def _reset_to_default(self, keys):
        for k in keys:
            s, st = self._sig(k), self._st(k)
            if s.role == ROLE_AIRCRAFT_IN:
                d = self._default_value(s)
                st["pending"] = None if (st["applied"] is not None and abs(st["applied"] - d) < 1e-12) else d
                self._refresh_row(k)
        self._refresh_summary()

    # ======================= Uygula / geri al / override kapat =======================
    def pending_items(self) -> list:
        """[(anahtar, alan, yeni, eski)] — alan: 'value' | 'enable'."""
        out = []
        for key in self.config.pinned:
            if key not in self._rows:
                continue
            s, st = self._sig(key), self._st(key)
            if st["pending"] is not None:
                out.append((key, "value", st["pending"], st["applied"]))
            if st["en_pending"] is not None:
                out.append((key, "enable", st["en_pending"], st["en"]))
        return out

    def revert_pending(self):
        for key in list(self._state):
            st = self._state[key]
            st["pending"] = None
            st["en_pending"] = None
            self._refresh_row(key)
        self._refresh_summary()

    def _on_apply_clicked(self):
        items = self.pending_items()
        if not items:
            return
        if not self._can_allowed:
            self._set_status("Yetki yok: giriş göndermek için Mühendis veya Yönetici rolü gerekir.", False)
            return
        oor = [self._sig(k).name for k, f, v, _o in items
               if f == "value" and self._out_of_range(self._sig(k), v)]
        if oor:
            ans = QMessageBox.question(
                self, "Aralık dışı değer",
                "Şu girişler tanımlı aralığın DIŞINDA:\n  " + "\n  ".join(oor) + "\n\nYine de uygulansın mı?")
            if ans != QMessageBox.Yes:
                return
        changes = self.build_changes(items)
        self._snapshot = {k: st["live"] for k, st in self._state.items()
                          if st["live"] is not None and self._sig(k).role in (ROLE_OUTPUT, ROLE_INTERNAL)}
        self._last_apply = time.time()
        self.apply_requested.emit(changes)

    def build_changes(self, items) -> dict:
        can: dict[str, dict] = {}
        ccp: list = []
        pending_value_keys = {k for k, f, _v, _o in items if f == "value"}
        for key, field, value, _old in items:
            s = self._sig(key)
            if s.role == ROLE_AIRCRAFT_IN:
                can.setdefault(s.message, {})[s.signal] = value
            elif s.role == ROLE_SENSOR_OVR and field == "value" and s.ovr_val is not None:
                ccp.append({"key": key, "field": "value", "info": s.ovr_val, "value": value})
        for key, field, value, _old in items:       # bayraklar değerlerden SONRA
            s = self._sig(key)
            if s.role == ROLE_SENSOR_OVR and field == "enable" and s.ovr_en is not None:
                ccp.append({"key": key, "field": "enable", "info": s.ovr_en, "value": 1 if value else 0})
        cycles = {m: self._sig_cycle(m) for m in can}
        return {"can": can, "ccp": ccp, "cycles": cycles}

    def _sig_cycle(self, message: str) -> int:
        for s in self._catalog:
            if s.message == message and s.cycle_ms:
                return s.cycle_ms
        return cp.DEFAULT_CYCLE_MS

    def apply_finished(self, results: list):
        """MainWindow sonucu bildirir: [{"key","field","ok","error"}]."""
        ok_n = bad_n = 0
        errors = []
        for r in results:
            st = self._st(r["key"])
            s = self._sig(r["key"])
            if r["ok"]:
                ok_n += 1
                if r["field"] == "value" and st["pending"] is not None:
                    st["applied"] = st["pending"]
                    st["pending"] = None
                elif r["field"] == "enable" and st["en_pending"] is not None:
                    st["en"] = bool(st["en_pending"])
                    st["en_pending"] = None
                st["error"] = ""
            else:
                bad_n += 1
                st["error"] = r.get("error", "")
                errors.append(f"{s.name}: {st['error']}")
            self._refresh_row(r["key"])
        self.apply_info_label.setText("Son uygulama: " + time.strftime("%H:%M:%S"))
        msg = f"{ok_n} değişiklik uygulandı."
        if bad_n:
            msg += f" {bad_n} başarısız: " + "; ".join(errors[:3])
        self._set_status(msg, bad_n == 0)
        self._refresh_summary()
        self._refresh_effects()

    def set_external_applied(self, message: str, signal: str, value: float):
        """Ana Sayfa'daki Simülasyon Girişleri bir değeri gönderdiğinde,
        aynı sinyal burada da 'uygulanmış' olarak görünsün."""
        key = f"dbc:{message}.{signal}"
        if key not in self._index:
            return
        st = self._st(key)
        st["applied"] = float(value)
        if st["pending"] is not None and st["pending"] == st["applied"]:
            st["pending"] = None
        if key in self._rows:
            self._refresh_row(key)
            self._refresh_summary()

    def _on_kill_clicked(self):
        infos = [s.ovr_en for s in self._catalog if s.role == ROLE_SENSOR_OVR and s.ovr_en is not None]
        # çalışma listesinde olmayan ama kataloğdaki TÜM override çiftleri de kapatılır
        self.kill_overrides_requested.emit(infos)

    def overrides_killed(self):
        for key, st in self._state.items():
            st["en"] = False
            st["en_pending"] = None
            self._refresh_row(key)
        self._refresh_summary()

    # ======================= Canlı değerler (MainWindow'dan) =======================
    def on_can_frame(self, frame_id: int, data: bytes):
        keys = self._can_out_by_frame.get(frame_id)
        if not keys or self._dbc is None:
            return
        msg = self._dbc.get_message_by_frame_id(frame_id)
        if msg is None:
            return
        try:
            values = msg.decode(bytes(data), decode_choices=False)
        except Exception:
            return
        for k in keys:
            s = self._index.get(k)
            if s is not None and s.signal in values:
                v = values[s.signal]
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                self._st(k)["live"] = v
                self._dirty.add(k)

    def ccp_poll_targets(self) -> list:
        """[(anahtar, tür, info)] — tür: 'live' (çıkış) | 'seen' (sensör: ECU'nun
        gördüğü) | 'en' (override bayrağı). Yalnızca çalışma listesindekiler."""
        out = []
        for key in self.config.pinned:
            if key not in self._rows:
                continue
            s = self._sig(key)
            if s.missing:
                continue
            if s.role == ROLE_SENSOR_OVR:
                if s.meas is not None and s.meas.address is not None:
                    out.append((key, "seen", s.meas))
                if s.ovr_en is not None:
                    out.append((key, "en", s.ovr_en))
            elif s.source == "CCP" and s.role in (ROLE_OUTPUT, ROLE_INTERNAL):
                if s.role == ROLE_INTERNAL and ROLE_INTERNAL in self.config.collapsed:
                    continue
                if s.meas is not None and s.meas.address is not None:
                    out.append((key, "live", s.meas))
        return out

    def set_ccp_value(self, key: str, kind: str, value: float):
        st = self._st(key)
        if kind == "en":
            st["en"] = bool(round(value))
            if st["en_pending"] is not None and st["en_pending"] == st["en"]:
                st["en_pending"] = None
        elif kind == "seen":
            st["seen"] = value
        else:
            st["live"] = value
        st["error"] = ""
        st["t_live"] = time.monotonic()
        self._dirty.add(key)

    def set_ccp_error(self, key: str, message: str):
        self._st(key)["error"] = message
        self._dirty.add(key)

    # ======================= Zamanlayıcılar =======================
    def _on_poll_tick(self):
        if self._ccp_connected and not self._lost and self.isVisible() and self.ccp_poll_targets():
            self.poll_requested.emit()

    STALE_SECONDS = 3.0

    def _on_ui_tick(self):
        now = time.monotonic()
        for key, (t, r) in list(self._rows.items()):
            st = self._st(key)
            # Bayat değer "canlı" gibi kalmasın: CCP kopmuş/ECU susmuşsa temizle.
            t_live = st.get("t_live")
            if t_live is not None and (now - t_live > self.STALE_SECONDS
                                       or not self._ccp_connected or self._lost):
                if st["live"] is not None or st["seen"] is not None:
                    st["live"] = None
                    st["seen"] = None
                    self._dirty.add(key)
            if t.role in (ROLE_OUTPUT, ROLE_INTERNAL) and st["live"] is not None:
                st["hist"].append((now, st["live"]))
            while st["hist"] and now - st["hist"][0][0] > HIST_SECONDS:
                st["hist"].popleft()
        if not self.isVisible():
            return                      # gizli sekmede satırları boşuna yenileme
        keys = set(self._dirty)
        self._dirty.clear()
        for key, (t, r) in self._rows.items():
            if key in keys or t.role in (ROLE_OUTPUT, ROLE_INTERNAL):
                self._refresh_row(key)
        self._refresh_effects()
        self._refresh_summary(light=True)

    # ======================= Süzgeç / özet =======================
    def _on_compact(self, on: bool):
        self.config.compact = on
        self.config.save()
        self._apply_filters()

    def _on_section_toggled(self, role: str, on: bool):
        if on and role in self.config.collapsed:
            self.config.collapsed.remove(role)
        elif not on and role not in self.config.collapsed:
            self.config.collapsed.append(role)
        self.config.save()

    def _apply_filters(self, *_):
        text = self.search.text().strip().lower()
        checked = self._role_group.checkedButton()
        role_filter = next((k for k, b in self._role_chips.items() if b is checked), "all")
        state_filters = [k for k, b in self._state_chips.items() if b.isChecked()]
        for role, sec in self.sections.items():
            t = sec.table
            flags = getattr(t, "_row_flags", {})
            visible_count = 0
            sec_vis = role_filter == "all" or role == role_filter or (
                role_filter == ROLE_OUTPUT and role == ROLE_INTERNAL)
            for r in range(t.rowCount()):
                key = self._row_key_of(t, r)
                hide = not sec_vis
                if not hide and text and key and text not in self._sig(key).name.lower():
                    hide = True
                if not hide:
                    fl = flags.get(r, {})
                    for sf in state_filters:
                        if not fl.get(sf):
                            hide = True
                            break
                t.setRowHidden(r, hide)
                if not hide:
                    visible_count += 1
            sec.setVisible(sec_vis)
            t.fit_height(self.compact_check.isChecked())
            extra = ""
            if role == ROLE_SENSOR_OVR:
                n_on = sum(1 for k, (tt, _r) in self._rows.items() if tt is t and self._st(k)["en"])
                extra = f"{n_on} override açık"
            elif role == ROLE_OUTPUT:
                n_f = sum(1 for k, (tt, _r) in self._rows.items()
                          if tt is t and self._is_fault_active(self._sig(k), self._st(k)["live"]))
                extra = f"{n_f} arıza"
            sec.set_summary(t.rowCount(), extra)
        # hiç sinyal yoksa 4 boş bölüm yerine kısa kullanım yönlendirmesi göster
        total = sum(sec.table.rowCount() for sec in self.sections.values())
        self.onboarding.setVisible(total == 0)
        self.right_box.setVisible(total > 0)     # boşken yan panel (bekleyen/etki/senaryo) gizli
        if total == 0:
            for sec in self.sections.values():
                sec.setVisible(False)

    def _refresh_summary(self, light: bool = False):
        items = self.pending_items()
        n = len(items)
        self.apply_button.setText(f"Uygula ({n})")
        self.apply_button.setEnabled(n > 0 and self._can_allowed)
        self.revert_button.setEnabled(n > 0)
        self.pending_label.setText(f"<b style='color:#9A6208'>{n} bekleyen değişiklik</b>" if n else "Bekleyen değişiklik yok")
        n_ovr = sum(1 for k in self._rows if self._sig(k).role == ROLE_SENSOR_OVR and self._st(k)["en"])
        self.ovr_label.setText(f"Override aktif: <b>{n_ovr}</b>")
        self.tx_label.setText(f"Periyodik gönderim: <b>{len(self._tx_running)}</b> mesaj")
        self.tx_toggle.setText("Gönderimi başlat" if self._tx_paused else "Gönderimi durdur")
        self.tx_toggle.setVisible(bool(self._tx_running) or self._tx_paused)
        self.pending_list.clear()
        for key, field, new, old in items:
            s = self._sig(key)
            if field == "enable":
                txt = f"{s.name} override  {'KAPALI' if not old else 'AÇIK'} → {'AÇIK' if new else 'KAPALI'}"
            else:
                a = "—" if old is None else self._format_value(s, old)
                txt = f"{s.name}  {a} → {self._format_value(s, new)} {s.unit}".rstrip()
            self.pending_list.addItem(txt)
        if not light:
            self._apply_filters()
        else:
            for sec in self.sections.values():
                pass

    def _refresh_effects(self):
        self.effects_list.clear()
        if not self._snapshot:
            return
        for key, old in self._snapshot.items():
            st = self._state.get(key)
            if st is None or st["live"] is None or old is None:
                continue
            if abs(st["live"] - old) > 1e-9:
                s = self._sig(key)
                it = self.effects_list.addItem(
                    f"{s.name}   {self._format_value(s, old)} → {self._format_value(s, st['live'])}")
                item = self.effects_list.item(self.effects_list.count() - 1)
                item.setForeground(C_BAD if self._is_fault_active(s, st["live"]) else C_WARN)

    def _set_status(self, text: str, ok: bool):
        self.status_label.setText(text)
        self.status_label.setStyleSheet("color:#1B8A4C;" if ok else "color:#C22A1D;")

    # ======================= Dış durumlar =======================
    def set_connection_state(self, can: bool, ccp: bool, lost: bool = False):
        self._can_connected, self._ccp_connected, self._lost = can, ccp, lost
        if lost:
            self.banner.setText("Bağlantı koptu — gönderim durdu; override'lar “bilinmiyor”.")
            self.banner.setVisible(True)
        else:
            self.banner.setVisible(False)
        for k in list(self._rows):
            self._refresh_row(k)

    def set_allowed(self, allowed: bool):
        """Rol yetkisi (Mühendis/Yönetici). Operatörde giriş kutuları kilitlenir."""
        if allowed != self._can_allowed:
            self._can_allowed = allowed
            self._rebuild_tables()
        self.kill_button.setEnabled(True)   # güvenlik amaçlı bırakma: rol gerektirmez

    def set_tx_running(self, names: set, paused: bool = False):
        self._tx_running = set(names)
        self._tx_paused = paused
        for k, (t, r) in self._rows.items():
            if t.role == ROLE_AIRCRAFT_IN:
                self._refresh_row(k)
        self._refresh_summary(light=True)

    def _on_tx_toggle(self):
        self.tx_toggle_requested.emit(not self._tx_paused)

    # ======================= Katalog / görünümler / senaryolar =======================
    def _toggle_catalog(self, on: bool):
        self.catalog_panel.setVisible(on)
        if on:
            self.splitter.setSizes([420, 900])

    def _reload_views_combo(self):
        self.view_combo.blockSignals(True)
        self.view_combo.clear()
        self.view_combo.addItem("(Çalışma listesi)")
        for name in sorted(self.config.views):
            self.view_combo.addItem(name)
        i = self.view_combo.findText(self.config.current_view) if self.config.current_view else 0
        self.view_combo.setCurrentIndex(max(0, i))
        self.view_combo.blockSignals(False)
        self.view_delete.setEnabled(self.view_combo.currentIndex() > 0)

    def _on_view_selected(self, idx: int):
        name = self.view_combo.itemText(idx)
        if idx <= 0 or name not in self.config.views:
            self.config.current_view = ""
        else:
            self.config.current_view = name
            self.config.pinned = list(self.config.views[name])
        self.config.save()
        self.catalog_panel.set_pinned(self.config.pinned)
        self._rebuild_tables()
        self.view_delete.setEnabled(idx > 0)

    def _save_view(self):
        name, ok = QInputDialog.getText(self, "Görünümü kaydet", "Görünüm ismi:",
                                        text=self.config.current_view or "")
        name = name.strip()
        if not ok or not name:
            return
        self.config.views[name] = list(self.config.pinned)
        self.config.current_view = name
        self.config.save()
        self._reload_views_combo()
        self._set_status(f"“{name}” görünümü kaydedildi ({len(self.config.pinned)} sinyal).", True)

    def _delete_view(self):
        name = self.view_combo.currentText()
        if name in self.config.views:
            del self.config.views[name]
            self.config.current_view = ""
            self.config.save()
            self._reload_views_combo()

    def _scenario_values(self) -> dict:
        data = {}
        for key in self.config.pinned:
            s, st = self._sig(key), self._st(key)
            if s.role == ROLE_AIRCRAFT_IN:
                data[key] = {"value": self._display_input_value(s, st)}
            elif s.role == ROLE_SENSOR_OVR:
                d = {}
                v = st["pending"] if st["pending"] is not None else st["applied"]
                if v is not None:
                    d["value"] = v
                d["enable"] = bool(st["en_pending"] if st["en_pending"] is not None else st["en"])
                data[key] = d
        return data

    def _scenario_save(self):
        name = self.scenario_combo.currentText().strip()
        if not name:
            self._set_status("Senaryo için bir isim yazın.", False)
            return
        self.config.scenarios[name] = self._scenario_values()
        self.config.save()
        self._reload_scenarios(name)
        self._set_status(f"“{name}” senaryosu kaydedildi.", True)

    def _scenario_load(self):
        name = self.scenario_combo.currentText().strip()
        sc = self.config.scenarios.get(name)
        if sc is None:
            self._set_status("Senaryo bulunamadı.", False)
            return
        n = 0
        for key, d in sc.items():
            if key not in self._rows:
                continue
            st = self._st(key)
            if "value" in d:
                v = float(d["value"])
                st["pending"] = None if (st["applied"] is not None and abs(st["applied"] - v) < 1e-12) else v
            if "enable" in d and self._sig(key).role == ROLE_SENSOR_OVR:
                en = bool(d["enable"])
                st["en_pending"] = None if en == st["en"] else en
            self._refresh_row(key)
            n += 1
        self._refresh_summary()
        self._set_status(f"“{name}” senaryosu yüklendi ({n} sinyal, bekleyen olarak). Uygula'ya basın.", True)

    def _scenario_delete(self):
        name = self.scenario_combo.currentText().strip()
        if name in self.config.scenarios:
            del self.config.scenarios[name]
            self.config.save()
            self._reload_scenarios("")

    def _reload_scenarios(self, select: str = ""):
        self.scenario_combo.blockSignals(True)
        self.scenario_combo.clear()
        self.scenario_combo.addItems(sorted(self.config.scenarios))
        self.scenario_combo.setCurrentText(select)
        self.scenario_combo.blockSignals(False)

    def showEvent(self, e):
        super().showEvent(e)
        self._reload_scenarios(self.scenario_combo.currentText())
        self._apply_filters()
