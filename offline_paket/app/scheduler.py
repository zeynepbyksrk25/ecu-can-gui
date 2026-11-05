"""Birden fazla periyodik mesajı, her biri kendi periyoduyla (örn. motor devri 10 ms, batarya
verisi 100 ms) aynı anda ve birbirinden bağımsız yöneten modül.

Her satır kendi iş parçacığında çalışır. ÖNEMLİ: gönderim hatası (TX kuyruğu dolu, bus-off,
adaptör geçici yok...) görevi ÖLDÜRMEZ — hata sayılır ve bir sonraki periyotta yeniden denenir;
böylece ECU kapanıp açıldığında ya da hat toparlandığında gönderim kendiliğinden sürer.
(Eskiden python-can ``send_periodic`` kullanılıyordu; ilk hatada görevi kalıcı durduruyordu.)
"""

import threading
import time

import can


class _Task(threading.Thread):
    def __init__(self, get_bus, msg: can.Message, period_s: float):
        super().__init__(daemon=True)
        self._get_bus = get_bus
        self.msg = msg
        self.period_s = period_s
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self.sent = 0
        self.errors = 0
        self.last_error: str | None = None

    def update_data(self, data: bytes):
        with self._lock:
            self.msg = can.Message(arbitration_id=self.msg.arbitration_id, data=data,
                                   is_extended_id=self.msg.is_extended_id)

    def stop(self):
        self._stop_event.set()

    def run(self):
        next_t = time.monotonic()
        while not self._stop_event.is_set():
            try:
                bus = self._get_bus()
                if bus is None:
                    raise RuntimeError("Bağlantı yok")
                with self._lock:
                    msg = self.msg
                bus.send(msg)
                self.sent += 1
                self.last_error = None
            except Exception as exc:  # hat toparlanırken gönderim hataları beklenir; görev sürer
                self.errors += 1
                self.last_error = str(exc)
            next_t += self.period_s
            delay = next_t - time.monotonic()
            if delay < -1.0:            # uzun kesintiden sonra patlama (burst) yapma
                next_t = time.monotonic()
                delay = 0.0
            if self._stop_event.wait(max(0.0, delay)):
                break


class PeriodicManager:
    def __init__(self, bus):
        """``bus``: can.BusABC ya da güncel bus'ı döndüren çağrılabilir (bus yeniden açılınca
        görevler yeni bus'a kendiliğinden geçsin diye ikincisi önerilir)."""
        self._get_bus = bus if callable(bus) else (lambda: bus)
        self._tasks: dict[str, _Task] = {}

    def start(self, row_id: str, arbitration_id: int, data: bytes,
              extended: bool, period_ms: int):
        """Verilen satır için periyodik gönderimi başlatır. Aynı row_id zaten çalışıyorsa önce
        durdurur (data/periyot güncellemesi için)."""
        self.stop(row_id)
        msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=extended)
        task = _Task(self._get_bus, msg, period_ms / 1000.0)
        self._tasks[row_id] = task
        task.start()

    def update_data(self, row_id: str, data: bytes):
        task = self._tasks.get(row_id)
        if task is not None:
            task.update_data(data)

    def stop(self, row_id: str):
        task = self._tasks.pop(row_id, None)
        if task is not None:
            task.stop()

    def stop_all(self):
        for row_id in list(self._tasks.keys()):
            self.stop(row_id)

    def is_running(self, row_id: str) -> bool:
        return row_id in self._tasks

    def stats(self, row_id: str) -> dict:
        t = self._tasks.get(row_id)
        return {} if t is None else {"sent": t.sent, "errors": t.errors, "last_error": t.last_error}
