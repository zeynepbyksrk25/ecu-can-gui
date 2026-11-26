"""MATLAB Lookup Table Editor tarzı tablo başlıkları.

Üst başlık iki satırdır: gri "indeks" satırı (1, 2, 3 ...) + altında KALIN eksen
değeri. Sol başlık iki sütundur: gri indeks sütunu + KALIN eksen değeri.
Köşe hücresine MATLAB'daki gibi çapraz çizgi çizilir. Eksen değerleri
modelin başlık metninden (setHorizontal/VerticalHeaderLabels) okunur.
"""

from PySide6.QtCore import QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractButton, QHeaderView, QWidget

from app import theme

INDEX_W = 34


class LookupHeader(QHeaderView):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setSectionsClickable(True)
        self.setHighlightSections(True)
        # Çizimi paintSection yapar; bildirilen renkler okunabilir kontrast sözleşmesini belgeler/test eder.
        self.setStyleSheet(theme.paint("QHeaderView::section { background:@@MODAS_TABLE_HEAD@@; color:@@INK@@; font-weight:bold; }"))

    def _row_h(self) -> int:
        return self.fontMetrics().height() + 10

    def _label(self, i: int) -> str:
        v = self.model().headerData(i, self.orientation(), Qt.DisplayRole) if self.model() else None
        return "" if v is None else str(v)

    def sizeHint(self):
        if self.orientation() == Qt.Horizontal:
            return QSize(super().sizeHint().width(), 2 * self._row_h())
        fm = self.fontMetrics()
        n = self.count()
        w = max([fm.horizontalAdvance(self._label(i)) for i in range(n)] + [24])
        return QSize(INDEX_W + w + 22, super().sizeHint().height())

    def _selected(self, i: int) -> bool:
        sm = self.parent().selectionModel() if self.parent() is not None else None
        if sm is None:
            return False
        return sm.columnIntersectsSelection(i, self.rootIndex()) if self.orientation() == Qt.Horizontal \
            else sm.rowIntersectsSelection(i, self.rootIndex())

    def paintSection(self, p: QPainter, rect: QRect, i: int):
        if not rect.isValid():
            return
        p.save()
        idx_bg = QColor(theme.MODAS_TABLE_HEAD)
        val_bg = QColor(theme.MODAS_TABLE_ALT)
        if self._selected(i):
            idx_bg, val_bg = idx_bg.darker(108), val_bg.darker(104)
        if self.orientation() == Qt.Horizontal:
            h = rect.height() // 2
            top, bot = QRect(rect.x(), rect.y(), rect.width(), h), QRect(rect.x(), rect.y() + h, rect.width(), rect.height() - h)
            idx_rect, val_rect = top, bot
            idx_align = Qt.AlignCenter
            val_align = Qt.AlignRight | Qt.AlignVCenter
        else:
            idx_rect = QRect(rect.x(), rect.y(), INDEX_W, rect.height())
            val_rect = QRect(rect.x() + INDEX_W, rect.y(), rect.width() - INDEX_W, rect.height())
            idx_align = Qt.AlignCenter
            val_align = Qt.AlignRight | Qt.AlignVCenter
        border = QPen(QColor(theme.MODAS_WIN_LINE))
        for r, bg in ((idx_rect, idx_bg), (val_rect, val_bg)):
            p.fillRect(r, bg)
            p.setPen(border)
            p.drawRect(r.adjusted(0, 0, -1, -1))
        p.setPen(QColor(theme.MODAS_GROUP_LABEL))
        p.drawText(idx_rect, int(idx_align), str(i + 1))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(theme.INK))
        p.drawText(val_rect.adjusted(4, 0, -8, 0), int(val_align), self._label(i))
        p.restore()


class _CornerOverlay(QWidget):
    """Köşe hücresinde MATLAB'daki çapraz çizgi."""

    def __init__(self, button):
        super().__init__(button)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setGeometry(button.rect())
        self.show()

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setPen(QPen(QColor(theme.MODAS_WIN_LINE), 1))
        p.drawLine(2, 2, self.width() - 3, self.height() - 3)
        p.end()


class _ResizeWatcher(QObject):
    def __init__(self, button, overlay):
        super().__init__(button)
        self._overlay = overlay

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Resize:
            self._overlay.setGeometry(obj.rect())
        return False


def apply_lookup_style(table):
    """Tabloya iki satırlı/sütunlu MATLAB başlıklarını ve çapraz köşeyi uygular."""
    table.setHorizontalHeader(LookupHeader(Qt.Horizontal, table))
    table.setVerticalHeader(LookupHeader(Qt.Vertical, table))
    table.horizontalHeader().setDefaultSectionSize(72)
    table.verticalHeader().setDefaultSectionSize(26)
    table.setShowGrid(True)
    table.setStyleSheet(theme.paint("QTableWidget { gridline-color:@@MODAS_WIN_LINE@@; background:@@MODAS_CAL_BG@@; "
                                  "selection-background-color:@@MODAS_LIST_SEL@@; selection-color:@@INK@@; }"))
    corner = table.findChild(QAbstractButton)
    if corner is not None:
        ov = _CornerOverlay(corner)
        corner.installEventFilter(_ResizeWatcher(corner, ov))
