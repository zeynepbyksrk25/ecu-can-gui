"""Birden fazla periyodik mesajı, her biri kendi periyoduyla (örn. motor
devri 10 ms, batarya verisi 100 ms) aynı anda ve birbirinden bağımsız
yöneten modül.

python-can'in send_periodic() fonksiyonu, arka planda kendi thread'ini
yöneten bir CyclicSendTask döndürür; bu sayede periyotlar birbirini
bloklamaz ve ayrıca QTimer yönetmemize gerek kalmaz.
"""

import can


class PeriodicManager:
    def __init__(self, bus: can.BusABC):
        self.bus = bus
        self._tasks: dict[str, can.broadcastmanager.CyclicSendTaskABC] = {}

    def start(self, row_id: str, arbitration_id: int, data: bytes,
              extended: bool, period_ms: int):
        """Verilen satır için periyodik gönderimi başlatır. Aynı row_id
        zaten çalışıyorsa önce durdurur (data/periyot güncellemesi için)."""
        self.stop(row_id)
        msg = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=extended,
        )
        task = self.bus.send_periodic(msg, period_ms / 1000.0)
        self._tasks[row_id] = task

    def stop(self, row_id: str):
        task = self._tasks.pop(row_id, None)
        if task is not None:
            task.stop()

    def stop_all(self):
        for row_id in list(self._tasks.keys()):
            self.stop(row_id)

    def is_running(self, row_id: str) -> bool:
        return row_id in self._tasks
