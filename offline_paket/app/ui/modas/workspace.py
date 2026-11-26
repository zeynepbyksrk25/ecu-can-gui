"""Modas çalışma alanı: mavi MDI zemini + altta worksheet sekmeleri + sağda Variable list (F2) + altta Log (F3).

Çalışma alanı ECU ile KONUŞMAZ. Ölçüm turu (``read_requested``), değer/tablo yazma ve tablo okuma istekleri sinyal olarak
MainWindow'a gider (bkz. ``mainwin/modas.py``); sonuç pencerelere ``set_reading`` / ``set_write_result`` ile döner.

Worksheet düzeni (hangi etiket, hangi konum/boyut) ``modas_worksheets.json`` dosyasında saklanır; A2L sonradan
yüklenirse bekleyen pencereler o zaman kurulur (etiket kaybolmaz).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from PySide6.QtCore import QPoint, QTimer, Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QInputDialog, QMdiArea, QMenu, QMessageBox, QSplitter, QTabBar, QToolButton,
    QVBoxLayout, QWidget,
)

from app import theme
from app.persist import atomic_write_json, load_json
from app.ui.modas.pages import RP, WP
from app.ui.modas.style import MODAS_QSS
from app.ui.modas.variable_list import MIME, LogPanel, VariableListPanel, classify
from app.ui.modas.windows import ModasSub, TableWindow, ValueWindow

log = logging.getLogger(__name__)

STATE_VERSION = 1
MEASURE_INTERVAL_MS = 250          # watch_tab.POLL_INTERVAL_MS ile aynı: değerler arka plan CCP önbelleğinden gelir
SAVE_DELAY_MS = 500
DEFAULT_SHEET = "Sheet1"


class ModasSheetStore:
    """``{"version", "current", "sheets": [{"name", "windows": [..]}]}`` — JSON; hatada sessizce boş döner."""

    def __init__(self, path: str | None):
        self.path = path

    def load(self) -> dict | None:
        if not self.path:
            return None
        data = load_json(self.path, None, dict)
        if not data or not isinstance(data.get("sheets"), list):
            return None
        sheets = []
        for s in data["sheets"]:
            if isinstance(s, dict) and isinstance(s.get("name"), str):
                wins = [w for w in (s.get("windows") or []) if isinstance(w, dict) and isinstance(w.get("name"), str)]
                sheets.append({"name": s["name"], "windows": wins})
        if not sheets:
            return None
        cur = data.get("current", 0)
        return {"version": STATE_VERSION, "current": cur if isinstance(cur, int) else 0, "sheets": sheets}

    def save(self, state: dict) -> bool:
        return bool(self.path) and atomic_write_json(self.path, state)


class _Mdi(QMdiArea):
    """Mavi zemin; Variable list'ten sürüklenen etiketleri kabul eder."""
    labels_dropped = Signal(list, QPoint)

    def __init__(self):
        super().__init__()
        self.setObjectName("modasMdi")
        self.setBackground(QBrush(QColor(theme.MODAS_WORKSPACE)))      # QSS QMdiArea arka planını boyamaz
        self.setAcceptDrops(True)
        self.setActivationOrder(QMdiArea.ActivationHistoryOrder)

    def dragEnterEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(MIME):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):  # noqa: N802
        if event.mimeData().hasFormat(MIME):
            names = bytes(event.mimeData().data(MIME)).decode("utf-8", "replace").split("\n")
            self.labels_dropped.emit([n for n in names if n], event.position().toPoint())
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


@dataclass
class _Sheet:
    name: str
    mdi: _Mdi
    windows: list = field(default_factory=list)       # canlı ModasSub'lar
    pending: list = field(default_factory=list)       # henüz kurulamayan (A2L yok / etiket bulunamadı) pencere tanımları


class ModasWorkspace(QWidget):
    read_requested = Signal()                 # ölçüm turu: değer pencerelerini oku
    value_write_requested = Signal(object, str)
    table_read_requested = Signal(list)
    table_write_requested = Signal(object)
    measuring_changed = Signal(bool)
    page_changed = Signal(str)
    layout_changed = Signal()                 # pencere eklendi / silindi / sayfa değişti (Diff yeniden hesaplanır)

    def __init__(self, store: ModasSheetStore | None = None):
        super().__init__()
        self.setObjectName("modasWorkspace")
        self.setStyleSheet(MODAS_QSS)
        self.store = store or ModasSheetStore(None)
        self._summary = None
        self._by_name: dict = {}
        self._sheets: list[_Sheet] = []
        self._online = False
        self._allowed = True
        self._page = WP
        self._reference: dict = {}
        self._cascade = 0

        # ---- orta: MDI yığını + Variable list
        self.stack_host = QWidget()
        self.stack_layout = QVBoxLayout(self.stack_host)
        self.stack_layout.setContentsMargins(0, 0, 0, 0)
        self.var_panel = VariableListPanel()
        self.var_panel.add_requested.connect(self.add_label)
        self.var_panel.info_requested.connect(self.show_info)
        self.splitter = QSplitter(Qt.Horizontal)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.addWidget(self.stack_host)
        self.splitter.addWidget(self.var_panel)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 0)
        self.splitter.setSizes([900, 340])

        # ---- worksheet sekmeleri
        self.sheet_bar = QFrame()
        self.sheet_bar.setObjectName("modasSheetBar")
        bar = QHBoxLayout(self.sheet_bar)
        bar.setContentsMargins(4, 0, 4, 0)
        bar.setSpacing(2)
        self.prev_btn = QToolButton()
        self.prev_btn.setText("◀")
        self.next_btn = QToolButton()
        self.next_btn.setText("▶")
        for b in (self.prev_btn, self.next_btn):
            b.setAutoRaise(True)
            b.setFixedWidth(18)
            bar.addWidget(b)
        self.tabs = QTabBar()
        self.tabs.setObjectName("modasSheetTabs")
        self.tabs.setShape(QTabBar.RoundedSouth)
        self.tabs.setDrawBase(False)
        self.tabs.setMovable(False)
        self.tabs.setExpanding(False)
        self.tabs.setUsesScrollButtons(True)
        self.tabs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabs.customContextMenuRequested.connect(self._on_tab_menu)
        self.tabs.tabBarDoubleClicked.connect(self.rename_sheet)
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.prev_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(max(0, self.tabs.currentIndex() - 1)))
        self.next_btn.clicked.connect(lambda: self.tabs.setCurrentIndex(min(self.tabs.count() - 1, self.tabs.currentIndex() + 1)))
        bar.addWidget(self.tabs, 1)

        self.log_panel = LogPanel()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self.splitter, 1)
        root.addWidget(self.sheet_bar)
        root.addWidget(self.log_panel)

        # ---- ölçüm zamanlayıcısı + gecikmeli kayıt
        self._timer = QTimer(self)
        self._timer.setInterval(MEASURE_INTERVAL_MS)
        self._timer.timeout.connect(self.read_requested.emit)
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(SAVE_DELAY_MS)
        self._save_timer.timeout.connect(self.save)

        self._load()

    # ======================================================================
    # Worksheet'ler
    # ======================================================================
    @property
    def sheets(self) -> list:
        return self._sheets

    def sheet_names(self) -> list:
        return [s.name for s in self._sheets]

    def current_sheet(self) -> _Sheet:
        return self._sheets[max(0, self.tabs.currentIndex())]

    def _unique_name(self, base: str = "Sheet") -> str:
        names = set(self.sheet_names())
        i = 1
        while f"{base}{i}" in names:
            i += 1
        return f"{base}{i}"

    def _make_sheet(self, name: str, select: bool = True) -> _Sheet:
        mdi = _Mdi()
        mdi.labels_dropped.connect(self._on_dropped)
        sheet = _Sheet(name, mdi)
        self._sheets.append(sheet)
        self.stack_layout.addWidget(mdi)
        mdi.setVisible(False)
        self.tabs.blockSignals(True)
        idx = self.tabs.addTab(name)
        self.tabs.blockSignals(False)
        if select:
            self.tabs.setCurrentIndex(idx)
            self._on_tab_changed(idx)
        return sheet

    def new_sheet(self, name: str | None = None) -> _Sheet:
        sheet = self._make_sheet(name or self._unique_name())
        self._changed()
        return sheet

    def rename_sheet(self, index: int, name: str | None = None) -> bool:
        if not 0 <= index < len(self._sheets):
            return False
        if name is None:
            name, ok = QInputDialog.getText(self, "Worksheet", "Worksheet adı:", text=self._sheets[index].name)
            if not ok:
                return False
        name = (name or "").strip()
        if not name or any(s.name == name for i, s in enumerate(self._sheets) if i != index):
            return False
        self._sheets[index].name = name
        self.tabs.setTabText(index, name)
        self._changed()
        return True

    def delete_sheet(self, index: int) -> bool:
        """Son worksheet silinemez (Modas gibi en az bir sayfa kalır)."""
        if len(self._sheets) <= 1 or not 0 <= index < len(self._sheets):
            return False
        sheet = self._sheets.pop(index)
        for w in list(sheet.windows):
            w.closed.disconnect()
        self.stack_layout.removeWidget(sheet.mdi)
        sheet.mdi.deleteLater()
        self.tabs.blockSignals(True)
        self.tabs.removeTab(index)
        self.tabs.blockSignals(False)
        self._on_tab_changed(self.tabs.currentIndex())
        self._changed()
        return True

    def _on_tab_changed(self, index: int):
        for i, s in enumerate(self._sheets):
            s.mdi.setVisible(i == index)
        self._save_timer.start()

    def _on_tab_menu(self, pos):
        idx = self.tabs.tabAt(pos)
        menu = QMenu(self)
        act_new = menu.addAction("New worksheet")
        act_ren = menu.addAction("Rename…")
        act_del = menu.addAction("Delete")
        act_ren.setEnabled(idx >= 0)
        act_del.setEnabled(idx >= 0 and len(self._sheets) > 1)
        chosen = menu.exec(self.tabs.mapToGlobal(pos))
        if chosen is act_new:
            self.new_sheet()
        elif chosen is act_ren:
            self.rename_sheet(idx)
        elif chosen is act_del:
            self.delete_sheet(idx)

    # ======================================================================
    # Etiket / pencere ekleme
    # ======================================================================
    def set_summary(self, summary):
        """A2L özetini bildirir (None = A2L yok). Mevcut pencereler yeni nesnelere yeniden bağlanır."""
        states = {id(s): self._sheet_specs(s) for s in self._sheets}
        for s in self._sheets:
            for w in list(s.windows):
                w.closed.disconnect()
                w.close()
            s.windows.clear()
            s.pending = states[id(s)]
        self._summary = summary
        self._by_name = {}
        if summary is not None:
            for c in summary.characteristics:
                self._by_name[c.name] = c
            for m in summary.measurements:          # ad çakışırsa ölçüm önceliklidir (readable_by_name gibi)
                self._by_name[m.name] = m
        self.var_panel.set_summary(summary)
        for s in self._sheets:
            self._materialize(s)
        self._changed(save=False)

    def object_by_name(self, name: str):
        return self._by_name.get(name)

    def _materialize(self, sheet: _Sheet):
        left = []
        for spec in sheet.pending:
            obj = self._by_name.get(spec.get("name", ""))
            if obj is None:
                left.append(spec)
                continue
            if self._open_window(sheet, obj, geom=spec.get("geom"), fmt=spec.get("fmt")) is None:
                left.append(spec)
        sheet.pending = left

    def _sheet_specs(self, sheet: _Sheet) -> list:
        return [w.state() for w in sheet.windows] + list(sheet.pending)

    def find_window(self, name: str, sheet: _Sheet | None = None):
        for w in (sheet or self.current_sheet()).windows:
            if w.label == name:
                return w
        return None

    def add_label(self, obj_or_name, pos: QPoint | None = None):
        """Etiketi AKTİF worksheet'e ekler (zaten açıksa o pencereyi öne getirir). Eklenen pencereyi döner."""
        obj = self._by_name.get(obj_or_name) if isinstance(obj_or_name, str) else obj_or_name
        if obj is None:
            self.log_panel.add_text(f"Label bulunamadı: {obj_or_name}")
            return None
        sheet = self.current_sheet()
        existing = self.find_window(obj.name, sheet)
        if existing is not None:
            sheet.mdi.setActiveSubWindow(existing)
            return existing
        win = self._open_window(sheet, obj, pos=pos)
        if win is not None:
            self._changed()
            if self._online:
                if isinstance(win, TableWindow):
                    self.table_read_requested.emit([win])
                else:
                    self._warmup()
        return win

    def _on_dropped(self, names: list, pos: QPoint):
        p = QPoint(pos)
        for n in names:
            self.add_label(n, p)
            p += QPoint(24, 24)

    def _open_window(self, sheet: _Sheet, obj, pos: QPoint | None = None, geom=None, fmt=None):
        kind = classify(obj)
        if kind == "text":
            self.log_panel.add_text(f"{obj.name}: metin (ASCII) alanları bu sürümde desteklenmiyor.")
            return None
        if kind in ("curve", "map"):
            win: ModasSub = TableWindow(obj)
            win.write_requested.connect(self.table_write_requested.emit)
            win.read_requested.connect(lambda w: self.table_read_requested.emit([w]))
            win.set_allowed(self._allowed)
            if fmt:
                win.set_format(fmt)
        else:
            win = ValueWindow(obj, "cal" if kind == "value" else "meas")
            win.write_requested.connect(self.value_write_requested.emit)
            win.set_allowed(self._allowed and self._online)
            if fmt:
                win.set_format(fmt)
        win.closed.connect(lambda w, s=sheet: self._on_closed(s, w))
        sheet.mdi.addSubWindow(win)
        win.show()
        if isinstance(geom, (list, tuple)) and len(geom) == 4 and all(isinstance(v, (int, float)) for v in geom):
            win.setGeometry(*(int(v) for v in geom))
        else:
            win.move(pos if pos is not None else self._next_pos())
        sheet.windows.append(win)
        self._apply_page_to(win)
        return win

    def _next_pos(self) -> QPoint:
        self._cascade = (self._cascade + 1) % 12
        return QPoint(20 + 26 * self._cascade, 20 + 26 * self._cascade)

    def _on_closed(self, sheet: _Sheet, win):
        if win in sheet.windows:
            sheet.windows.remove(win)
        self._changed()

    # ======================================================================
    # Sorgular
    # ======================================================================
    def windows(self, all_sheets: bool = True) -> list:
        sheets = self._sheets if all_sheets else [self.current_sheet()]
        return [w for s in sheets for w in s.windows]

    def value_windows(self, all_sheets: bool = True) -> list:
        return [w for w in self.windows(all_sheets) if isinstance(w, ValueWindow)]

    def table_windows(self, all_sheets: bool = True) -> list:
        return [w for w in self.windows(all_sheets) if isinstance(w, TableWindow)]

    def active_window(self):
        sub = self.current_sheet().mdi.activeSubWindow()
        return sub if isinstance(sub, ModasSub) else None

    def has_labels(self) -> bool:
        return bool(self.windows())

    # ======================================================================
    # Pencere düzeni
    # ======================================================================
    def tile(self):
        self.current_sheet().mdi.tileSubWindows()
        self._changed()

    def cascade(self):
        self.current_sheet().mdi.cascadeSubWindows()
        self._changed()

    def close_all(self):
        for w in list(self.current_sheet().windows):
            w.close()

    def remove_selected(self) -> bool:
        w = self.active_window()
        if w is None:
            return False
        w.close()
        return True

    def toggle_variable_list(self, show: bool | None = None) -> bool:
        show = self.var_panel.isHidden() if show is None else show
        self.var_panel.setVisible(show)
        return show

    def toggle_log(self, show: bool | None = None) -> bool:
        show = self.log_panel.isHidden() if show is None else show
        self.log_panel.setVisible(show)
        return show

    def set_format(self, fmt: str) -> int:
        """Seçili değer / tablo penceresine (yoksa aktif worksheet'teki tüm değer ve tablo pencerelerine) biçim uygular."""
        w = self.active_window()
        targets = [w] if isinstance(w, (ValueWindow, TableWindow)) else self.windows(all_sheets=False)
        for t in targets:
            t.set_format(fmt)
        self._changed()
        return len(targets)

    def show_info(self, obj):
        """Variable Information (Ctrl+I): etiketin A2L özeti."""
        lines = [f"Name: {obj.name}", f"Type: {classify(obj)}", f"Description: {getattr(obj, 'description', '') or '-'}",
                 f"Datatype: {getattr(obj, 'datatype', '') or '-'}", f"Unit: {getattr(obj, 'unit', '') or '-'}"]
        addr = getattr(obj, "address", None)
        lines.append(f"Address: {'0x%X' % addr if addr else '-'}  (ext {getattr(obj, 'address_extension', 0) or 0})")
        lo, hi = getattr(obj, "minimum", None), getattr(obj, "maximum", None)
        if lo is not None or hi is not None:
            lines.append(f"Limits: {lo} … {hi}")
        if hasattr(obj, "read_only"):
            lines.append(f"Read only: {'yes' if obj.read_only else 'no'}")
        QMessageBox.information(self, "Variable Information", "\n".join(lines))

    # ======================================================================
    # Ölçüm / bağlantı / yetki
    # ======================================================================
    @property
    def is_measuring(self) -> bool:
        return self._timer.isActive()

    def start_measurement(self):
        if not self._timer.isActive():
            self._timer.start()
            self.measuring_changed.emit(True)

    def stop_measurement(self):
        if self._timer.isActive():
            self._timer.stop()
            self.measuring_changed.emit(False)

    def toggle_measurement(self) -> bool:
        if self.is_measuring:
            self.stop_measurement()
        else:
            self.start_measurement()
        return self.is_measuring

    WARMUP_MS = (0, 150, 400, 900, 1800)

    def _warmup(self):
        """Ölçüm kapalıyken de yeni / bağlantı sonrası değer pencereleri bir değer göstersin: arka plan CCP önbelleği
        ilk okumada ısınır, bu yüzden kısa bir süre birkaç okuma turu istenir (değeri olan pencere kalmayınca durur)."""
        def need():
            return any(w.wp_value() is None for w in self.value_windows())

        for ms in self.WARMUP_MS:
            QTimer.singleShot(ms, lambda: self.read_requested.emit() if (self._online and need()) else None)

    def set_online(self, online: bool):
        """ECU/CCP çevrimiçi mi. Çevrimdışıyken değer pencereleri düzenlenemez, ölçüm turu durur."""
        was = self._online
        self._online = bool(online)
        if self._online and not was:
            self._warmup()
        for w in self.value_windows():
            w.set_allowed(self._allowed and self._online)
        if not online:
            self.stop_measurement()

    def set_allowed(self, allowed: bool):
        """Rol, kalibrasyon yazmaya izin veriyor mu."""
        self._allowed = bool(allowed)
        for w in self.value_windows():
            w.set_allowed(self._allowed and self._online)
        for w in self.table_windows():
            w.set_allowed(self._allowed)

    # ======================================================================
    # WP / RP gösterimi
    # ======================================================================
    @property
    def page(self) -> str:
        return self._page

    def wp_snapshot(self) -> dict:
        """Çalışma alanındaki KALİBRASYON etiketlerinin WP (canlı/ECU) değerleri: {ad: float | grid}."""
        out = {}
        for w in self.windows():
            if isinstance(w, ValueWindow) and w.is_calibration:
                v = w.wp_value()
                if v is not None:
                    out[w.label] = v
            elif isinstance(w, TableWindow):
                g = w.wp_grid()
                if g is not None and all(x is not None for row in g for x in row):
                    out[w.label] = g
        return out

    def set_reference(self, reference: dict):
        self._reference = reference
        for w in self.windows():
            self._apply_page_to(w)

    def set_page(self, page: str):
        if page not in (WP, RP) or page == self._page:
            return
        self._page = page
        for w in self.windows():
            self._apply_page_to(w)
        self.page_changed.emit(page)
        self.layout_changed.emit()

    def _apply_page_to(self, w):
        ref = self._reference.get(w.label) if self._page == RP else None
        if isinstance(w, ValueWindow):
            if w.is_calibration:
                w.set_reference_view(ref, rp=self._page == RP)
        elif isinstance(w, TableWindow):
            w.set_reference_view(ref, rp=self._page == RP)

    # ======================================================================
    # Kayıt
    # ======================================================================
    def _changed(self, save: bool = True):
        self.layout_changed.emit()
        if save:
            self._save_timer.start()

    def to_state(self) -> dict:
        return {"version": STATE_VERSION, "current": max(0, self.tabs.currentIndex()),
                "sheets": [{"name": s.name, "windows": self._sheet_specs(s)} for s in self._sheets]}

    def save(self) -> bool:
        self._save_timer.stop()
        return self.store.save(self.to_state())

    def _load(self):
        state = self.store.load()
        if state is None:
            self._make_sheet(DEFAULT_SHEET)
            return
        for s in state["sheets"]:
            sheet = self._make_sheet(s["name"], select=False)
            sheet.pending = list(s["windows"])
        idx = state["current"] if 0 <= state["current"] < len(self._sheets) else 0
        self.tabs.setCurrentIndex(idx)
        self._on_tab_changed(idx)

    def shutdown(self):
        self.stop_measurement()
        self.save()
