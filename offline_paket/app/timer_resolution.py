"""Windows sistem zamanlayıcı çözünürlüğünü 1 ms'ye çeker.

Windows'ta ``threading.Event.wait`` / ``time.sleep`` varsayılan olarak ~15,6 ms'lik adımlarla uyanır; bu
yüzden 10 ms'lik periyodik CAN gönderimi (motor devri vb.) fiilen ~15,6 ms'e yuvarlanır. ``timeBeginPeriod(1)``
süreç boyunca bu adımı 1 ms'ye indirir. Diğer platformlarda hiçbir şey yapmaz.
"""
from __future__ import annotations

import atexit
import logging
import sys

log = logging.getLogger(__name__)
_active = False


def enable_high_resolution_timer(period_ms: int = 1) -> bool:
    """True: çözünürlük artırıldı. Windows dışında ya da başarısızsa False (uygulama yine çalışır)."""
    global _active
    if _active:
        return True
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        winmm = ctypes.windll.winmm
        if winmm.timeBeginPeriod(period_ms) != 0:           # TIMERR_NOERROR = 0
            log.warning("timeBeginPeriod(%d) başarısız; zamanlayıcı çözünürlüğü varsayılan", period_ms)
            return False
        atexit.register(winmm.timeEndPeriod, period_ms)
    except Exception:  # noqa: BLE001
        log.warning("Zamanlayıcı çözünürlüğü ayarlanamadı", exc_info=True)
        return False
    _active = True
    log.info("Windows zamanlayıcı çözünürlüğü %d ms", period_ms)
    return True
