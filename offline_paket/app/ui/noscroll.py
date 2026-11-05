"""Fare tekerleğiyle kazara değer değişimini engelleyen yardımcı.

Kaydırılabilir sayfalarda tekerlek bir spinbox/slider üzerinden geçerken değeri
değiştirir; sim giriş / sinyal değeri gibi alanlarda bu, ECU'ya istenmeyen bir
komut gitmesine yol açabilir. Odakta olmayan widget'ta tekerlek olayı yutulur
(sayfa kaymaya devam eder); tıklayıp odaklanınca tekerlek normal çalışır.
"""
from PySide6.QtCore import QEvent, QObject, Qt


class _WheelGuard(QObject):
    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return False


_guard = None


def no_wheel(*widgets):
    global _guard
    if _guard is None:
        _guard = _WheelGuard()
    for w in widgets:
        w.setFocusPolicy(Qt.StrongFocus)
        w.installEventFilter(_guard)
    return widgets[0] if len(widgets) == 1 else widgets
