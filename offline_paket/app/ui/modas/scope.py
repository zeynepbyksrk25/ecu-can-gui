"""Modas "oscilloscope" penceresi: ölçüm etiketlerini zaman grafiğinde gösterir.

A2L etiketleri Variable list'ten sürüklenip bırakılır; DBC sinyalleri, göstergeler, girişler, matematik sinyalleri ve
içe aktarılan CSV kayıtları "Sinyaller…" düğmesinden eklenir. Çizim ``PlotPanel``'dir (gerçek birimli eksenler, üst üste /
ayrı ayrı, A/B imleçleri, Δ / ortalama / min / maks tablosu); veri ortak ``SignalHub``'dadır. A2L etiketleri ölçüm turu (F9)
ile, DBC/gösterge/giriş sinyalleri canlı akışla beslenir. Pencere ECU ile konuşmaz.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from app import theme
from app.ui.modas.variable_list import MIME
from app.ui.modas.windows import ModasSub
from app.ui.workspace_panels import PlotPanel

SPANS = [("10 s", 10.0), ("30 s", 30.0), ("1 min", 60.0), ("5 min", 300.0), ("10 min", 600.0)]
REFRESH_MS = 250
PREFIX = "a2l:"


def sid_of(label: str) -> str:
    return PREFIX + label


def label_of(sid: str) -> str:
    return sid[len(PREFIX):] if sid.startswith(PREFIX) else sid


class _Body(QWidget):
    labels_dropped = Signal(list)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)

    def dragEnterEvent(self, ev):  # noqa: N802
        if ev.mimeData().hasFormat(MIME):
            ev.acceptProposedAction()

    def dragMoveEvent(self, ev):  # noqa: N802
        if ev.mimeData().hasFormat(MIME):
            ev.acceptProposedAction()

    def dropEvent(self, ev):  # noqa: N802
        if not ev.mimeData().hasFormat(MIME):
            return
        names = bytes(ev.mimeData().data(MIME)).decode("utf-8").split("\n")
        self.labels_dropped.emit([n for n in names if n])
        ev.acceptProposedAction()


class ScopeWindow(ModasSub):
    changed = Signal()                      # sinyal listesi / ayar değişti (çalışma alanı düzeni kirlendi)
    pick_requested = Signal()               # "Sinyaller…": DBC / gösterge / giriş / matematik / CSV seçici
    math_requested = Signal(str)            # "ƒ Matematik": "" = yeni, "math:ad" = düzenle
    math_delete_requested = Signal(str)
    csv_open_requested = Signal()
    csv_export_requested = Signal()

    def __init__(self, label: str, hub, state: dict | None = None):
        super().__init__(label, theme.ACCENT)
        self.hub = hub
        self.panel = PlotPanel(hub)
        self.panel.changed.connect(self.changed.emit)
        self._span = 30.0
        self._frozen = False

        self.span_combo = QComboBox()
        for text, secs in SPANS:
            self.span_combo.addItem(text, secs)
        self.span_combo.setCurrentIndex(1)
        self.span_combo.currentIndexChanged.connect(self._on_span)
        self.freeze_check = QCheckBox("Hold")
        self.freeze_check.setToolTip("Grafiği dondurur (veri arka planda kaydedilmeye devam eder); dondurulunca fareyle yakınlaştırılır")
        self.freeze_check.toggled.connect(self._on_freeze)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.setToolTip("Seçili sinyalleri listeden kaldır")
        self.clear_btn.clicked.connect(self.clear_signals)
        self.pick_btn = QPushButton("Sinyaller…")
        self.pick_btn.setToolTip("DBC sinyali, gösterge, giriş, matematik sinyali ya da içe aktarılan kayıt ekle")
        self.pick_btn.clicked.connect(self.pick_requested.emit)
        self.math_btn = QToolButton()
        self.math_btn.setText("ƒ Matematik")
        self.math_btn.setPopupMode(QToolButton.InstantPopup)
        self.math_btn.setToolTip("Matematik sinyali: ölçekle (a·x+b), A ○ B işlemi, hareketli ortalama")
        self._math_menu = QMenu(self.math_btn)
        self._math_menu.aboutToShow.connect(self._fill_math_menu)
        self.math_btn.setMenu(self._math_menu)
        self.csv_btn = QToolButton()
        self.csv_btn.setText("CSV")
        self.csv_btn.setPopupMode(QToolButton.InstantPopup)
        csv_menu = QMenu(self.csv_btn)
        csv_menu.addAction("Kayıt aç (CSV)…", self.csv_open_requested.emit)
        csv_menu.addAction("Canlı kaydı CSV'ye aktar…", self.csv_export_requested.emit)
        self.csv_btn.setMenu(csv_menu)
        self.hint = QLabel("Variable list'ten etiket sürükleyin ya da Sinyaller… ile ekleyin · A2L verisi F9 (Measurement) ile akar")
        self.hint.setObjectName("modasWinUnit")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Span:"))
        bar.addWidget(self.span_combo)
        bar.addWidget(self.freeze_check)
        bar.addWidget(self.clear_btn)
        bar.addWidget(self.pick_btn)
        bar.addWidget(self.math_btn)
        bar.addWidget(self.csv_btn)
        bar.addStretch(1)
        bar.addWidget(self.hint)

        body = _Body()
        body.labels_dropped.connect(self.add_labels)
        lay = QVBoxLayout(body)
        lay.setContentsMargins(4, 3, 4, 4)
        lay.setSpacing(3)
        lay.addLayout(bar)
        lay.addWidget(self.panel, 1)
        for w in self.panel.findChildren(QWidget):          # QGraphicsView / tablo bırakmayı yutmasın: olay gövdeye çıksın
            w.setAcceptDrops(False)
        self.setWidget(body)
        self.resize(640, 420)
        self.panel.set_span(self._span)
        if state:
            self.apply_state(state)

        self._timer = QTimer(self)
        self._timer.setInterval(REFRESH_MS)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._sync_hint()

    # ---- sinyaller -------------------------------------------------------------------
    def signals(self) -> list:
        return list(self.panel.signals_ids)

    def labels(self) -> list:
        """İzlenen A2L etiket adları (ölçüm turu bunları okur); DBC/gösterge/matematik sinyalleri dahil değildir."""
        return [label_of(s) for s in self.panel.signals_ids if s.startswith(PREFIX)]

    def add_signals(self, sids: list) -> int:
        """Herhangi bir sinyal kimliğini (``dbc:``, ``gauge:``, ``input:``, ``math:``, ``csv:`` …) grafiğe ekler."""
        n = sum(1 for sid in sids if self.panel.add_signal(sid))
        self._sync_hint()
        return n

    def _fill_math_menu(self):
        m = self._math_menu
        m.clear()
        m.addAction("Yeni matematik sinyali…", lambda: self.math_requested.emit(""))
        derived = sorted(self.hub.derived)
        if derived:
            edit, delete = m.addMenu("Düzenle"), m.addMenu("Sil")
            for sid in derived:
                edit.addAction(sid.split(":", 1)[1], lambda _c=False, s=sid: self.math_requested.emit(s))
                delete.addAction(sid.split(":", 1)[1], lambda _c=False, s=sid: self.math_delete_requested.emit(s))

    def add_labels(self, names: list) -> int:
        n = 0
        for name in names:
            if self.panel.add_signal(sid_of(name)):
                n += 1
        self._sync_hint()
        return n

    def clear_signals(self):
        for sid in list(self.panel.signals_ids):
            self.panel.remove_signal(sid)
        self._sync_hint()

    def _sync_hint(self):
        self.hint.setVisible(not self.panel.signals_ids)

    # ---- görünüm ---------------------------------------------------------------------
    def _on_span(self, _i):
        self._span = float(self.span_combo.currentData())
        self.panel.set_span(self._span)
        self.panel.refresh(self._span, self._frozen)
        self.changed.emit()

    def _on_freeze(self, on: bool):
        self._frozen = bool(on)
        self.panel.set_frozen(self._frozen)
        if not self._frozen:
            self.panel.refresh(self._span, False)

    def _tick(self):
        if self.isVisible() and not self._frozen:
            self.panel.refresh(self._span, False)

    # ---- durum -----------------------------------------------------------------------
    def apply_state(self, state: dict):
        span = state.get("span")
        idx = next((i for i, (_t, s) in enumerate(SPANS) if span == s), 1)
        self.span_combo.blockSignals(True)
        self.span_combo.setCurrentIndex(idx)
        self.span_combo.blockSignals(False)
        self._span = float(SPANS[idx][1])
        self.panel.set_span(self._span)
        panel_state = state.get("panel")
        if isinstance(panel_state, dict):
            self.panel.from_state(panel_state)

    def state(self) -> dict:
        return {"kind": "scope", "name": self.label, "geom": self.geometry_state(), "span": self._span,
                "panel": self.panel.to_state()}

    def closeEvent(self, event):  # noqa: N802
        self._timer.stop()
        super().closeEvent(event)
