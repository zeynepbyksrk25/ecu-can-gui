import os
import tempfile

import pytest

pytest.importorskip("PySide6")


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


@pytest.fixture
def datadir(monkeypatch):
    d = tempfile.mkdtemp()
    monkeypatch.setenv("OPENECU_VERI_KLASORU", d)
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", None)
    return d


def test_main_window_builds_and_closes(qapp, datadir):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    qapp.processEvents()
    w.close()
