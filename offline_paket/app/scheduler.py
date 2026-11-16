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
    def __init__(self, get_bus, msg: can.Message, period_s: float, on_sent=None):
        super().__init__(daemon=True)
        self._get_bus = get_bus
        self._on_sent = on_sent
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
                if self._on_sent is not None:
                    try:
                        self._on_sent(msg)
                    except Exception:  # noqa: BLE001 - izleme/kayıt hatası gönderimi durdurmasın
                        pass
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
    def __init__(self, bus, on_sent=None):
        """``bus``: can.BusABC ya da güncel bus'ı döndüren çağrılabilir (bus yeniden açılınca
        görevler yeni bus'a kendiliğinden geçsin diye ikincisi önerilir). ``on_sent(msg)``: başarıyla
        gönderilen HER kare için (gönderen iş parçacığında) çağrılır; izleme tablosu / CSV kaydı içindir."""
        self._get_bus = bus if callable(bus) else (lambda: bus)
        self._on_sent = on_sent
        self._tasks: dict[str, _Task] = {}

    def start(self, row_id: str, arbitration_id: int, data: bytes,
              extended: bool, period_ms: int):
        """Verilen satır için periyodik gönderimi başlatır. Aynı row_id zaten çalışıyorsa önce
        durdurur (data/periyot güncellemesi için)."""
        if not isinstance(period_ms, int) or not 1 <= period_ms <= 60_000:
            raise ValueError(f"Periyot 1-60000 ms arasında olmalı (verilen: {period_ms!r}).")
        if len(data) > 8:
            raise ValueError("Klasik CAN çerçevesi en fazla 8 bayt taşır.")
        if not 0 <= arbitration_id <= (0x1FFFFFFF if extended else 0x7FF):
            raise ValueError(f"CAN ID aralık dışı: 0x{arbitration_id:X}")
        self.stop(row_id)
        msg = can.Message(arbitration_id=arbitration_id, data=data, is_extended_id=extended)
        task = _Task(self._get_bus, msg, period_ms / 1000.0, on_sent=self._on_sent)
        self._tasks[row_id] = task
        task.start()

    def update_data(self, row_id: str, data: bytes):
        task = self._tasks.get(row_id)
        if task is not None:
            task.update_data(data)

    def stop(self, row_id: str):
        task = self._tasks.pop(row_id, None)
        if task is not None:
            try:
                task.stop()
            except Exception:  # noqa: BLE001 - bus kapanmış olabilir; kayıt zaten silindi
                pass

    def stop_all(self):
        for row_id in list(self._tasks.keys()):
            self.stop(row_id)

    def is_running(self, row_id: str) -> bool:
        return row_id in self._tasks

    def stats(self, row_id: str) -> dict:
        t = self._tasks.get(row_id)
        return {} if t is None else {"sent": t.sent, "errors": t.errors, "last_error": t.last_error}
