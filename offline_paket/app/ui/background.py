"""Uzun süren, Qt'ye dokunmayan işleri (dosya ayrıştırma vb.) arayüzü dondurmadan çalıştırma.

``run_with_progress`` işi bir arka plan iş parçacığında yürütür; iş bitene kadar belirsiz (indeterminate)
bir ilerleme penceresi gösterir ve olay döngüsünü döndürür. Çağıran için eşzamanlıdır: işin sonucunu döner
ya da hatasını aynen yükseltir. Pencere modal olduğu için kullanıcı bu sırada başka bir işlem başlatamaz;
CAN alımı, periyodik gönderim ve zamanlayıcılar ise çalışmaya devam eder.
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import QProgressDialog

INLINE_S = 0.05      # bundan kısa süren işlerde pencere hiç açılmaz


def run_with_progress(parent, text: str, fn, inline_s: float = INLINE_S):
    box: dict = {}

    def run():
        try:
            box["result"] = fn()
        except BaseException as exc:  # noqa: BLE001 - arayüz iş parçacığında yeniden yükseltilir
            box["error"] = exc

    thread = threading.Thread(target=run, name="bg-job", daemon=True)
    thread.start()
    thread.join(inline_s)
    if thread.is_alive():
        dialog = QProgressDialog(text, "", 0, 0, parent)
        dialog.setWindowTitle("Lütfen bekleyin")
        dialog.setCancelButton(None)                  # iş yarıda kesilemez
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setWindowFlag(Qt.WindowCloseButtonHint, False)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        loop = QEventLoop()
        timer = QTimer()
        timer.setInterval(15)
        timer.timeout.connect(lambda: loop.quit() if not thread.is_alive() else None)
        dialog.show()
        timer.start()
        try:
            if thread.is_alive():
                loop.exec()
        finally:
            timer.stop()
            dialog.close()
            dialog.deleteLater()
    if "error" in box:
        raise box["error"]
    return box.get("result")
