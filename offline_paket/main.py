import ctypes
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from app.icon import make_icon
from app.theme import APP_QSS
from app.ui.main_window import MainWindow

APP_USER_MODEL_ID = "OpenECU.M220.TestKalibrasyon"


def main():
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
    app.setApplicationName("OpenECU M220")
    app.setWindowIcon(make_icon())
    app.setStyleSheet(APP_QSS)
    window = MainWindow()
    window.setWindowIcon(make_icon())
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
