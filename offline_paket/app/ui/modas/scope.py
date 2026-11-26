"""Modas "oscilloscope" penceresi: ölçüm etiketlerini zaman grafiğinde gösterir.

Etiketler Variable list'ten sürüklenip bırakılır (ya da pencere menüsünden eklenir). Çizim, Çalışma Alanı'ndaki
``PlotPanel``'dir (gerçek birimli eksenler, üst üste / ayrı ayrı, A/B imleçleri, Δ / ortalama / min / maks tablosu); veri
``SignalHub``'dadır ve ölçüm turu (F9) ile beslenir: ölçüm durunca grafik de durur. Pencere ECU ile konuşmaz.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

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
        self.hint = QLabel("Variable list'ten etiket sürükleyip bırakın · veri F9 (Measurement) ile akar")
        self.hint.setObjectName("modasWinUnit")
        bar = QHBoxLayout()
        bar.addWidget(QLabel("Span:"))
        bar.addWidget(self.span_combo)
        bar.addWidget(self.freeze_check)
        bar.addWidget(self.clear_btn)
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
        return [label_of(s) for s in self.panel.signals_ids]

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
