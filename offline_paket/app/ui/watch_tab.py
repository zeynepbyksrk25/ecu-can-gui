"""Parametre Listesi (izleme) sekmesi: istenen sayıda Measurement /
Characteristic / elle girilmiş adresi tek tabloda aynı anda izleme ve
değiştirme. Sütunlar: Adres, Hex (ham baytlar), Değer (Value), İsim (Name),
Birim, Tip.

Diğer sekmeler gibi bu widget de gerçek CCP işlemini YAPMAZ — isteği
sinyal olarak bildirir; MainWindow CCPClient ile okuyup/yazıp sonucu
set_row_value / set_row_error / commit_written / set_write_result ile geri
bildirir. Değer hücresi düzenlenince ECU'ya yazılmaz; yalnızca satırın
"bekleyen" (pending_text) değeri olarak sarıya boyanır ve ancak yazma
düğmelerine basılınca write_requested yayılır (onay diyaloğu yok).
"""

import logging
import math
import os
import re
import time
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QWidget, QStyledItemDelegate, QAbstractItemDelegate,
)

from app import theme
from app.persist import atomic_write_json, load_json
from app.ccp import codec

log = logging.getLogger(__name__)

POLL_INTERVAL_MS = 250          # canlı okuma: önbellekten (bloklamaz), bkz. app/ccp/worker.py
VERIFY_WINDOW_S = 1.5           # yazılan değerin ECU'dan geri okunarak doğrulanma süresi
FLASH_S = 0.9                   # başarıyla yazılan satırın yeşil yanma süresi
ROLE_OBJECT = Qt.UserRole

# Sütun sırası
COL_ADDR, COL_HEX, COL_VALUE, COL_NAME, COL_UNIT, COL_TYPE, COL_DESC = range(7)
HEADERS = ["Adres", "Hex", "Değer (Value)", "İsim (Name)", "Birim", "Tip", "Açıklama"]

OK_BG = QColor("#DDF3E5")        # yazma doğrulandı (kısa süre)
OK_FG = QColor("#1B6B3E")
PENDING_BG = QColor("#FFE8A8")   # yazılmayı bekleyen değer (map_editor MODIFIED_BG ile aynı)
PENDING_FG = QColor("#7A4F00")
INVALID_BG = QColor("#FBDCD8")   # ayrıştırılamayan sayı
INVALID_FG = QColor("#A8241A")
ERROR_FG = QColor(theme.DANGER)

_HEX_RE = re.compile(r"[+-]?0[xX][0-9a-fA-F]+")

# Combobox'ta önce sık kullanılan tipler; codec'in bildiği gerisi eklenir.
_PREFERRED_TYPES = ["UBYTE", "SBYTE", "UWORD", "SWORD", "ULONG", "SLONG",
                    "FLOAT32_IEEE", "FLOAT64_IEEE", "A_UINT64", "A_INT64",
                    "FLOAT16_IEEE"]


def supported_datatypes() -> list[str]:
    known = list(codec._STRUCT_CODES.keys())
    ordered = [t for t in _PREFERRED_TYPES if t in known]
    return ordered + [t for t in known if t not in ordered]


def parse_value_text(text: str) -> float:
    """Kullanıcının girdiği değer metnini sayıya çevirir. Ondalık virgül
    ('1,5') ve onaltılık tam sayı ('0x1F') kabul edilir. Hata -> ValueError."""
    t = (text or "").strip()
    if not t:
        raise ValueError("Değer boş.")
    if _HEX_RE.fullmatch(t):
        return float(int(t, 16))
    try:
        value = float(t.replace(",", "."))
    except ValueError:
        raise ValueError(f"Geçerli bir sayı değil: {text!r}")
    if not math.isfinite(value):
        raise ValueError(f"Sonlu bir sayı olmalı: {text!r}")
    return value


def _parse_hex_field(text: str, field_name: str, max_value: int) -> int:
    t = (text or "").strip()
    t = t[2:] if t.lower().startswith("0x") else t
    try:
        value = int(t, 16)
    except ValueError:
        raise ValueError(f"{field_name} geçerli bir onaltılık (hex) değer değil: {text!r}")
    if not 0 <= value <= max_value:
        raise ValueError(f"{field_name} 0 ile 0x{max_value:X} arasında olmalı.")
    return value


@dataclass
class WatchEntry:
    name: str
    kind: str                  # "measurement" | "characteristic" | "manual"
    address: int
    datatype: str              # ccp_codec'in anladığı A2L datatype adı
    unit: str = ""
    address_extension: int = 0
    byte_order: str | None = None
    compu_method: object | None = None
    read_only: bool = True
    raw: bytes | None = None
    phys: float | int | None = None
    error: str | None = None
    pending_text: str | None = None
    # A2L satırı henüz gerçek nesneye çözülmediyse False (diskten yüklenmiş
    # ama A2L yok / nesne bulunamadı). MainWindow bu satırları okumamalı.
    resolved: bool = True
    description: str = ""      # A2L LONGIDENTIFIER (açıklama), salt okunur
    # Yazma doğrulaması: yazılan ham baytlar ECU'dan geri okunup eşleşmeli
    verify_raw: bytes | None = None
    verify_deadline: float = 0.0
    flash_until: float = 0.0


def format_hex_bytes(raw: bytes | None) -> str:
    return " ".join(f"{b:02X}" for b in raw) if raw else ""


def format_phys(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    return f"{value:.9g}"


# ---------------------------------------------------------------------------
# Diyaloglar
# ---------------------------------------------------------------------------
class A2LPickerDialog(QDialog):
    """A2L'den çoklu nesne seçme. Yalnızca adresi tanımlı tek-elemanlı
    (SCALAR characteristic + tüm measurement) nesneler listelenir."""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.setWindowTitle("A2L'den Ekle")
        self.resize(560, 480)

        self._objects: list[tuple[str, object]] = []
        summary = getattr(db, "summary", None)
        if summary is not None:
            for m in summary.measurements:
                if m.address:
                    self._objects.append(("measurement", m))
            for c in summary.characteristics:
                if c.kind == "SCALAR" and c.address:
                    self._objects.append(("characteristic", c))

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("İsme göre ara...")
        self.measurement_check = QCheckBox("Measurement")
        self.characteristic_check = QCheckBox("Characteristic")
        self.measurement_check.setChecked(True)
        self.characteristic_check.setChecked(True)

        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list_widget.itemDoubleClicked.connect(lambda _i: self.accept())

        self.count_label = QLabel("")
        hint = QLabel("İpucu: Dizi/tablo (ARRAY / CURVE / MAP) nesneleri burada "
                      "listelenmez; onlar için Harita Editörü'nü kullanın.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.MUTED}; font-size: 11px;")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Seçilenleri Ekle")
        buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        filters = QHBoxLayout()
        filters.addWidget(self.measurement_check)
        filters.addWidget(self.characteristic_check)
        filters.addStretch()
        filters.addWidget(self.count_label)

        layout = QVBoxLayout(self)
        layout.addWidget(self.search_edit)
        layout.addLayout(filters)
        layout.addWidget(self.list_widget, stretch=1)
        layout.addWidget(hint)
        layout.addWidget(buttons)

        self.search_edit.textChanged.connect(self._populate)
        self.measurement_check.toggled.connect(self._populate)
        self.characteristic_check.toggled.connect(self._populate)
        self._populate()

    @staticmethod
    def label_for(kind: str, obj) -> str:
        kind_text = "Measurement" if kind == "measurement" else "Characteristic"
        return f"{obj.name}  [{kind_text} · {obj.datatype} · 0x{obj.address:X}]"

    def _populate(self, *_args):
        text = self.search_edit.text().strip().lower()
        show_m = self.measurement_check.isChecked()
        show_c = self.characteristic_check.isChecked()
        self.list_widget.clear()
        for kind, obj in self._objects:
            if kind == "measurement" and not show_m:
                continue
            if kind == "characteristic" and not show_c:
                continue
            if text and text not in obj.name.lower():
                continue
            item = QListWidgetItem(self.label_for(kind, obj))
            item.setData(ROLE_OBJECT, (kind, obj))
            self.list_widget.addItem(item)
        self.count_label.setText(f"{self.list_widget.count()} nesne")

    def selected_objects(self) -> list[tuple[str, object]]:
        return [it.data(ROLE_OBJECT) for it in self.list_widget.selectedItems()]


class ManualEntryDialog(QDialog):
    """Elle adres girerek parametre ekleme."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manuel Ekle")
        self._entry: WatchEntry | None = None

        self.name_edit = QLineEdit()
        self.addr_edit = QLineEdit()
        self.addr_edit.setPlaceholderText("hex, örn. 0x00401A20")
        self.ext_edit = QLineEdit("0")
        self.ext_edit.setPlaceholderText("hex")
        self.type_combo = QComboBox()
        self.type_combo.addItems(supported_datatypes())
        self.unit_edit = QLineEdit()

        form = QFormLayout()
        form.addRow("İsim:", self.name_edit)
        form.addRow("Adres (hex):", self.addr_edit)
        form.addRow("Adres uzantısı (hex):", self.ext_edit)
        form.addRow("Tip:", self.type_combo)
        form.addRow("Birim:", self.unit_edit)

        self.warn_label = QLabel("")
        self.warn_label.setWordWrap(True)
        self.warn_label.setStyleSheet(f"color: {theme.DANGER};")

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Ekle")
        buttons.button(QDialogButtonBox.Cancel).setText("İptal")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.warn_label)
        layout.addWidget(buttons)

    def _on_accept(self):
        name = self.name_edit.text().strip()
        try:
            if not name:
                raise ValueError("İsim boş olamaz.")
            address = _parse_hex_field(self.addr_edit.text(), "Adres", 0xFFFFFFFF)
            ext = _parse_hex_field(self.ext_edit.text() or "0", "Adres uzantısı", 0xFF)
        except ValueError as exc:
            self.warn_label.setText(str(exc))
            return
        self._entry = WatchEntry(
            name=name, kind="manual", address=address,
            datatype=self.type_combo.currentText(),
            unit=self.unit_edit.text().strip(),
            address_extension=ext, read_only=False,
        )
        self.accept()

    def entry(self) -> WatchEntry | None:
        return self._entry


# ---------------------------------------------------------------------------
# Tablo
# ---------------------------------------------------------------------------
class _ValueDelegate(QStyledItemDelegate):
    """Değer hücresi düzenleyicisi: Enter = yazılacak değeri onayla, Esc = iptal, ODAK KAYBI = iptal
    (başka yere tıklayınca yanlışlıkla ECU'ya yazılmasın)."""

    def eventFilter(self, editor, event):  # noqa: N802
        if event.type() == QEvent.FocusOut:
            self.closeEditor.emit(editor, QAbstractItemDelegate.RevertModelCache)
            return True
        return super().eventFilter(editor, event)


class _WatchTable(QTableWidget):
    viewport_resized = Signal()

    def keyPressEvent(self, event):
        if event.matches(QKeySequence.Copy):
            self.copy_selection()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.viewport_resized.emit()

    def selection_text(self) -> str:
        indexes = self.selectedIndexes()
        if not indexes:
            return ""
        rows = sorted({i.row() for i in indexes})
        cols = sorted({i.column() for i in indexes})
        selected = {(i.row(), i.column()) for i in indexes}
        lines = []
        for r in rows:
            cells = []
            for c in cols:
                item = self.item(r, c)
                cells.append(item.text() if item and (r, c) in selected else "")
            lines.append("\t".join(cells))
        return "\n".join(lines)

    def copy_selection(self):
        text = self.selection_text()
        if text:
            QGuiApplication.clipboard().setText(text)


class WatchTab(QWidget):
    read_requested = Signal()          # tüm satırları oku
    write_requested = Signal(list)     # yazılacak satır indeksleri

    def __init__(self):
        super().__init__()
        self.a2l_db = None   # MainWindow tarafından A2LTab.db ile paylaşılır
        self._entries: list[WatchEntry] = []
        self._filling = False          # programatik doldurma: itemChanged'i yok say
        self._fitting = False          # İsim sütunu otomatik genişletilirken
        self._name_pref = 240          # kullanıcının istediği İsim sütunu genişliği
        self._storage_path: str | None = None
        self._connected = False
        self._write_allowed = True     # rol yazmaya yetkili mi (MainWindow bildirir; bkz. set_write_allowed)

        self._mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)

        layout = QVBoxLayout(self)
        layout.addLayout(self._build_toolbar())
        self.table = self._build_table()
        layout.addWidget(self.table, stretch=1)
        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.poll_timer = QTimer(self)
        self.poll_timer.setInterval(POLL_INTERVAL_MS)
        self.poll_timer.timeout.connect(self._on_poll_tick)

        self.set_connected(False)

    # ---- Arayüz ---------------------------------------------------------
    def _build_toolbar(self) -> QVBoxLayout:
        self.add_a2l_button = QPushButton("A2L'den Ekle…")
        self.add_manual_button = QPushButton("Manuel Ekle…")
        self.delete_button = QPushButton("Seçili Satırları Sil")
        self.clear_button = QPushButton("Listeyi Temizle")
        self.live_label = QLabel("● CCP bağlı değil")
        self.live_label.setStyleSheet(f"color: {theme.DANGER}; font-weight: bold;")
        self.hint_label = QLabel("")
        self._update_hint()

        self.add_a2l_button.clicked.connect(self._on_add_a2l)
        self.add_manual_button.clicked.connect(self._on_add_manual)
        self.delete_button.clicked.connect(self._on_delete_selected)
        self.clear_button.clicked.connect(self.clear_list)

        row1 = QHBoxLayout()
        for w in (self.add_a2l_button, self.add_manual_button,
                  self.delete_button, self.clear_button):
            row1.addWidget(w)
        row1.addStretch()
        row1.addWidget(self.live_label)

        outer = QVBoxLayout()
        outer.addLayout(row1)
        outer.addWidget(self.hint_label)
        return outer

    def _build_table(self) -> _WatchTable:
        table = _WatchTable(0, len(HEADERS))
        table.setHorizontalHeaderLabels(HEADERS)
        table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        table.setSelectionBehavior(QAbstractItemView.SelectItems)
        table.setEditTriggers(QAbstractItemView.DoubleClicked
                              | QAbstractItemView.EditKeyPressed
                              | QAbstractItemView.AnyKeyPressed)
        table.setAlternatingRowColors(True)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.Interactive)
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(50)
        for col, width in ((COL_ADDR, 110), (COL_HEX, 150), (COL_VALUE, 130),
                           (COL_NAME, self._name_pref), (COL_UNIT, 80), (COL_TYPE, 110), (COL_DESC, 260)):
            table.setColumnWidth(col, width)
        header.sectionResized.connect(self._on_section_resized)
        table.viewport_resized.connect(self._fit_name_column)
        table.itemChanged.connect(self._on_item_changed)
        table.setItemDelegateForColumn(COL_VALUE, _ValueDelegate(table))
        return table

    # İsim sütunu esnemesi: boş alan varsa İsim sütunu doldurur; yoksa kullanıcının
    # istediği genişlikte kalır ve yatay kaydırma çıkar.
    def _on_section_resized(self, index: int, _old: int, new: int):
        if self._fitting:
            return
        if index == COL_NAME:
            self._name_pref = max(new, 80)
        self._fit_name_column()

    def _fit_name_column(self):
        if self._fitting:
            return
        others = sum(self.table.columnWidth(c) for c in range(len(HEADERS)) if c != COL_NAME)
        target = max(self._name_pref, self.table.viewport().width() - others)
        if target != self.table.columnWidth(COL_NAME):
            self._fitting = True
            try:
                self.table.setColumnWidth(COL_NAME, target)
            finally:
                self._fitting = False

    # ---- Satır çizimi -----------------------------------------------------
    def _cell(self, row: int, col: int) -> QTableWidgetItem:
        item = self.table.item(row, col)
        if item is None:
            item = QTableWidgetItem()
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.table.setItem(row, col, item)
        return item

    def _is_editing(self, row: int) -> bool:
        # Kullanıcı Değer hücresine yazarken 500 ms'lik okuma yazdığını ezmesin.
        if self.table.state() != QAbstractItemView.EditingState:
            return False
        idx = self.table.currentIndex()
        return idx.row() == row and idx.column() == COL_VALUE

    @staticmethod
    def _set_text(item: QTableWidgetItem, text: str):
        if item.text() != text:
            item.setText(text)

    def _render_row(self, row: int):
        e = self._entries[row]
        self._filling = True
        try:
            addr = self._cell(row, COL_ADDR)
            self._set_text(addr, f"0x{e.address:08X}" if e.resolved else "")
            addr.setFont(self._mono)

            hex_item = self._cell(row, COL_HEX)
            self._set_text(hex_item, format_hex_bytes(e.raw))
            hex_item.setFont(self._mono)

            name = self._cell(row, COL_NAME)
            self._set_text(name, e.name)
            name_tip = f"{e.kind} · {e.name}"
            if e.address_extension:
                name_tip += f" · adres uzantısı 0x{e.address_extension:X}"
            if e.read_only:
                name_tip += " · salt okunur"
            name.setToolTip(name_tip)

            self._set_text(self._cell(row, COL_UNIT), e.unit)
            self._set_text(self._cell(row, COL_TYPE), e.datatype)
            desc = self._cell(row, COL_DESC)
            self._set_text(desc, e.description)
            desc.setToolTip(e.description)

            self._render_value_cell(row)
        finally:
            self._filling = False

    def _render_value_cell(self, row: int):
        """Değer hücresinin metni/rengi/tooltip'i satır durumundan türetilir."""
        e = self._entries[row]
        item = self._cell(row, COL_VALUE)
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if not e.read_only and e.resolved and self._write_allowed:
            flags |= Qt.ItemIsEditable
        # setFlags her çağrıda (değer aynı olsa da) Qt'ye "veri değişti" bildirir ve Qt AÇIK düzenleyicinin
        # içeriğini model değerine SIFIRLAR: canlı okuma her turda bu satırı yenilediği için kullanıcının
        # yazdığı karakterler siliniyordu ("değer girilmiyor"). Yalnızca gerçekten değişince çağrılır.
        if item.flags() != flags:
            item.setFlags(flags)
        if item.textAlignment() != (Qt.AlignRight | Qt.AlignVCenter):
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        bg = fg = None
        tips = []
        if not self._write_allowed and not e.read_only and e.resolved:
            tips.append("Yazmak için Mühendis veya Yönetici rolü gerekir.")
        if e.pending_text is not None:
            text = e.pending_text
            try:
                parse_value_text(e.pending_text)
                bg, fg = PENDING_BG, PENDING_FG
                tips.append("Bekleyen değer — henüz ECU'ya yazılmadı.")
            except ValueError as exc:
                bg, fg = INVALID_BG, INVALID_FG
                tips.append(f"Geçersiz değer: {exc}")
            if e.error:
                tips.append(f"Okuma hatası: {e.error}")
            if not self._is_editing(row):
                self._set_text(item, text)
        elif e.error:
            fg = ERROR_FG
            tips.append(e.error)
            if not self._is_editing(row):
                self._set_text(item, "hata")
        else:
            if not self._is_editing(row):
                self._set_text(item, format_phys(e.phys))
            if e.flash_until and time.monotonic() < e.flash_until:
                bg, fg = OK_BG, OK_FG
                tips.append("Yazıldı ve ECU'dan doğrulandı.")
        item.setBackground(bg) if bg else item.setData(Qt.BackgroundRole, None)
        item.setForeground(fg) if fg else item.setData(Qt.ForegroundRole, None)
        item.setToolTip("\n".join(tips))

    def _rebuild_table(self):
        self._filling = True
        try:
            self.table.setRowCount(len(self._entries))
        finally:
            self._filling = False
        for row in range(len(self._entries)):
            self._render_row(row)

    # ---- Ekleme / silme -----------------------------------------------------
    def _existing_names(self) -> set[str]:
        return {e.name for e in self._entries}

    def add_a2l_objects(self, objects) -> tuple[int, int]:
        """(kind, info) çiftlerini ekler; aynı ad varsa atlar. (eklenen, atlanan)."""
        names = self._existing_names()
        added = skipped = 0
        for kind, obj in objects:
            if obj.name in names:
                skipped += 1
                continue
            self._entries.append(self._entry_from_a2l(kind, obj))
            names.add(obj.name)
            added += 1
        if added:
            self._rebuild_table()
            self._save()
        return added, skipped

    def add_manual_entry(self, entry: WatchEntry) -> bool:
        if entry.name in self._existing_names():
            return False
        self._entries.append(entry)
        self._rebuild_table()
        self._save()
        return True

    @staticmethod
    def _entry_from_a2l(kind: str, obj) -> WatchEntry:
        return WatchEntry(
            name=obj.name, kind=kind, address=obj.address or 0,
            datatype=obj.datatype, unit=obj.unit or "",
            description=getattr(obj, "description", "") or "",
            address_extension=obj.address_extension or 0,
            byte_order=obj.byte_order, compu_method=obj.compu_method,
            read_only=True if kind == "measurement" else bool(obj.read_only),
        )

    def _on_add_a2l(self):
        if self.a2l_db is None or getattr(self.a2l_db, "summary", None) is None:
            QMessageBox.information(self, "A2L yüklü değil",
                                    "Önce Kalibrasyon > A2L sekmesinden bir A2L dosyası yükleyin.")
            return
        dlg = A2LPickerDialog(self.a2l_db, self)
        if dlg.exec() != QDialog.Accepted:
            return
        added, skipped = self.add_a2l_objects(dlg.selected_objects())
        self._set_status(f"{added} satır eklendi" +
                         (f", {skipped} tanesi zaten listede olduğu için atlandı." if skipped else "."),
                         None)

    def _on_add_manual(self):
        dlg = ManualEntryDialog(self)
        while dlg.exec() == QDialog.Accepted:
            entry = dlg.entry()
            if self.add_manual_entry(entry):
                self._set_status(f"'{entry.name}' eklendi.", None)
                return
            dlg.warn_label.setText(f"'{entry.name}' adlı satır zaten listede.")

    def _selected_rows(self) -> list[int]:
        return sorted({i.row() for i in self.table.selectedIndexes()})

    def remove_rows(self, rows):
        for r in sorted(set(rows), reverse=True):
            if 0 <= r < len(self._entries):
                del self._entries[r]
        self._rebuild_table()
        self._save()

    def _on_delete_selected(self):
        rows = self._selected_rows()
        if rows:
            self.remove_rows(rows)
            self._set_status(f"{len(rows)} satır silindi.", None)

    def clear_list(self):
        self._entries.clear()
        self._rebuild_table()
        self._save()

    # ---- Okuma ---------------------------------------------------------------
    # Okuma ARTIK her zaman canlı: CCP çevrimiçiyken liste boş değilse zamanlayıcı kendiliğinden
    # çalışır (önbellekten okur, arayüzü bekletmez). "Şimdi oku / Sürekli oku" kalktı.
    def _on_poll_tick(self):
        if self._entries and self._connected:
            self.read_requested.emit()
        self._expire_flash_and_verify()

    def stop_polling(self):
        self.poll_timer.stop()

    def start_polling(self):
        if not self.poll_timer.isActive():
            self.poll_timer.start()

    def is_polling(self) -> bool:
        return self.poll_timer.isActive()

    HINT_EDIT = "Değerler canlı izlenir · değiştirmek için Değer hücresine yazıp Enter'a basın (Esc iptal)"
    HINT_LOCKED = ("🔒 Değer yazmak için Mühendis veya Yönetici rolü gerekir — sağ üstteki ⚙ Ayarlar penceresinden "
                   "rol seçin. (Değerler yine canlı izlenir.)")

    def _update_hint(self):
        self.hint_label.setText(self.HINT_EDIT if self._write_allowed else self.HINT_LOCKED)
        color = theme.MUTED if self._write_allowed else theme.WARN_INK
        self.hint_label.setStyleSheet(f"color: {color};" + ("" if self._write_allowed else " font-weight: 600;"))

    def set_write_allowed(self, allowed: bool):
        """Rol değer yazmaya yetkili mi? Yetkisizse Değer hücreleri KİLİTLENİR (kullanıcı yazıp sonra "Yetki yok"
        ile geri alınmasın) ve ipucu satırı nedenini söyler. Yetki denetimi yazma anında ayrıca yapılır."""
        allowed = bool(allowed)
        if allowed == self._write_allowed:
            return
        self._write_allowed = allowed
        self._update_hint()
        for row in range(len(self._entries)):
            self._render_value_cell_guarded(row)

    def set_connected(self, connected: bool):
        self._connected = connected
        if connected:
            self.start_polling()
        else:
            self.stop_polling()

    def set_live_state(self, state: str, text: str):
        """CCP oturum durumu (idle/connecting/online/lost) -> araç çubuğundaki canlı etiketi."""
        color = {"idle": theme.DANGER, "connecting": theme.WARN_INK, "online": theme.OK, "lost": theme.DANGER}.get(state, theme.DANGER)
        dot = "●" if state in ("online", "lost", "connecting") else "○"
        self.live_label.setText(f"{dot} {text}")
        self.live_label.setStyleSheet(f"color: {color}; font-weight: bold;")

    # ---- MainWindow'un kullandığı erişimciler -----------------------------
    def entries(self) -> list[WatchEntry]:
        return list(self._entries)

    def pending_text(self, row: int) -> str | None:
        return self._entries[row].pending_text

    def set_row_value(self, row: int, raw: bytes, phys):
        e = self._entries[row]
        e.raw = bytes(raw)
        e.phys = phys
        e.error = None
        if e.verify_raw is not None:
            if bytes(raw) == e.verify_raw:               # yazılan değer ECU'dan aynen geri okundu
                e.verify_raw = None
                e.flash_until = time.monotonic() + FLASH_S
                self._set_status(f"'{e.name}': yazıldı ve ECU'dan doğrulandı.", True)
            elif time.monotonic() > e.verify_deadline:   # ECU başka bir değer okuyor
                e.verify_raw = None
                self._set_status(
                    f"'{e.name}': yazıldı ama ECU {format_phys(phys)} {e.unit} okuyor (beklenen değer tutmadı; "
                    "ECU değeri geri alıyor olabilir).", False)
        self._filling = True
        try:
            self._render_row(row)   # pending varsa Değer metnine dokunmaz
        finally:
            self._filling = False

    def set_row_error(self, row: int, message: str):
        e = self._entries[row]
        e.error = message
        e.raw = None
        e.phys = None
        self._render_row(row)

    def commit_written(self, row: int, phys):
        e = self._entries[row]
        e.pending_text = None
        e.phys = phys
        e.error = None
        try:   # Hex hücresi yazılan değeri yansıtsın (yeniden okuma gelene dek)
            raw_value = codec.physical_to_raw(e.compu_method, phys)
            e.raw = codec.encode_value(e.datatype, raw_value, e.byte_order)
            e.verify_raw = bytes(e.raw)
            e.verify_deadline = time.monotonic() + VERIFY_WINDOW_S
        except Exception:
            log.warning("%s: yazılan değer Hex hücresine yansıtılamadı", getattr(e, "name", "?"), exc_info=True)
        self._render_row(row)

    def discard_pending(self, rows):
        """Yazılamayan (yetki yok, ECU yok, geçersiz...) satırlarda bekleyen metni at: hücre canlı
        değere döner."""
        for row in rows:
            if 0 <= row < len(self._entries):
                self._entries[row].pending_text = None
                self._render_row(row)

    def _expire_flash_and_verify(self):
        now = time.monotonic()
        for row, e in enumerate(self._entries):
            if e.flash_until and now > e.flash_until:
                e.flash_until = 0.0
                self._render_row(row)
            if e.verify_raw is not None and now > e.verify_deadline and not self._connected:
                e.verify_raw = None

    def set_write_result(self, ok: bool, message: str):
        self._set_status(message, ok)

    def _set_status(self, message: str, ok: bool | None):
        self.status_label.setText(message)
        if ok is None:
            self.status_label.setStyleSheet("")
        else:
            self.status_label.setStyleSheet(f"color: {theme.OK};" if ok else f"color: {theme.DANGER};")

    # ---- Düzenleme / yazma ---------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem):
        if self._filling or item.column() != COL_VALUE:
            return
        row = item.row()
        if not 0 <= row < len(self._entries):
            return
        e = self._entries[row]
        if e.read_only or not e.resolved:
            return
        text = item.text().strip()
        e.pending_text = text or None
        self._render_value_cell_guarded(row)
        if not text:
            self._set_status(f"'{e.name}': bekleyen değer temizlendi.", None)
            return
        try:
            parse_value_text(text)
        except ValueError as exc:
            self._set_status(f"'{e.name}': geçersiz sayı — {exc}", False)
            return
        self._set_status(f"'{e.name}': ECU'ya yazılıyor…", None)
        self.write_requested.emit([row])        # Enter = anında RAM'e yaz

    def _render_value_cell_guarded(self, row: int):
        self._filling = True
        try:
            # Düzenleme bitmiş olduğundan metin temiz haliyle yeniden yazılır.
            self._render_value_cell(row)
        finally:
            self._filling = False

    def pending_rows(self) -> list[int]:
        return [i for i, e in enumerate(self._entries) if e.pending_text is not None]

    def _emit_write(self, rows: list[int], what: str):
        if not rows:
            self._set_status(f"{what}: yazılacak bekleyen (sarı) değer yok.", False)
            return
        self.write_requested.emit(rows)

    def _on_write_selected(self):
        selected = set(self._selected_rows())
        self._emit_write([r for r in self.pending_rows() if r in selected],
                         "Seçili satırlarda")

    def _on_write_all(self):
        self._emit_write(self.pending_rows(), "Listede")

    # ---- A2L çözümleme ---------------------------------------------------
    def refresh_objects(self):
        """A2L (yeniden) yüklenince: A2L adıyla kayıtlı satırları gerçek
        nesnelere çözümler; bulunamayanları hata ile bırakır."""
        summary = getattr(self.a2l_db, "summary", None) if self.a2l_db is not None else None
        measurements = {m.name: m for m in summary.measurements if m.address} if summary else {}
        characteristics = {c.name: c for c in summary.characteristics
                           if c.kind == "SCALAR" and c.address} if summary else {}
        for i, e in enumerate(self._entries):
            if e.kind == "manual":
                continue
            source = measurements if e.kind == "measurement" else characteristics
            obj = source.get(e.name)
            if obj is None:
                self._entries[i] = self._unresolved(e.name, e.kind)
                continue
            fresh = self._entry_from_a2l(e.kind, obj)
            same_target = (fresh.address == e.address and fresh.datatype == e.datatype)
            fresh.pending_text = e.pending_text if (not fresh.read_only and same_target) else None
            self._entries[i] = fresh
        self._rebuild_table()

    @staticmethod
    def _unresolved(name: str, kind: str) -> WatchEntry:
        return WatchEntry(name=name, kind=kind, address=0, datatype="",
                          read_only=True, resolved=False,
                          error="A2L'de bulunamadı")

    # ---- Kalıcılık ---------------------------------------------------------
    def set_storage_path(self, path: str | None):
        self._storage_path = path
        if not path:
            return
        if os.path.exists(path):
            self._load()
        else:
            self._save()

    def _serialize(self) -> dict:
        items = []
        for e in self._entries:
            if e.kind == "manual":
                items.append({
                    "name": e.name, "kind": "manual", "address": e.address,
                    "datatype": e.datatype, "unit": e.unit,
                    "address_extension": e.address_extension,
                    "byte_order": e.byte_order, "read_only": e.read_only,
                })
            else:
                items.append({"name": e.name, "kind": e.kind})
        return {"version": 1, "entries": items}

    def _save(self):
        if not self._storage_path:
            return
        if not atomic_write_json(self._storage_path, self._serialize()):
            self._set_status("Liste kaydedilemedi (dosya yazılamadı); ayrıntı openecu.log içinde.", False)

    def _load(self):
        data = load_json(self._storage_path, None, dict)
        items = data.get("entries") if data else None
        if not isinstance(items, list):
            if data is not None:
                self._set_status("Parametre listesi okunamadı (biçim geçersiz); dosya .corrupt olarak saklandı.", False)
            return
        entries: list[WatchEntry] = []
        seen = set()
        for it in items:
            try:
                name, kind = str(it["name"]), it["kind"]
                if name in seen:
                    continue
                if kind == "manual":
                    e = WatchEntry(
                        name=name, kind="manual", address=int(it["address"]),
                        datatype=str(it["datatype"]), unit=str(it.get("unit", "")),
                        address_extension=int(it.get("address_extension", 0)),
                        byte_order=it.get("byte_order"),
                        read_only=bool(it.get("read_only", False)),
                    )
                elif kind in ("measurement", "characteristic"):
                    e = self._unresolved(name, kind)
                else:
                    continue
            except (KeyError, TypeError, ValueError):
                continue
            seen.add(name)
            entries.append(e)
        self._entries = entries
        self._rebuild_table()
        if self.a2l_db is not None and getattr(self.a2l_db, "summary", None) is not None:
            self.refresh_objects()
