"""Performans sayfası ve Ana Sayfa giriş paneli için ortak küçük bileşenler:
siyah dijital değer kutusu, renkli kart çerçevesi, sinyal seçme ve eşik
diyalogları."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMenu, QVBoxLayout, QWidget,
)

from app.sim_interface import CARD_STYLES, SourceSig


def fmt_value(v, digits: int = 4) -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):.{digits}g}"
    except (TypeError, ValueError):
        return "—"


class Sparkline(QWidget):
    """Kutunun sağındaki küçük eğilim çizgisi (son değerler)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pts: list = []
        self.setFixedSize(84, 26)

    def set_points(self, pts: list):
        self._pts = list(pts)
        self.update()

    def paintEvent(self, _e):
        from PySide6.QtGui import QColor, QPainter, QPen, QPolygonF
        from PySide6.QtCore import QPointF
        if len(self._pts) < 2:
            return
        lo, hi = min(self._pts), max(self._pts)
        span = (hi - lo) or 1.0
        n = len(self._pts) - 1
        w, h = self.width() - 2, self.height() - 4
        poly = QPolygonF([QPointF(1 + w * i / n, 2 + h * (1 - (v - lo) / span)) for i, v in enumerate(self._pts)])
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor("#5FA8D3"), 1.4))
        p.drawPolyline(poly)


class ColorCard(QFrame):
    """Koyu kart (A–E): rozet ve başlık, kartın vurgu rengini taşır."""

    ACCENTS = {"A": "#5aa9ff", "B": "#4ade80", "C": "#f0c040", "D": "#ff9a52", "E": "#2dd4bf"}

    def __init__(self, card_id: str, parent=None):
        super().__init__(parent)
        title = CARD_STYLES[card_id][0]
        ink = self.ACCENTS.get(card_id, "#35c6f4")
        self.setObjectName("colorCard")
        self.setStyleSheet(
            "QFrame#colorCard { background:#0f2034; border:1px solid #1f3853; border-radius:12px; }"
            f"QLabel#cardTitle {{ color:{ink}; font-size:14px; font-weight:800; background:transparent; }}")
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(14, 10, 14, 12)
        self.outer.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        badge = QLabel(card_id)
        badge.setFixedSize(26, 26)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet(f"background:{ink}; color:#08121f; border-radius:13px; font-weight:800; font-size:13px;")
        self.title_label = QLabel(title.split(". ", 1)[-1])
        self.title_label.setObjectName("cardTitle")
        head.addWidget(badge)
        head.addWidget(self.title_label, 1)
        self.outer.addLayout(head)
        self.body = QGridLayout()
        self.body.setSpacing(8)
        self.outer.addLayout(self.body, 1)


class DigitalBox(QFrame):
    """Siyah dijital kutu: isim (sol üst, küçük), değer (büyük), birim, eğilim oku."""

    bind_requested = Signal(str)
    unbind_requested = Signal(str)
    threshold_requested = Signal(str)

    COLORS = {0: "#FFFFFF", 1: "#FFC93C", 2: "#FF5A4D"}

    def __init__(self, key: str, label: str, unit: str, hint: str = "", parent=None):
        super().__init__(parent)
        self.key = key
        self._label = label
        self._unit = unit
        self._hint = hint
        self.setObjectName("digitalBox")
        self.setMinimumHeight(56)
        self.setMaximumHeight(72)
        self.setStyleSheet("QFrame#digitalBox { background:#0a1626; border:1px solid #1a3049; border-radius:8px; }"
                           "QLabel { background:transparent; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 5, 10, 5)
        lay.setSpacing(0)
        top = QHBoxLayout()
        self.name_label = QLabel(label + (f"  ({hint})" if hint else ""))
        self.name_label.setStyleSheet("color:#9FB3C4; font-size:11px; font-weight:600;")
        self.name_label.setWordWrap(False)
        self.bound_label = QLabel("")
        self.bound_label.setStyleSheet("color:#F2B84B; font-size:10px; font-weight:700;")
        top.addWidget(self.name_label, 1)
        top.addWidget(self.bound_label)
        row = QHBoxLayout()
        self.value_label = QLabel("—")
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.value_label.setStyleSheet("color:#FFFFFF; font-size:21px; font-weight:700; font-family:'IBM Plex Mono','DejaVu Sans Mono',monospace;")
        self.unit_label = QLabel(unit)
        self.unit_label.setStyleSheet("color:#8FA3B3; font-size:11px;")
        self.trend_label = QLabel("")
        self.trend_label.setStyleSheet("color:#7FA6C4; font-size:12px;")
        self.spark = Sparkline()
        self.spark.setVisible(False)
        row.addWidget(self.value_label)
        row.addWidget(self.unit_label)
        row.addWidget(self.trend_label)
        row.addStretch(1)
        row.addWidget(self.spark)
        lay.addLayout(top)
        lay.addLayout(row)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        self.set_bound(False, "")

    def set_bound(self, bound: bool, name: str):
        self.bound_label.setText("" if bound else "bağla")
        self.setToolTip(f"{self._label}\nKaynak: {name}" if bound else
                        f"{self._label}\nBağlı sinyal yok — sağ tık: Sinyal bağla…")

    BORDERS = {0: "none", 1: "2px solid #FFC93C", 2: "2px solid #FF5A4D"}
    ICONS = {0: "", 1: "⚠ ", 2: "⛔ "}

    def set_value(self, value, level: int = 0, trend: int = 0, stale: bool = False):
        if stale:
            level = 0
        self.setStyleSheet(f"QFrame#digitalBox {{ background:#0a1626; border-radius:8px; "
                           f"border:{self.BORDERS.get(level, '1px solid #1a3049')}; }} QLabel {{ background:transparent; }}")
        base = self._label + (f"  ({self._hint})" if self._hint else "")
        self.name_label.setText(self.ICONS.get(level, "") + base)
        color = "#5F7283" if stale else self.COLORS.get(level, "#FFFFFF")
        self.value_label.setText(fmt_value(value))
        self.value_label.setStyleSheet(
            f"color:{color}; font-size:21px; font-weight:700; "
            "font-family:'IBM Plex Mono','DejaVu Sans Mono',monospace;")
        self.trend_label.setText("▲" if trend > 0 else "▼" if trend < 0 else "")

    def set_history(self, pts: list):
        self.spark.setVisible(len(pts) >= 2)
        self.spark.set_points(pts)

    def _menu(self, pos):
        m = QMenu(self)
        a1 = m.addAction("Sinyal bağla…")
        a2 = m.addAction("Eşik ayarla…")
        a3 = m.addAction("Bağlantıyı kaldır")
        act = m.exec(self.mapToGlobal(pos))
        if act is a1:
            self.bind_requested.emit(self.key)
        elif act is a2:
            self.threshold_requested.emit(self.key)
        elif act is a3:
            self.unbind_requested.emit(self.key)


class SignalPickerDialog(QDialog):
    def __init__(self, title: str, sources: list[SourceSig], current: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(560, 460)
        self._sources = sources
        lay = QVBoxLayout(self)
        self.search = QLineEdit()
        self.search.setPlaceholderText("İsme göre ara...")
        self.list = QListWidget()
        lay.addWidget(self.search)
        lay.addWidget(self.list, 1)
        self.info = QLabel("")
        lay.addWidget(self.info)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        for s in sources:
            it = QListWidgetItem(s.label)
            it.setData(Qt.UserRole, s.key)
            self.list.addItem(it)
            if s.key == current:
                self.list.setCurrentItem(it)
        self.search.textChanged.connect(self._filter)
        self.list.itemDoubleClicked.connect(lambda _i: self.accept())
        if not sources:
            self.info.setText("Kaynak yok: önce DBC ve/veya A2L dosyasını yükleyin.")

    def _filter(self, text):
        t = text.strip().lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def selected_key(self) -> str:
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it is not None else ""


class ThresholdDialog(QDialog):
    def __init__(self, title: str, cfg: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        cfg = cfg or {}
        form = QFormLayout(self)
        self.mode = QComboBox()
        self.mode.addItem("Değer eşiğin ALTINA düşünce (ör. Surge Margin)", "low")
        self.mode.addItem("Değer eşiğin ÜSTÜNE çıkınca (ör. sıcaklık)", "high")
        self.mode.setCurrentIndex(0 if cfg.get("mode", "low") == "low" else 1)
        self.warn = QLineEdit("" if cfg.get("warn") is None else str(cfg["warn"]))
        self.crit = QLineEdit("" if cfg.get("crit") is None else str(cfg["crit"]))
        self.warn.setPlaceholderText("boş = uyarı yok")
        self.crit.setPlaceholderText("boş = kritik yok")
        form.addRow("Koşul:", self.mode)
        form.addRow("Uyarı eşiği (sarı):", self.warn)
        form.addRow("Kritik eşik (kırmızı):", self.crit)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    @staticmethod
    def _num(text):
        t = text.strip().replace(",", ".")
        if not t:
            return None
        try:
            return float(t)
        except ValueError:
            return None

    def result_cfg(self) -> dict | None:
        w, c = self._num(self.warn.text()), self._num(self.crit.text())
        if w is None and c is None:
            return None
        return {"mode": self.mode.currentData(), "warn": w, "crit": c}
