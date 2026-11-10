import ctypes
import logging
import logging.handlers
import sys
import threading
import traceback

from PySide6.QtCore import QLockFile, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from app.icon import make_icon
from app.paths import data_path
from app.theme import APP_QSS
from app.ui.main_window import MainWindow

APP_USER_MODEL_ID = "OpenECU.M220.TestKalibrasyon"


log = logging.getLogger("openecu")
_shown_errors = 0


def setup_logging():
    """Dosyaya (döner log) ve stderr'e günlük. --noconsole exe'de hatalar
    artık kaybolmaz: openecu.log içinde kalır."""
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        fh = logging.handlers.RotatingFileHandler(
            data_path("openecu.log"), maxBytes=2_000_000, backupCount=3, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(fh)
    except OSError:
        pass
    if sys.stderr is not None:
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)


def install_excepthook():
    """Yakalanmamış her istisnayı loglar ve (taşmayı önleyerek) kullanıcıya gösterir."""
    def hook(exc_type, exc, tb):
        global _shown_errors
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.error("Yakalanmamış hata:\n%s", text)
        _shown_errors += 1
        if _shown_errors <= 3 and QApplication.instance() is not None:
            try:
                box = QMessageBox(QMessageBox.Critical, "Beklenmeyen hata",
                                  f"{exc_type.__name__}: {exc}\n\nAyrıntı openecu.log dosyasına yazıldı.")
                box.setDetailedText(text)
                box.exec()
            except Exception:  # noqa: BLE001
                pass
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def main():
    setup_logging()
    install_excepthook()
    # Windows görev çubuğunda "python/exe" yerine kendi simgemiz görünsün.
    if sys.platform == "win32":
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
        except Exception:
            pass
    # %125/%150 gibi kesirli Windows ölçeklerinde yuvarlama yapma: yazı ve
    # bileşenler orantılı kalır (aksi halde tam ekranda taşma/kayma olur).
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    # Net yazı: tam hinting + tam sayı piksel boyutu (QSS'teki font-size ile uyumlu)
    from PySide6.QtGui import QFont
    # Paketlenen DejaVu Sans'ı kaydet: QSS'teki "IBM Plex Sans/Segoe UI" yoksa her makinede
    # aynı (Türkçe karakter destekli) yazı tipi kullanılsın.
    try:
        import os
        from PySide6.QtGui import QFontDatabase
        from app.report import _bundled_font_dir
        for fname in ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf"):
            fpath = os.path.join(_bundled_font_dir(), fname)
            if os.path.exists(fpath):
                QFontDatabase.addApplicationFont(fpath)
    except Exception:  # noqa: BLE001  (yazı tipi yüklenemezse sistem yazı tipiyle devam)
        logging.getLogger(__name__).warning("Paketlenen yazı tipi yüklenemedi", exc_info=True)
    base_font = app.font()
    base_font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    base_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(base_font)
    # Tek örnek: iki kopya aynı audit/history/profil dosyalarına yazıp bozar.
    lock = QLockFile(data_path("openecu.lock"))
    lock.setStaleLockTime(15000)
    if not lock.tryLock(200):
        QMessageBox.warning(None, "Zaten çalışıyor",
                            "OpenECU başka bir pencerede açık. Aynı veri dosyalarını iki kopya "
                            "birlikte kullanamaz; lütfen açık olanı kullanın.")
        return 1
    app.setApplicationName("OpenECU M220")
    app.setWindowIcon(make_icon())
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.setWindowIcon(make_icon())
    window.show()
    rc = app.exec()
    lock.unlock()
    sys.exit(rc)


if __name__ == "__main__":
    main()
