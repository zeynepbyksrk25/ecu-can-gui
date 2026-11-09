import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _host(widget, stretch=10):
    host = QWidget()
    lay = QVBoxLayout(host)
    lay.addWidget(QWidget(), 1)
    lay.addWidget(widget, stretch)
    lay.addWidget(QWidget(), 1)
    host.show()
    return host, lay


def test_detach_and_dock_restores_slot(qapp):
    from app.ui.trend_panel import TrendPanel
    w = TrendPanel()
    host, lay = _host(w)
    idx = lay.indexOf(w)
    assert w.detacher.detach()
    win = w.detacher.window_widget()
    assert win is not None and win.parent() is None
    assert w.parentWidget() is win
    assert lay.indexOf(w) == -1 and lay.count() == 3        # yer tutucu girdi
    w.detacher.dock()
    assert not w.detacher.is_detached()
    assert w.parentWidget() is host
    assert lay.indexOf(w) == idx and lay.stretch(idx) == 10
    assert lay.count() == 3


def test_closing_detached_window_docks_back(qapp):
    from app.ui.trend_panel import TrendPanel
    w = TrendPanel()
    host, lay = _host(w)
    w.detacher.detach()
    w.detacher.window_widget().close()
    assert not w.detacher.is_detached() and w.parentWidget() is host
