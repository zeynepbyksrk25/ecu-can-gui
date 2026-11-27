"""Test yardımcıları: MainWindow gibi ağır pencereleri denetimli biçimde yok eder (aksi halde her test ~50 MB sızdırır;
CI'daki 2 işçi birlikte bellek sınırına dayanabiliyordu). Yalnızca TESTİN KENDİ oluşturduğu pencereler için kullanın."""
import gc

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication


def dispose(w):
    try:
        w.close()
        w.deleteLater()
    except RuntimeError:
        return
    app = QApplication.instance()
    if app is not None:
        app.sendPostedEvents(None, QEvent.DeferredDelete)
        app.processEvents()
    gc.collect()
