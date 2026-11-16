import os
import sys

import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Testler depo klasörüne ayar/log dosyası yazmasın:
os.environ["OPENECU_VERI_KLASORU"] = tempfile.mkdtemp(prefix="openecu_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _qt_cleanup():
    """Test yalıtımı: her testten sonra açık kalan pencereler kapatılır, zamanlayıcıları durdurulur. Aksi halde önceki
    testlerin pencereleri (zamanlayıcıları ve iş parçacıklarıyla) yaşamaya devam eder; sonraki testleri
    yavaşlatır ve zamanlamaya duyarlı testleri sıraya bağımlı hale getirir."""
    yield
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return
    for w in app.topLevelWidgets():
        try:
            w.close()                                  # MainWindow: bağlantıyı, iş parçacıklarını kapatır
            for timer in w.findChildren(QTimer):       # tek başına kurulan sekmeler de sussun
                timer.stop()
        except RuntimeError:                           # zaten silinmiş
            pass
    app.processEvents()


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    from app.theme import APP_QSS
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_QSS)
    return app


# ---- Çıkış: Qt nesnelerinin yorumlayıcı kapanışındaki rastgele silinme sırası, tüm testler geçtikten SONRA
# süreci çökertebiliyor (segfault, çıkış kodu 139) ve CI'ı yanlış yere kırmızıya boyuyor. Testlerin kendi
# sonucu çıkış kodu olarak korunur; yorumlayıcının nesne temizliği atlanır.
_exit_status = {"code": None}


def pytest_sessionfinish(session, exitstatus):
    _exit_status["code"] = int(exitstatus)


def pytest_unconfigure(config):
    if _exit_status["code"] is None or os.environ.get("OPENECU_TEST_NORMAL_EXIT"):
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_status["code"])
