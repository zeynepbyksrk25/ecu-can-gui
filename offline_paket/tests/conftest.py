import os
import sys

import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Testler depo klasörüne ayar/log dosyası yazmasın:
os.environ["OPENECU_VERI_KLASORU"] = tempfile.mkdtemp(prefix="openecu_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def _fresh_worksheets():
    """Worksheet düzeni (modas_worksheets.json) testler arasında sızmasın: önceki testin kaydettiği pencereler
    sonraki testin MainWindow'unda canlanmasın."""
    from app.paths import data_path
    for name in ("modas_worksheets.json", "modas_templates.json"):
        for suffix in ("", ".bak", ".tmp"):
            try:
                os.remove(data_path(name) + suffix)
            except OSError:
                pass
    import shutil
    for folder in ("makrolar", "parametre_dosyalari", "modas_projects"):
        shutil.rmtree(data_path(folder), ignore_errors=True)
    yield


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
    # Testin yerel widget'ları (sahipsiz sekmeler, grafikler) QApplication hâlâ YAŞARKEN, kontrollü sırayla
    # yok edilsin; yorumlayıcı kapanışına bırakılırsa PySide çöker.
    import gc
    gc.collect()
    app.processEvents()


@pytest.fixture(scope="session", autouse=True)
def qapp():
    """QApplication tüm oturum için OTOMATİK kurulur. (Eskiden yalnızca isteyen testlerde kuruluyordu; fixture'ı
    istemeyen bir test pencere oluşturursa ve süreçte ondan önce başka test QApplication kurmamışsa Qt süreci
    abort ediyordu: test sırasına/paralel dağılıma bağlı rastgele çökme.)"""
    import gc
    from PySide6.QtWidgets import QApplication
    from app.theme import APP_QSS
    app = QApplication.instance() or QApplication([])
    app.setStyleSheet(APP_QSS)
    yield app
    # Pencereler kapatılır ama ZORLA silinmez (deleteLater/DeferredDelete): pyqtgraph'ın QGraphicsScene'i
    # Python tarafı hâlâ yaşarken yok edilirse PySide çöker.
    for w in app.topLevelWidgets():
        w.close()
    app.processEvents()
    gc.collect()
    app.processEvents()


# ---- Çıkış: test süreci yüzlerce pencereyi (Dashboard, grafikler...) biriktirir; yorumlayıcı kapanışında
# PySide bunları yok ederken (PySide::destroyQCoreApplication) bazen çöker (segfault, çıkış kodu 139) ve
# tüm testler geçmiş olsa bile CI'ı kırmızıya boyar. GERÇEK UYGULAMA ETKİLENMEZ: ekransız başlatılıp
# kapatıldığında 8/8 temiz (çıkış kodu 0) çıkar. Bu yüzden testlerin kendi sonucu çıkış kodu olarak
# korunur ve süreç, Qt'nin kapanış temizliği atlanarak sonlandırılır. OPENECU_TEST_NORMAL_EXIT=1 ile
# normal çıkış (hata ayıklama için) istenebilir.
_exit_status = {"code": None}


def pytest_sessionfinish(session, exitstatus):
    _exit_status["code"] = int(exitstatus)


def pytest_unconfigure(config):
    if _exit_status["code"] is None or os.environ.get("OPENECU_TEST_NORMAL_EXIT"):
        return
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(_exit_status["code"])
