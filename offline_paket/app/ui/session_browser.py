"""Kayıtlı oturumlar: listele, analiz için aç (canlı trenddeki cursor/şerit/istatistik araçlarıyla), dışa aktar.

Yükleme ve dışa aktarma arka plan iş parçacığında çalışır (büyük kayıtta arayüz donmaz).
"""
from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox,
    QPushButton, QSplitter, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget, QAbstractItemView,
)

from app import session_export as sx
from app import theme
from app.ui.background import run_with_progress
from app.ui.dash_widgets import make_card

EVENT_COLORS = {"MARKER": theme.WARN, "KALIBRASYON": theme.PURPLE, "HATA": theme.DANGER, "BASLANGIC": theme.OK,
                "DURAKLATMA": theme.WARN_INK, "DEVAM": theme.WARN_INK, "BAGLANTI": theme.DANGER, "MODEL": theme.BLUE,
                "OTURUM": theme.MUTED, "ISARET": theme.WARN}
STATUS_TEXT = {"complete": "tamamlandı", "recovered": "KURTARILDI (beklenmedik kapanış)", "error": "HATA ile bitti",
               "unknown": "?"}
EXT = {"mf4": "mf4", "asc": "asc", "log": "log", "candump": "log", "csv": "csv", "mat": "mat"}


def event_color(kind: str) -> str | None:
    for k, c in EVENT_COLORS.items():
        if kind.startswith(k):
            return c
    return None


class AnalysisWindow(QDialog):
    """Bir oturumu TrendPanel (analiz modu) ile açar; sol tarafta sinyal seçimi."""

    def __init__(self, sd: sx.SessionData, parent=None):
        super().__init__(parent)
        from app.ui.trend_panel import TrendPanel
        self.sd = sd
        self.setWindowTitle(f"Oturum analizi — {sd.meta.get('name') or os.path.basename(sd.path)}")
        self.resize(1300, 760)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Sinyal ara…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        self.sig_list = QListWidget()
        for sid in sd.signals():
            u = sd.unit(sid)
            it = QListWidgetItem(f"{sid}" + (f"  [{u}]" if u else ""))
            it.setData(Qt.UserRole, sid)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Unchecked)
            self.sig_list.addItem(it)
        self.sim_axis_check = QCheckBox("Simülasyon zamanı ekseni (MIL)")
        self.sim_axis_check.setEnabled(sd.has_sim_time())
        self.sim_axis_check.setToolTip("Eksen = modelin simülasyon zamanı (mil:sim_time). Gerçek alım zamanı ile "
                                       "karıştırılmaz; eşleme yoksa/yeniden başlatma varsa kapalıdır.")
        self.sim_axis_check.toggled.connect(lambda _c: self.apply_selection())
        self.events_table = QTableWidget(0, 4)
        self.events_table.setHorizontalHeaderLabels(["Gerçek zaman (sn)", "Sistem saati", "Tür", "Olay"])
        self.events_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.events_table.verticalHeader().setVisible(False)
        self.events_table.horizontalHeader().setStretchLastSection(True)
        self.events_table.setMaximumHeight(170)
        self.events_table.setToolTip("Olay çizelgesi: her olay iki zamanla (gerçek zaman + sistem saati). ECU gücü kesintisi, "
                                     "bağlantı, hata, saat değişimi ve işaretler burada görünür.")
        self._fill_events()
        self.add_button = QPushButton("Seçilenleri grafiğe uygula")
        self.add_button.clicked.connect(self.apply_selection)
        self.info = QLabel(self._info_text())
        self.info.setWordWrap(True)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        for w in (self.info, self.filter_edit, self.sig_list, self.sim_axis_check, self.add_button, self.events_table):
            lv.addWidget(w)
        self.trend = TrendPanel()
        self.trend.btn_pick.setVisible(False)            # sinyal seçimi soldaki listeden
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(self.trend)
        split.setStretchFactor(1, 5)
        split.setSizes([300, 1000])
        lay = QVBoxLayout(self)
        lay.addWidget(split)
        self.trend.btn_cursor.setChecked(True)
        for i in range(min(4, self.sig_list.count())):   # ilk birkaç sinyal hazır seçili
            self.sig_list.item(i).setCheckState(Qt.Checked)
        self.apply_selection()

    def _fill_events(self):
        from app.session_recorder import system_time_text
        t = self.events_table
        evs = self.sd.events
        t.setRowCount(len(evs))
        for i, (tr, tu, kind, text) in enumerate(evs):
            vals = (f"{tr if abs(tr) >= 5e-4 else 0.0:.3f}", system_time_text(tu), kind, text)
            col = event_color(kind)
            for c, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if col and c == 2:
                    it.setForeground(QColor(col))
                if c == 3:
                    it.setToolTip(text)
                t.setItem(i, c, it)
        t.resizeColumnsToContents()

    def _info_text(self) -> str:
        m = self.sd.meta
        st = STATUS_TEXT.get(m.get("status", "unknown"), "?")
        colors = {"ok": theme.OK, "warn": theme.WARN_INK, "error": theme.DANGER}
        icons = {"ok": "✔", "warn": "⚠", "error": "✖"}
        integ = "".join(f"<br><span style='color:{colors[lv]}'>{icons[lv]} {txt}</span>" for lv, txt in self.sd.integrity())
        return (f"<b>{m.get('name') or os.path.basename(self.sd.path)}</b><br>Durum: {st} · kaynak: {m.get('mode') or '-'}"
                f" · kullanıcı: {m.get('user') or '-'}<br>{len(self.sd.signals())} sinyal, {len(self.sd.events)} olay"
                f"<br>Zaman: <b>gerçek zaman</b> (monotonik, sn) ve <b>sistem saati</b> ayrı kaydedildi" + integ)

    def _apply_filter(self, text: str):
        t = text.strip().lower()
        for i in range(self.sig_list.count()):
            self.sig_list.item(i).setHidden(bool(t) and t not in self.sig_list.item(i).text().lower())

    def selected_ids(self) -> list:
        return [self.sig_list.item(i).data(Qt.UserRole) for i in range(self.sig_list.count())
                if self.sig_list.item(i).checkState() == Qt.Checked]

    def apply_selection(self):
        sd = self.sd
        sim = self.sim_axis_check.isChecked() and sd.has_sim_time()
        t0 = sd.meta.get("start_unix") or 0.0
        specs = []
        for sid in self.selected_ids():
            tu = sd.t_axis(sid)              # başlangıç + gerçek zaman (monotonik): sistem saati atlasa da eğri bozulmaz
            if sim:
                tu = sd.to_sim_time(sd.t_unix[sid])
            specs.append({"key": sid, "label": sid.split(":", 1)[-1], "unit": sd.unit(sid), "source": sd.source(sid),
                          "t": list(tu), "v": list(sd.values[sid])})
        events = []
        for tr, tu, kind, text in sd.events:
            tu = sd.event_axis(tr)
            if sim:
                tu = float(sd.to_sim_time([tu])[0])
                if tu != tu:
                    continue
            col = event_color(kind)
            if col:
                events.append((tu, f"{kind}: {text}" if text else kind, col))
        self.trend.load_static(specs, events)
        if t0 and not specs:
            self.trend._tick()


class SessionBrowser(QWidget):
    """Oturum listesi + Aç / Dışa aktar. ``directory_provider()`` kayıt klasörünü verir."""
    status = Signal(str)

    def __init__(self, directory_provider, parent=None):
        super().__init__(parent)
        self._dir = directory_provider
        self._windows: list = []
        card, v, head = make_card("Kayıtlı oturumlar", "trend")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Oturum", "Başlangıç", "Süre", "Kaynak", "Durum", "Boyut"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setMinimumHeight(120)
        self.refresh_button = QPushButton("Yenile")
        self.refresh_button.clicked.connect(self.refresh)
        self.open_button = QPushButton("Analiz için Aç")
        self.open_button.setToolTip("Kaydı canlı trenddeki araçlarla (Main/Difference cursor, şeritler, istatistik) inceler")
        self.open_button.clicked.connect(self.open_selected)
        self.report_button = QPushButton("Test Raporu (HTML)")
        self.report_button.clicked.connect(lambda: self.report_selected())
        self.export_button = QPushButton("Dışa Aktar ▾")
        menu = QMenu(self.export_button)
        for fmt, label in sx.EXPORTERS.items():
            menu.addAction(label, lambda f=fmt: self.export_selected(f))
        self.export_button.setMenu(menu)
        row = QHBoxLayout()
        for w in (self.refresh_button, self.open_button, self.report_button, self.export_button):
            row.addWidget(w)
        row.addStretch(1)
        v.addWidget(self.table)
        v.addLayout(row)
        self._rows: list = []
        out = QVBoxLayout(self)
        out.setContentsMargins(0, 0, 0, 0)
        out.addWidget(card)

    def refresh(self):
        self._rows = sx.list_sessions(self._dir())
        self.table.setRowCount(len(self._rows))
        for r, d in enumerate(self._rows):
            dur = d["duration_s"]
            vals = [d["name"], time.strftime("%d.%m.%Y %H:%M:%S", time.localtime(d["start"])),
                    "-" if dur is None else f"{int(dur) // 60:02d}:{int(dur) % 60:02d}", d["mode"] or "-",
                    STATUS_TEXT.get(d["status"], d["status"]), f"{d['size'] / 1024:.0f} KB"]
            for c, t in enumerate(vals):
                self.table.setItem(r, c, QTableWidgetItem(t))

    def _selected(self):
        r = self.table.currentRow()
        return self._rows[r] if 0 <= r < len(self._rows) else None

    def _load(self, d):
        try:
            return run_with_progress(self, "Oturum yükleniyor…", lambda: sx.load_session(d["path"]))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self.window(), "Oturum açılamadı", str(exc))
            return None

    def open_selected(self):
        d = self._selected()
        if d is None:
            return
        sd = self._load(d)
        if sd is None:
            return
        if not sd.signals():
            QMessageBox.information(self.window(), "Boş oturum", "Bu kayıtta sinyal örneği yok.")
            return
        w = AnalysisWindow(sd, self.window())
        w.setAttribute(Qt.WA_DeleteOnClose, True)
        self._windows.append(w)
        w.destroyed.connect(lambda _=None, w=w: self._windows.remove(w) if w in self._windows else None)
        w.show()

    def report_selected(self, path: str | None = None):
        from app import session_report
        d = self._selected()
        if d is None:
            return None
        sd = self._load(d)
        if sd is None:
            return None
        if path is None:
            base = os.path.splitext(os.path.basename(d["path"]))[0]
            path, _ = QFileDialog.getSaveFileName(self.window(), "Test raporu", f"{base}_rapor.html", "HTML (*.html)")
            if not path:
                return None
        try:
            run_with_progress(self, "Rapor hazırlanıyor…", lambda: session_report.write_report(sd, path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self.window(), "Rapor", f"Yazılamadı: {exc}")
            return None
        self.status.emit(f"Rapor yazıldı: {path}")
        return path

    def export_selected(self, fmt: str, path: str | None = None):
        d = self._selected()
        if d is None:
            return None
        sd = self._load(d)
        if sd is None:
            return None
        if path is None:
            base = os.path.splitext(os.path.basename(d["path"]))[0]
            suffix = ".candump" if fmt == "candump" else ""
            path, _ = QFileDialog.getSaveFileName(self.window(), "Dışa aktar", f"{base}{suffix}.{EXT[fmt]}",
                                                  f"{EXT[fmt].upper()} (*.{EXT[fmt]})")
            if not path:
                return None
        try:
            run_with_progress(self, "Dışa aktarılıyor…", lambda: sx.export(sd, fmt, path))
        except ValueError as exc:
            QMessageBox.information(self.window(), "Dışa aktar", str(exc))
            return None
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self.window(), "Dışa aktar", f"Yazılamadı: {exc}")
            return None
        note = " (AVL Concerto ile uyumluluk DOĞRULANMADI)" if fmt == "mf4" else ""
        self.status.emit(f"Dışa aktarıldı: {path}{note}")
        return path
