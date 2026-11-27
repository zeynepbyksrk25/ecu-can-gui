"""Modas Sport tarzı iç pencereler (MDI alt pencereleri).

* :class:`ValueWindow`  — tek değer: ``[ikon] [değer kutusu] [birim]``. Beyaz = ayarlanabilir kalibrasyon,
  gri = ölçüm (salt okunur). Yazılan değer önce "bekleyen" (sarı) olur, Enter ile ``write_requested`` yayılır.
* :class:`TableWindow`  — eğri / harita: eksen başlıkları + düzenlenebilir hücreler. ``MapDocument`` ile aynı
  "doküman" arayüzünü (``characteristic``, ``set_grid_from_ecu`` …) sunar; böylece MainWindow'daki mevcut,
  güvenli tablo okuma/yazma yolu (yedek + geri okuma doğrulaması + geri alma) aynen kullanılır.

Pencereler CCP/CAN işi YAPMAZ; yalnızca sinyal yayar ve sonucu MainWindow geri bildirir.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QSize, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMdiSubWindow, QMenu,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from app import theme
from app.ccp import codec as ccp_codec
from app.ccp import mapio
from app.value_text import parse_value_text

FORMATS = ("phys", "dec", "hex", "bin")
FORMAT_LABELS = {"phys": "Physical", "dec": "Decimal", "hex": "Hexadecimal", "bin": "Binary"}


def format_phys(value, digits: int = 3) -> str:
    """Fiziksel değeri okunur biçimde yazar (12000 → '12000', 0.5 → '0.5', 1e-5 → '1e-05')."""
    if value is None:
        return ""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(v):
        return str(v)
    if v != 0 and (abs(v) >= 1e9 or abs(v) < 1e-4):
        return f"{v:.6g}"
    text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return text if text not in ("", "-") else "0"


def format_reading(reading, fmt: str = "phys", byte_order: str | None = None) -> str:
    """``codec.Reading`` değerini seçilen biçimde (Physical / Decimal / Hex / Binary) metne çevirir."""
    if reading is None:
        return ""
    if fmt == "phys":
        return format_phys(reading.phys)
    raw = reading.raw_bytes
    if not raw:
        return format_phys(reading.phys)
    little = (byte_order or "").upper() in ("MSB_LAST", "LITTLE_ENDIAN")
    num = int.from_bytes(raw, "little" if little else "big")
    if fmt == "dec":
        try:
            return str(round(float(reading.raw)))
        except (TypeError, ValueError, OverflowError):
            return str(num)
    if fmt == "hex":
        return f"0x{num:0{len(raw) * 2}X}"
    if fmt == "bin":
        return f"{num:0{len(raw) * 8}b}"
    return format_phys(reading.phys)


def format_cell(characteristic, phys, fmt: str) -> str:
    """Tablo hücresi için sayı biçimi (Modas Ctrl+P/D/H/B). Yalnızca GÖSTERİM: doğrulama yapılmaz, yazma yolunda kullanılmaz.
    Ham değer hesaplanamazsa '—' döner (ör. A2L'de COMPU_METHOD / veri tipi yoksa)."""
    if phys is None:
        return ""
    if fmt == "phys":
        return format_phys(phys)
    try:
        raw = ccp_codec.physical_to_raw(getattr(characteristic, "compu_method", None), float(phys))
        data = ccp_codec.encode_value(characteristic.datatype, raw, getattr(characteristic, "byte_order", None))
    except Exception:  # noqa: BLE001 - gösterim hatası arayüzü bozmasın
        return "—"
    little = (getattr(characteristic, "byte_order", None) or "").upper() in ("MSB_LAST", "LITTLE_ENDIAN")
    num = int.from_bytes(data, "little" if little else "big")
    if fmt == "dec":
        try:
            return str(round(float(raw)))
        except (TypeError, ValueError, OverflowError):
            return str(num)
    if fmt == "hex":
        return f"0x{num:0{len(data) * 2}X}"
    if fmt == "bin":
        return f"{num:0{len(data) * 8}b}"
    return format_phys(phys)


def _square_icon(color: str) -> QIcon:
    pm = QPixmap(12, 12)
    pm.fill(QColor(color))
    return QIcon(pm)


def kind_of_object(obj) -> str:
    """'cal' (ayarlanabilir) | 'meas' (ölçüm). MeasurementInfo'da ``kind`` alanı yoktur."""
    return "cal" if hasattr(obj, "kind") and hasattr(obj, "read_only") else "meas"


class ModasSub(QMdiSubWindow):
    """Ortak iç pencere: başlık = etiket; kapatılınca ``closed`` yayılır (çalışma alanı listesinden düşer)."""
    closed = Signal(object)

    def __init__(self, label: str, color: str):
        super().__init__()
        self.label = label
        self.setWindowTitle(label)
        self.setWindowIcon(_square_icon(color))
        self.setAttribute(Qt.WA_DeleteOnClose, True)

    def closeEvent(self, event):  # noqa: N802
        self.closed.emit(self)
        super().closeEvent(event)

    def geometry_state(self) -> list:
        g = self.geometry()
        return [g.x(), g.y(), g.width(), g.height()]

    def refresh_style(self, widget: QWidget):
        widget.style().unpolish(widget)
        widget.style().polish(widget)


class _ValueEdit(QLineEdit):
    """Değer kutusu: değişmemişken M / N tuşları değeri artırır / azaltır (PDF §8), Esc bekleyeni atar."""
    nudge = Signal(int)
    cancelled = Signal()
    remove = Signal()

    def focusInEvent(self, event):  # noqa: N802
        super().focusInEvent(event)
        if not self.isReadOnly() and not self.isModified():
            QTimer.singleShot(0, self.selectAll)         # tıklayıp doğrudan yazınca eski değerin yerine geçer

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key_Delete and not self.isModified():
            self.remove.emit()                  # PDF §8: "Remove label from view"
            return
        if not self.isReadOnly() and not self.isModified():
            k = event.key()
            if k == Qt.Key_M:
                self.nudge.emit(+1)
                return
            if k == Qt.Key_N:
                self.nudge.emit(-1)
                return
        if event.key() == Qt.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


class ValueWindow(ModasSub):
    """Tek değer penceresi. ``obj`` MeasurementInfo ya da skaler CharacteristicInfo'dur."""
    write_requested = Signal(object, str)

    def __init__(self, obj, kind: str | None = None):
        kind = kind or kind_of_object(obj)
        super().__init__(obj.name, theme.OK if kind == "cal" else theme.SLATE)
        self.obj = obj
        self.kind = kind
        self.fmt = "phys"
        self.step = 0.1 if str(getattr(obj, "datatype", "")).upper().startswith("FLOAT") else 1.0
        self._allowed = True           # rol / bağlantı izni (kalibrasyon yazmak için)
        self._last_reading = None
        self._pending = False
        self._rp_view = False          # RP (referans) gösteriminde değer salt okunur ve referans değeri gösterir
        self._ref_value = None

        body = QWidget()
        body.setObjectName("modasWinBody")
        row = QHBoxLayout(body)
        row.setContentsMargins(4, 3, 4, 3)
        row.setSpacing(4)
        glyph = QLabel("≡" if kind == "cal" else "∿")
        glyph.setObjectName("modasWinLabel")
        row.addWidget(glyph)
        self.edit = _ValueEdit()
        self.edit.setObjectName("modasValue")
        self.edit.setProperty("kind", kind)
        self.edit.setMinimumWidth(90)
        self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.edit.textEdited.connect(self._on_text_edited)
        self.edit.returnPressed.connect(self._on_commit)
        self.edit.nudge.connect(self._on_nudge)
        self.edit.cancelled.connect(self.discard_pending)
        self.edit.remove.connect(self.close)
        row.addWidget(self.edit, 1)
        self.unit_label = QLabel(getattr(obj, "unit", "") or "")
        self.unit_label.setObjectName("modasWinUnit")
        row.addWidget(self.unit_label)
        self.setWidget(body)
        self.resize(max(230, 150 + 8 * len(obj.name)), 54)
        self._apply_editable()
        self.edit.setToolTip(self._tooltip())

    # ---- durum ---------------------------------------------------------------------
    @property
    def is_calibration(self) -> bool:
        return self.kind == "cal"

    @property
    def has_pending(self) -> bool:
        return self._pending

    def set_change(self, arrow: str, delta: str, summary: str):
        """Değişiklik takibi göstergesi (ok + fark): son yazım yönü ve miktarı birim etiketinin yanında, ayrıntı ipucunda."""
        self._change_text = f"  {arrow} {delta}".rstrip() if arrow else ""
        self._change_summary = summary
        self.unit_label.setText(((getattr(self.obj, "unit", "") or "") + self._change_text).strip())
        self.edit.setToolTip(self._tooltip())

    def _tooltip(self) -> str:
        o = self.obj
        addr = f"0x{o.address:X}" if getattr(o, "address", None) else "-"
        kind = "Kalibrasyon (ayarlanabilir)" if self.is_calibration else "Ölçüm (salt okunur)"
        extra = getattr(self, "_change_summary", "")
        return (f"{o.name}\n{getattr(o, 'description', '') or ''}\n{kind} · {getattr(o, 'datatype', '')} · adres {addr}\n"
                "M / N: değeri artır / azalt · Enter: yaz · Esc: vazgeç" + (f"\n\n{extra}" if extra else ""))

    def _editable(self) -> bool:
        return (self.is_calibration and self._allowed and self.fmt == "phys" and not self._rp_view
                and not getattr(self.obj, "read_only", False))

    def _apply_editable(self):
        self.edit.setReadOnly(not self._editable())
        self.edit.setProperty("kind", "cal" if self._editable() else ("cal" if self.is_calibration else "meas"))
        self.refresh_style(self.edit)

    def set_allowed(self, allowed: bool):
        """Kalibrasyon yazma izni (rol + bağlantı). İzin yoksa değer kutusu salt okunur olur."""
        self._allowed = bool(allowed)
        if not self._allowed:
            self.discard_pending()
        self._apply_editable()

    def set_format(self, fmt: str):
        if fmt not in FORMATS:
            return
        self.fmt = fmt
        self.discard_pending()
        self._apply_editable()
        self._render()

    # ---- canlı değer ---------------------------------------------------------------
    def set_reading(self, reading):
        self._last_reading = reading
        if self._pending:
            return                      # kullanıcı yazarken canlı değer üzerine yazmaz
        self.edit.setProperty("bad", False)
        self.refresh_style(self.edit)
        self._render()

    def set_error(self, message: str):
        self._last_reading = None
        if self._pending or self._rp_view:
            return
        self.edit.setText("—")
        self.edit.setToolTip(f"{self._tooltip()}\n\n⚠ {message}")
        self.edit.setProperty("bad", True)
        self.refresh_style(self.edit)

    def wp_value(self):
        """WP (canlı/ECU) fiziksel değeri; henüz okunmadıysa None."""
        r = self._last_reading
        try:
            return float(r.phys) if r is not None else None
        except (TypeError, ValueError):
            return None

    def set_reference_view(self, ref, rp: bool):
        """RP gösterimi: referans değeri (yoksa '—') salt okunur gösterilir; WP'ye dönünce canlı değer."""
        self._rp_view = bool(rp)
        self._ref_value = ref
        self.discard_pending()
        self._apply_editable()
        self._render()

    def _render(self):
        if self._rp_view:
            self.edit.setText(format_phys(self._ref_value) if self._ref_value is not None else "—")
            self.edit.setCursorPosition(0)
            return
        if self._last_reading is None:
            return
        text = format_reading(self._last_reading, self.fmt, getattr(self.obj, "byte_order", None))
        if text != self.edit.text():                     # aynı değerde yeniden yazma: seçimi / imleci bozma
            self.edit.setText(text)
            self.edit.setCursorPosition(0)
        self.edit.setModified(False)
        self.edit.setToolTip(self._tooltip())

    # ---- düzenleme / yazma ---------------------------------------------------------
    def _set_pending(self, on: bool):
        self._pending = on
        self.edit.setProperty("pending", on)
        self.refresh_style(self.edit)

    def _on_text_edited(self, _text: str):
        if not self.edit.isReadOnly():
            self._set_pending(True)

    def discard_pending(self):
        if self._pending:
            self._set_pending(False)
        self.edit.setModified(False)
        self._render()

    def _on_commit(self):
        if not self._pending or self.edit.isReadOnly():
            return
        self.write_requested.emit(self, self.edit.text())

    def _on_nudge(self, direction: int):
        if self._last_reading is None or self.edit.isReadOnly():
            return
        try:
            value = float(self._last_reading.phys) + direction * self.step
        except (TypeError, ValueError):
            return
        self.write_requested.emit(self, format_phys(value, 6))

    def set_write_result(self, ok: bool, message: str = ""):
        """MainWindow yazma sonucunu bildirir: başarıda bekleyen biter (canlı değer akar), hatada kırmızı kalır."""
        self._set_pending(False)
        self.edit.setModified(False)
        if ok:
            self.edit.setProperty("bad", False)
            self.edit.setToolTip(f"{self._tooltip()}\n\n✔ {message}" if message else self._tooltip())
        else:
            self.edit.setProperty("bad", True)
            self.edit.setToolTip(f"{self._tooltip()}\n\n⚠ {message}")
            self._render()
        self.refresh_style(self.edit)

    def state(self) -> dict:
        return {"kind": "value", "name": self.label, "geom": self.geometry_state(), "fmt": self.fmt}


class TableWindow(ModasSub):
    """Eğri / harita penceresi (``MapDocument`` ile aynı doküman arayüzü)."""
    write_requested = Signal(object)
    read_requested = Signal(object)

    def __init__(self, characteristic):
        super().__init__(characteristic.name, theme.ACCENT)
        self.characteristic = characteristic
        self.rows, self.cols = mapio.grid_shape(characteristic)
        self.writable_layout, self.layout_note = mapio.layout_support(characteristic)
        self._allowed = True
        self._original: list | None = None
        self._updating = False
        self._rp_view = False
        self._wp_backup: list | None = None     # RP gösteriminde WP tablosunun saklandığı yer
        self.fmt = "phys"                       # Physical | Decimal | Hexadecimal | Binary (Modas Ctrl+P/D/H/B)
        self._phys_cache: list | None = None    # Physical dışı biçimde gerçek (fiziksel) değerler; hücre metni yalnızca gösterimdir

        body = QWidget()
        body.setObjectName("modasWinBody")
        v = QVBoxLayout(body)
        v.setContentsMargins(4, 3, 4, 4)
        v.setSpacing(3)
        self.info = QLabel(self._info_text())
        self.info.setObjectName("modasTableInfo")
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        self.table = QTableWidget(self.rows, self.cols)
        self.table.setObjectName("modasTable")
        self.table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.table.horizontalHeader().setDefaultSectionSize(62)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self._build_headers()
        self._set_corner_label()
        for r in range(self.rows):
            for c in range(self.cols):
                it = QTableWidgetItem("")
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        self.table.itemChanged.connect(self._on_item_changed)       # hücreler tamamlandıktan SONRA bağlanır
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._on_context_menu)
        v.addWidget(self.table, 1)
        self.setWidget(body)
        self.resize(min(720, 90 + 64 * self.cols), min(460, 96 + 22 * self.rows))
        self._apply_editable()

    # ---- başlıklar / bilgi ---------------------------------------------------------
    def _axis_text(self, ax, name: str) -> str:
        return f"{name}: {ax.attribute or '-'} [{ax.unit or '-'}]"

    def _info_text(self) -> str:
        c = self.characteristic
        parts = [f"<b>Z</b> {c.name} [{c.unit or '-'}]"]
        axes = c.axes or []
        if len(axes) >= 1:
            parts.append(self._axis_text(axes[0], "X"))
        if len(axes) >= 2:
            parts.append(self._axis_text(axes[1], "Y"))
        text = "  &nbsp;·&nbsp;  ".join(parts)
        if not self.writable_layout:
            text += f"<br><span style='color:{theme.DANGER}'>⚠ {self.layout_note} Yazma kapalı.</span>"
        return text

    def _build_headers(self):
        axes = self.characteristic.axes or []

        def labels(ax, n):
            vals = ax.values if (ax is not None and ax.values and len(ax.values) == n) else None
            return [format_phys(vals[i]) if vals else str(i) for i in range(n)]

        x_ax = axes[0] if len(axes) >= 1 else None
        y_ax = axes[1] if len(axes) >= 2 else None
        self.table.setHorizontalHeaderLabels(labels(x_ax, self.cols))
        self.table.setVerticalHeaderLabels(labels(y_ax, self.rows) if y_ax is not None else ["Z"] * self.rows)

    def _set_corner_label(self):
        """Modas Sport: sol üst köşe hücresi 'Y\\X' (satır ekseni \\ sütun ekseni); eğride 'X'."""
        corner = self.table.findChild(QAbstractButton)
        if corner is not None:
            corner.setText("Y\\X" if len(self.characteristic.axes or []) >= 2 else "X")

    # ---- yetki ---------------------------------------------------------------------
    def set_allowed(self, allowed: bool):
        self._allowed = bool(allowed)
        self._apply_editable()

    def _apply_editable(self):
        ok = self.writable_layout and self._allowed and not self._rp_view and self.fmt == "phys"
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed
            if ok else QAbstractItemView.NoEditTriggers)

    def is_cell_editable(self) -> bool:
        return self.writable_layout and self._allowed and not self._rp_view and self.fmt == "phys"

    # ---- doküman arayüzü (mainwin/calibration.py bunu çağırır) ----------------------
    def _cell_value(self, r: int, c: int):
        if self.fmt != "phys" and self._phys_cache is not None:          # gösterim biçimi ham: gerçek değer önbellekte
            try:
                return self._phys_cache[r][c]
            except IndexError:
                return None
        it = self.table.item(r, c)
        text = (it.text() if it else "").strip()
        if not text:
            return None
        try:
            return parse_value_text(text)
        except ValueError:
            return None

    def _read_table_grid(self) -> list:
        return [[self._cell_value(r, c) for c in range(self.cols)] for r in range(self.rows)]

    def current_grid(self) -> list:
        """WP tablosu (RP gösterimindeyken bile WP değerleri; yazma hiçbir zaman referansı yazmaz)."""
        if self._rp_view and self._wp_backup is not None:
            return [list(r) for r in self._wp_backup]
        return self._read_table_grid()

    def wp_grid(self):
        return self.current_grid()

    def set_reference_view(self, ref, rp: bool):
        """RP gösterimi: referans tablosu salt okunur gösterilir; WP'ye dönünce saklanan WP tablosu geri gelir."""
        if rp:
            if not self._rp_view:
                self._wp_backup = self._read_table_grid()
                self._rp_view = True
            blank = [[None] * self.cols for _ in range(self.rows)]
            self._fill(ref if ref is not None else blank)
        elif self._rp_view:
            grid, self._wp_backup, self._rp_view = self._wp_backup, None, False
            self._fill(grid or [[None] * self.cols for _ in range(self.rows)])
        self._apply_editable()

    def is_writable(self) -> bool:
        return self.writable_layout and all(v is not None for row in self.current_grid() for v in row)

    def is_modified(self) -> bool:
        if self._original is None:
            return False
        grid = self.current_grid()
        for r in range(self.rows):
            for c in range(self.cols):
                a, b = self._original[r][c], grid[r][c]
                if a is None or b is None or abs(a - b) > 1e-9:
                    return True
        return False

    def set_grid_from_ecu(self, grid: list):
        self._original = [list(row) for row in grid]
        if self._rp_view:                       # RP gösteriminde tablo referansı gösterir; yeni WP arka planda saklanır
            self._wp_backup = [list(row) for row in grid]
            return
        self._fill(grid)
        self.info.setToolTip("ECU'dan okundu.")

    def load_grid_as_edit(self, grid: list):
        """Verilen tabloyu hücrelere BEKLEYEN (sarı) değer olarak yükler (RP → WP için); yazmayı çağıran yapar."""
        self._fill(grid)

    def set_error(self, message: str):
        self.info.setText(self._info_text() + f"<br><span style='color:{theme.DANGER}'>⚠ {message}</span>")

    def set_write_result(self, ok: bool, message: str):
        self._original = self.current_grid() if ok else self._original
        color = theme.OK if ok else theme.DANGER
        self.info.setText(self._info_text() + f"<br><span style='color:{color}'>{'✔' if ok else '⚠'} {message}</span>")
        self._refresh_pending()

    def _fill(self, grid: list):
        full = [[grid[r][c] if r < len(grid) and c < len(grid[r]) else None for c in range(self.cols)]
                for r in range(self.rows)]
        if self.fmt != "phys":
            self._phys_cache = full
        self._render(full)
        self._refresh_pending()

    def _render(self, grid: list):
        """Hücre metinlerini geçerli biçimde yazar (gerçek değerlere dokunmaz)."""
        self._updating = True
        try:
            for r in range(self.rows):
                for c in range(self.cols):
                    self.table.item(r, c).setText(format_cell(self.characteristic, grid[r][c], self.fmt))
        finally:
            self._updating = False

    def set_format(self, fmt: str):
        """Sayı biçimi (Ctrl+P/D/H/B). Physical dışında hücreler salt-okunurdur; gerçek değerler fiziksel olarak saklanır."""
        if fmt not in FORMATS or fmt == self.fmt:
            return
        grid = self._read_table_grid()                 # geçerli (bekleyen düzenleme dahil) fiziksel değerler
        self.fmt = fmt
        self._phys_cache = grid if fmt != "phys" else None
        self._render(grid)
        self._apply_editable()
        self._refresh_pending()

    def _refresh_pending(self):
        if self._rp_view:
            return
        self._updating = True
        try:
            for r in range(self.rows):
                for c in range(self.cols):
                    it = self.table.item(r, c)
                    if it is None:
                        continue
                    changed = (self._original is not None and
                               (self._cell_value(r, c) is None or
                                abs((self._original[r][c] or 0.0) - (self._cell_value(r, c) or 0.0)) > 1e-9))
                    it.setBackground(QColor(theme.PENDING_BG) if changed else QColor(theme.MODAS_CAL_BG))
        finally:
            self._updating = False

    # ---- düzenleme -----------------------------------------------------------------
    def _on_item_changed(self, item: QTableWidgetItem):
        if self._updating or self._rp_view or self.fmt != "phys":
            return                                  # ham biçimde hücre metni gösterimdir: düzenleme / yazma tetiklenmez
        self._refresh_pending()
        if self.is_writable() and self.is_modified():
            self.write_requested.emit(self)       # Enter ile onaylanan hücre: RAM'e yaz (yedek + doğrulama MainWindow'da)

    def _selected(self) -> list:
        return [(i.row(), i.column()) for i in self.table.selectedIndexes()]

    def apply_to_selection(self, op: str, operand: float | None = None) -> int:
        """Seçili hücrelere işlem uygular (Modas: M/N artır-azalt, * / + çarp-böl-ekle, = ata). Değişen sayıyı döner.
        Geçersiz / sonsuz sonuç ve boş hücreler atlanır; sonunda tek seferde yazılır."""
        if not self.is_cell_editable():
            return 0
        cells = self._selected()
        if not cells:
            return 0
        if operand is None:
            operand = 1.0
        changed = 0
        self._updating = True
        try:
            for r, c in cells:
                cur = self._cell_value(r, c)
                try:
                    if op == "set":
                        new = operand
                    elif cur is None:
                        continue
                    elif op == "inc":
                        new = cur + operand
                    elif op == "dec":
                        new = cur - operand
                    elif op == "mul":
                        new = cur * operand
                    elif op == "div":
                        new = cur / operand
                    elif op == "add":
                        new = cur + operand
                    else:
                        continue
                except ZeroDivisionError:
                    continue
                if not math.isfinite(new):
                    continue
                self.table.item(r, c).setText(format_phys(new, 6))
                changed += 1
        finally:
            self._updating = False
        self._refresh_pending()
        if changed and self.is_writable() and self.is_modified():
            self.write_requested.emit(self)
        return changed

    def restore_selection(self) -> int:
        """Modas Ctrl+R: seçili hücreleri ECU'dan okunan (son yazılan) değerine döndürür. Değişen hücre sayısını döner."""
        if not self.is_cell_editable() or self._original is None:
            return 0
        changed = 0
        self._updating = True
        try:
            for r, c in self._selected():
                orig = self._original[r][c] if r < len(self._original) and c < len(self._original[r]) else None
                if orig is None:
                    continue
                cur = self._cell_value(r, c)
                if cur is None or abs(cur - orig) > 1e-9:
                    self.table.item(r, c).setText(format_phys(orig, 6))
                    changed += 1
        finally:
            self._updating = False
        self._refresh_pending()
        if changed and self.is_writable() and self.is_modified():
            self.write_requested.emit(self)
        return changed

    def _on_context_menu(self, pos):
        menu = QMenu(self.table)
        editable = self.is_cell_editable()
        act_restore = menu.addAction("Seçili değerleri geri yükle  (Ctrl+R)")
        act_restore.setEnabled(editable and self._original is not None and bool(self._selected()))
        act_backup = menu.addAction("Yedekten Yükle…")
        act_backup.setEnabled(editable)
        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen is act_restore:
            self.restore_selection()
        elif chosen is act_backup:
            self.restore_from_backup()

    def restore_from_backup(self) -> bool:
        """Tablonun, ECU'ya yazılmadan önce otomatik alınan yedeklerinden birini hücrelere DÜZENLEME olarak yükler.
        ECU'ya yazılmaz: kullanıcı onaylayınca (Enter / Write) normal güvenli yazma yolu çalışır."""
        from PySide6.QtWidgets import QMessageBox
        from app.ccp import table_backup
        from app.paths import data_path
        ch = self.characteristic
        backups = table_backup.list_backups(data_path("tablo_yedekleri"), ch)
        if not backups:
            QMessageBox.information(self.window(), "Yedek yok", f"{ch.name} için kayıtlı bir yedek yok. Yedekler, tablo "
                                                                 "ECU'ya yazılmadan hemen önce otomatik alınır.")
            return False
        label, ok = QInputDialog.getItem(self.window(), "Yedekten yükle", f"{ch.name}: yedek seçin (en yenisi üstte)",
                                         [b.label for b in backups], 0, False)
        if not ok:
            return False
        chosen = next(b for b in backups if b.label == label)
        try:
            grid = table_backup.load(chosen.path, ch, mapio.grid_shape(ch))
        except ValueError as exc:
            QMessageBox.warning(self.window(), "Yedek yüklenemedi", str(exc))
            return False
        self.load_grid_as_edit(grid)
        # set_write_result KULLANILMAZ: başarıda tabloyu "ECU ile aynı" sayıp değişiklik işaretini silerdi.
        self.info.setText(self._info_text() + f"<br><span style='color:{theme.WARN_INK}'>Yedek yüklendi "
                          f"({label.split('  ')[0]}); ECU'ya HENÜZ yazılmadı. Yazmak için Enter / Write data to ECU.</span>")
        return True

    def ask_operand(self, title: str) -> float | None:
        value, ok = QInputDialog.getDouble(self, title, "Değer:", 1.0, -1e12, 1e12, 6)
        return value if ok else None

    def keyPressEvent(self, event):  # noqa: N802
        """PDF §8 tablo kısayolları: M / N artır-azalt, * çarp, / böl, + ekle, = ata, Ctrl+R geri yükle, Delete pencereyi kapatır."""
        key = event.key()
        table_focus = self.table.hasFocus() and self.table.state() != QAbstractItemView.EditingState
        if table_focus:
            if key == Qt.Key_R and event.modifiers() & Qt.ControlModifier:
                self.restore_selection()        # PDF §8: "Restore selected values" (Ctrl+R)
                return
            if key == Qt.Key_Delete:
                self.close()                    # PDF §8: "Remove label from view"
                return
            if key == Qt.Key_M:
                self.apply_to_selection("inc")
                return
            if key == Qt.Key_N:
                self.apply_to_selection("dec")
                return
            ops = {Qt.Key_Asterisk: ("mul", "Çarp"), Qt.Key_Slash: ("div", "Böl"),
                   Qt.Key_Plus: ("add", "Ekle"), Qt.Key_Equal: ("set", "Ata")}
            if key in ops and self.is_cell_editable() and self._selected():
                op, title = ops[key]
                operand = self.ask_operand(title)
                if operand is not None:
                    self.apply_to_selection(op, operand)
                return
        super().keyPressEvent(event)

    def sizeHint(self):  # noqa: N802
        return QSize(self.width(), self.height())

    def state(self) -> dict:
        return {"kind": "table", "name": self.label, "geom": self.geometry_state(), "fmt": self.fmt}
