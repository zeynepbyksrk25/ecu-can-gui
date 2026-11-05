import os
import sys

import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Testler depo klasörüne ayar/log dosyası yazmasın:
os.environ["OPENECU_VERI_KLASORU"] = tempfile.mkdtemp(prefix="openecu_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    from app.theme import APP_QSS
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_QSS)
    return app
