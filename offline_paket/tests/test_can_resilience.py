"""Güç kesilip gelince CAN katmanının toparlanması (sahte PCAN bus ile)."""
import queue
import time

import can
import pytest

from app import can_worker as cw
from app.can_worker import BusRecovering, CanConnection
from app.scheduler import PeriodicManager

BUSOFF = 0x10


class FakeBus:
    created: list = []

    def __init__(self, **kw):
        self.kw = kw
        self.status_code = 0
        self.resets = 0
        self.sent: list = []
        self.rx: "queue.Queue" = queue.Queue()
        self.fail_send = False
        self.reset_fixes = False
        self.closed = False
        FakeBus.created.append(self)

    def recv(self, timeout=None):
        try:
            return self.rx.get(timeout=min(timeout or 0.05, 0.05))
        except queue.Empty:
            return None

    def send(self, msg, timeout=None):
        if self.fail_send or self.status_code & BUSOFF:
            raise can.CanOperationError("TX kuyruğu dolu / bus-off")
        self.sent.append(msg)

    def status(self):
        return self.status_code

    def status_string(self):
        return "BUSOFF" if self.status_code & BUSOFF else "OK"

    def reset(self):
        self.resets += 1
        if self.reset_fixes:
            self.status_code = 0
        return True

    def shutdown(self):
        self.closed = True


@pytest.fixture
def conn(monkeypatch):
    FakeBus.created = []
    monkeypatch.setattr(cw, "SILENT_S", 0.05)
    monkeypatch.setattr(cw, "RESET_INTERVAL_S", 0.0)
    monkeypatch.setattr(cw, "RECOVERY_PROBE_S", 0.2)
    c = CanConnection(bus_factory=FakeBus)
    c.connect("pcan", "PCAN_USBBUS1", 500_000)
    yield c
    c.disconnect()


def _msg(i=0x100):
    return can.Message(arbitration_id=i, data=b"\x01", is_extended_id=False)


def test_pcan_is_opened_with_driver_auto_reset_but_virtual_is_not():
    FakeBus.created = []
    c = CanConnection(bus_factory=FakeBus)
    c.connect("pcan", "PCAN_USBBUS1", 500_000)
    c.disconnect()
    c2 = CanConnection(bus_factory=FakeBus)
    c2.connect("virtual", "x", 500_000)
    c2.disconnect()
    assert FakeBus.created[0].kw["auto_reset"] is True
    assert "auto_reset" not in FakeBus.created[1].kw


def test_busoff_and_silence_trigger_reset_and_recovery_clears(conn):
    bus = conn.bus
    bus.status_code = BUSOFF
    time.sleep(0.08)
    events = conn.watchdog()
    assert bus.resets == 1 and conn.recovering
    assert any("0x10" in e for e in events) and any("reset()" in e for e in events)
    bus.reset_fixes = True
    conn.watchdog()                      # 2. deneme: reset hatayı giderir
    bus.rx.put(_msg())
    time.sleep(0.15)                     # ECU geri geldi, mesaj alındı
    conn.watchdog()
    assert not conn.recovering
    conn.send(0x200, b"\x01", False)     # tam hızda gönderim
    conn.send(0x200, b"\x02", False)
    assert len(bus.sent) == 2


def test_sends_are_throttled_while_recovering_but_not_dropped_forever(conn):
    conn.bus.status_code = BUSOFF
    time.sleep(0.08)
    conn.watchdog()
    conn.bus.status_code = 0             # reset sonrası sürücü hatayı bıraktı ama hat hâlâ sessiz
    conn.recovering = True
    conn.send(0x1, b"\x00", False)       # ilk kare (yoklama) geçer
    with pytest.raises(BusRecovering):
        conn.send(0x1, b"\x00", False)   # hemen ardından gelen bekletilir
    time.sleep(0.25)
    conn.send(0x1, b"\x00", False)       # sonraki yoklama süresinde yine geçer


def test_reopens_adapter_when_reset_does_not_help(conn):
    first = conn.bus
    reopened = []
    conn.on_reopen.append(lambda: reopened.append(conn.bus))
    first.status_code = BUSOFF           # reset hiçbir şeyi düzeltmiyor
    time.sleep(0.08)
    for _ in range(cw.MAX_RESETS_BEFORE_REOPEN + 1):
        conn.watchdog()
    assert first.resets == cw.MAX_RESETS_BEFORE_REOPEN
    assert first.closed and conn.bus is not first and conn.reopen_count == 1
    assert reopened == [conn.bus] and conn.bus.status_code == 0     # temiz yeni bus
    assert FakeBus.created[1].kw == FakeBus.created[0].kw            # aynı parametreler


def test_status_code_transitions_are_reported_for_diagnostics(conn):
    assert conn.watchdog() == []                         # temiz başlangıç
    conn.bus.status_code = BUSOFF
    time.sleep(0.08)
    assert any("durum kodu 0x10" in e for e in conn.watchdog())
    conn.bus.status_code = 0
    assert any("durum kodu 0x0" in e for e in conn.watchdog())


def test_silent_for_tracks_last_rx(conn):
    conn.bus.rx.put(_msg())
    time.sleep(0.3)
    assert conn.silent_for() >= 0.2
    conn.bus.rx.put(_msg())
    time.sleep(0.2)
    assert conn.silent_for() < 0.25


def test_periodic_task_survives_bus_errors_and_resumes():
    bus = FakeBus()
    pm = PeriodicManager(lambda: bus)
    bus.fail_send = True
    pm.start("r1", 0x300, b"\x01\x02", False, 10)
    time.sleep(0.12)
    st = pm.stats("r1")
    assert pm.is_running("r1") and st["errors"] >= 3 and st["sent"] == 0
    bus.fail_send = False                # ECU/hat geri geldi
    time.sleep(0.12)
    assert pm.stats("r1")["sent"] >= 3
    pm.update_data("r1", b"\x09")
    time.sleep(0.05)
    assert bus.sent[-1].data == b"\x09"
    pm.stop_all()


def test_periodic_task_follows_a_reopened_bus():
    holder = {"bus": FakeBus()}
    pm = PeriodicManager(lambda: holder["bus"])
    pm.start("r", 0x1, b"\x00", False, 10)
    time.sleep(0.05)
    new = FakeBus()
    holder["bus"] = new
    time.sleep(0.08)
    assert new.sent
    pm.stop_all()


def test_tx_scheduler_keeps_running_after_a_failure(qapp):
    import os
    from app.control_panel import TxScheduler
    from app.dbc import DbcDatabase
    dbc = DbcDatabase()
    dbc.load(os.path.join(os.path.dirname(__file__), "data", "sample.dbc"))
    ok = {"v": True}
    sent = []

    def send(i, d, e):
        if not ok["v"]:
            raise can.CanOperationError("bus-off")
        sent.append(i)

    ts = TxScheduler(dbc, send)
    failed, recovered = [], []
    ts.failed.connect(lambda m, e: failed.append(m))
    ts.recovered.connect(lambda m: recovered.append(m))
    ts.set_values("AIRCRAFT", {"altitude": 8.0})
    assert ts.is_running("AIRCRAFT")
    ok["v"] = False
    for _ in range(5):
        ts._tick("AIRCRAFT")
    assert ts.is_running("AIRCRAFT") and failed == ["AIRCRAFT"] and ts.errors == 5   # bir kez bildirildi
    ok["v"] = True
    ts._tick("AIRCRAFT")
    assert recovered == ["AIRCRAFT"] and sent
    ts.stop_all()


def test_main_window_recovers_bus_and_shows_silence(qapp, monkeypatch):
    from app.ui.main_window import MainWindow
    FakeBus.created = []
    monkeypatch.setattr(cw, "SILENT_S", 0.05)
    monkeypatch.setattr(cw, "RESET_INTERVAL_S", 0.0)
    w = MainWindow()
    w.connection._bus_factory = FakeBus
    w._on_connect("pcan", "PCAN_USBBUS1", 500_000)
    bus = w.connection.bus
    # 1) ECU kapandı, hat sessiz ama sürücü sağlıklı -> "Hat sessiz" uyarısı
    w.connection.last_rx_mono -= 10
    w._check_connection_health()
    assert "Hat sessiz" in w.connection_tab.health_label.text()
    # 2) bus-off + sessizlik -> otomatik reset ve olay günlüğü
    bus.status_code = BUSOFF
    time.sleep(0.08)
    w._check_connection_health()
    assert bus.resets >= 1
    assert "kurtarılıyor" in w.connection_tab.health_label.text()
    assert any("Bus-off kurtarma" in e.message for e in w.event_log.entries)
    w._on_disconnect()
    w.close()
