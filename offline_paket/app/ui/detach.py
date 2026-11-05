"""Bir widget'ı (sayfa/panel) ana pencereden ayrı, bağımsız bir pencereye alır.

Ayrılan widget'ın yerine "ayrı pencerede" yer tutucusu konur; pencere kapatılınca
veya "geri yerleştir" düğmesine basılınca widget eski yerine (aynı layout, aynı
sıra, aynı esneme) döner. Pencere sahipsizdir (parent=None): ikinci monitöre
taşınabilir ve ana pencereyle birlikte gizlenmez.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QBoxLayout, QFrame, QLabel, QPushButton, QVBoxLayout, QWidget


class DetachedWindow(QWidget):
    dock_requested = Signal()

    def __init__(self, title: str):
        super().__init__(None, Qt.Window)
        from app.ui.dark_theme import dark_qss
        self.setWindowTitle(title)
        self.setObjectName("floatBody")
        self.setStyleSheet("QWidget#floatBody { background:#08121f; }" + dark_qss("floatBody"))
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(4, 4, 4, 4)
        btn = QPushButton("⤓  Ana pencereye geri yerleştir")
        btn.clicked.connect(self.dock_requested.emit)
        self._lay.addWidget(btn, 0, Qt.AlignLeft)

    def set_content(self, widget: QWidget):
        widget.setParent(self)
        self._lay.addWidget(widget, 1)

    def closeEvent(self, ev):  # noqa: N802
        # Pencereyi kapatmak widget'ı yok etmez, eski yerine döndürür.
        ev.ignore()
        self.dock_requested.emit()


class PanelDetacher(QObject):
    """``widget``'ı bulunduğu layout'tan ayrı pencereye alır / geri koyar."""
    state_changed = Signal(bool)   # True = ayrıldı

    def __init__(self, widget: QWidget, title: str, button: QWidget | None = None):
        super().__init__(widget)
        self.widget = widget
        self.title = title
        self.button = button            # ayrıldığında gizlenecek "ayır" düğmesi
        self._win: DetachedWindow | None = None
        self._holder: QFrame | None = None
        self._layout = None
        self._parent: QWidget | None = None
        self._index = 0
        self._stretch = 0

    def is_detached(self) -> bool:
        return self._win is not None

    def window_widget(self) -> DetachedWindow | None:
        return self._win

    def detach(self) -> bool:
        if self._win is not None:
            self._win.raise_()
            self._win.activateWindow()
            return True
        parent = self.widget.parentWidget()
        lay = parent.layout() if parent is not None else None
        if not isinstance(lay, QBoxLayout):
            return False
        self._parent, self._layout = parent, lay
        self._index = lay.indexOf(self.widget)
        self._stretch = lay.stretch(self._index)
        size = self.widget.size()

        holder = QFrame()
        holder.setObjectName("detachHolder")
        hl = QVBoxLayout(holder)
        hl.setAlignment(Qt.AlignCenter)
        msg = QLabel(f"“{self.title}” ayrı pencerede açık.")
        msg.setAlignment(Qt.AlignCenter)
        back = QPushButton("⤓  Geri yerleştir")
        back.clicked.connect(self.dock)
        hl.addWidget(msg)
        hl.addWidget(back, 0, Qt.AlignCenter)
        self._holder = holder

        lay.removeWidget(self.widget)
        lay.insertWidget(self._index, holder, self._stretch)

        win = DetachedWindow(self.title)
        win.dock_requested.connect(self.dock)
        win.set_content(self.widget)
        win.resize(max(size.width(), 640), max(size.height(), 400))
        self._win = win
        if self.button is not None:
            self.button.setVisible(False)
        win.show()
        self.widget.show()
        self.state_changed.emit(True)
        return True

    def dock(self):
        win, holder = self._win, self._holder
        if win is None:
            return
        self._win = self._holder = None
        lay = self._layout
        if holder is not None and lay is not None:
            lay.removeWidget(holder)
            holder.deleteLater()
        self.widget.setParent(self._parent)
        if lay is not None:
            lay.insertWidget(min(self._index, lay.count()), self.widget, self._stretch)
        self.widget.show()
        if self.button is not None:
            self.button.setVisible(True)
        win.hide()
        win.deleteLater()
        self.state_changed.emit(False)
