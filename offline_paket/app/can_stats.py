"""CAN trafiği istatistikleri: toplam RX/TX sayacı, RX hızı (msg/s) ve
TAHMİNİ bus load (%). Donanımdan doğrudan bus-load okuyan tek bir
arayüz standardı olmadığı için (SRS de "should provide an ESTIMATED
bus load" diyor), burada klasik CAN 2.0 çerçeve boyutuna dayalı bir
yaklaşık hesap kullanılır: kesin değil, kabaca bir gösterge amaçlıdır.

Yaklaşık çerçeve boyutu (bit stuffing için ~%20 pay dahil):
  standart ID  : ~47 bit sabit + 8*DLC veri biti
  extended ID  : ~67 bit sabit + 8*DLC veri biti
"""

import collections
import time

STANDARD_OVERHEAD_BITS = 47
EXTENDED_OVERHEAD_BITS = 67
STUFFING_MARGIN = 1.20
WINDOW_SECONDS = 1.0


def estimate_frame_bits(dlc: int, extended: bool) -> float:
    overhead = EXTENDED_OVERHEAD_BITS if extended else STANDARD_OVERHEAD_BITS
    return (overhead + 8 * dlc) * STUFFING_MARGIN


class CanStats:
    def __init__(self):
        self.total_rx = 0
        self.total_tx = 0
        self.bitrate: int | None = None
        self._rx_window: collections.deque = collections.deque()  # (t, bits)

    def reset(self):
        self.total_rx = 0
        self.total_tx = 0
        self._rx_window.clear()

    def set_bitrate(self, bitrate: int | None):
        self.bitrate = bitrate

    def record_rx(self, dlc: int, extended: bool, timestamp: float | None = None):
        self.total_rx += 1
        t = timestamp if timestamp is not None else time.time()
        self._rx_window.append((t, estimate_frame_bits(dlc, extended)))
        self._trim(t)

    def record_tx(self):
        self.total_tx += 1

    def _trim(self, now: float):
        while self._rx_window and now - self._rx_window[0][0] > WINDOW_SECONDS:
            self._rx_window.popleft()

    def rx_rate(self) -> float:
        """Son 1 saniyedeki RX mesaj hızı (msg/s)."""
        if not self._rx_window:
            return 0.0
        self._trim(time.time())
        if not self._rx_window:
            return 0.0
        span = max(time.time() - self._rx_window[0][0], 0.001)
        return len(self._rx_window) / span

    def bus_load_percent(self) -> float | None:
        """Son 1 saniyedeki TAHMİNİ bus load (%). Bitrate bilinmiyorsa None."""
        if not self.bitrate:
            return None
        self._trim(time.time())
        if not self._rx_window:
            return 0.0
        total_bits = sum(bits for _, bits in self._rx_window)
        span = max(time.time() - self._rx_window[0][0], WINDOW_SECONDS)
        return min((total_bits / span) / self.bitrate * 100.0, 100.0)
