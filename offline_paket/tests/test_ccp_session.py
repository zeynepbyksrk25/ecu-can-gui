"""CCP oturumu: arka plan okuma, ECU yok devre kesicisi, güç döngüsü sonrası otomatik yeniden bağlanma."""
import itertools
import os
import time

import can
import pytest

from app.can_worker import CanConnection
from app.ccp import protocol as ccp
from app.ccp import worker as cw
from app.ccp.simulator import CCPSlaveSimulator
from app.ccp.worker import CONNECTING, IDLE, LOST, ONLINE, CcpSession, EcuSilent

CRO, DTO = 0x6F9, 0x6F8
_ch = itertools.count()
ADDR = 0x2000


def wait_for(cond, timeout=5.0, step=0.02, pump=None):
    end = time.time() + timeout
    while time.time() < end:
        if pump:
            pump()
        if cond():
            return True
        time.sleep(step)
    return cond()


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(cw, "SHORT_TIMEOUT_S", 0.08)
    monkeypatch.setattr(cw, "LOST_PROBE_S", 0.15)
    monkeypatch.setattr(cw, "BACKOFF", (0.05, 0.1, 0.2))
    channel = f"ccp-session-{next(_ch)}"
    conn = CanConnection()
    conn.connect("virtual", channel, 500_000)
    ecu_bus = can.Bus(interface="virtual", channel=channel)
    ecu = CCPSlaveSimulator(ecu_bus, CRO, DTO)
    ecu.strict_session = True
    ecu.start()
    ecu.write_memory_bytes(ADDR, (1234).to_bytes(2, "big"))
    session = CcpSession(conn)
    yield session, ecu, conn
    session.stop(graceful=False)
    ecu.stop()
    ecu_bus.shutdown()
    conn.disconnect()


def read(session, size=2):
    return session.reader.read_memory(ADDR, size, 0)


def read_value(session):
    """Önbellekten bir değer gelene kadar dener (ilk tur beklenir)."""
    out = {}

    def attempt():
        try:
            out["v"] = int.from_bytes(read(session), "big")
            return True
        except ccp.CCPTimeoutError:
            return False
    return out["v"] if wait_for(attempt, 3.0) else None


def test_auto_connect_keeps_retrying_until_ecu_is_there(rig):
    session, ecu, _ = rig
    ecu.power_off()                                    # güç yeni geldi / ECU henüz hazır değil
    t0 = time.perf_counter()
    session.start(CRO, DTO, 0)
    assert time.perf_counter() - t0 < 0.2              # start() beklemez
    assert wait_for(lambda: session.attempts >= 3, 4.0)
    assert session.state == CONNECTING and "deneme" in session.info
    ecu.power_on()
    assert wait_for(lambda: session.state == ONLINE, 4.0)
    assert session.client is not None and "v2.1" in session.version


def test_reads_never_block_the_caller_even_when_ecu_is_silent(rig):
    session, ecu, _ = rig
    session.start(CRO, DTO, 0)
    assert wait_for(lambda: session.state == ONLINE)
    assert read_value(session) == 1234
    ecu.power_off()
    t0 = time.perf_counter()
    for _ in range(300):
        try:
            read(session)
        except ccp.CCPTimeoutError:
            pass
        time.sleep(0.002)
    assert time.perf_counter() - t0 < 1.5              # 300 okuma çağrısı: hiçbiri beklemedi (eskiden 1,5 sn × 300)
    assert wait_for(lambda: session.state == LOST, 3.0)
    t0 = time.perf_counter()
    with pytest.raises(EcuSilent):
        read(session)
    assert time.perf_counter() - t0 < 0.02


def test_power_cycle_reconnects_ccp_session_automatically(rig):
    session, ecu, _ = rig
    session.start(CRO, DTO, 0)
    assert wait_for(lambda: session.state == ONLINE)
    assert read_value(session) == 1234
    ecu.power_off()
    assert wait_for(lambda: session.state == LOST, 3.0)
    ecu.write_memory_bytes(ADDR, (4321).to_bytes(2, "big"))     # ECU açılırken değer değişti
    ecu.power_on()                                              # oturum unutuldu (strict)
    assert wait_for(lambda: session.state == ONLINE, 4.0)
    assert session.reconnects == 1
    assert read_value(session) == 4321                          # değerler kendiliğinden akıyor
    kinds = [e for e in session.poll_events() if e[0] == "log"]
    assert any("yeniden kuruldu" in e[2] for e in kinds)


def test_ecu_forgetting_the_session_while_online_is_detected_and_repaired(rig):
    session, ecu, _ = rig
    session.start(CRO, DTO, 0)
    assert wait_for(lambda: session.state == ONLINE)
    assert read_value(session) == 1234
    ecu.power_on()                       # ECU anlık sıfırlandı: hat hiç susmadı ama oturum gitti (ACCESS_DENIED)
    assert wait_for(lambda: session.state == LOST or session.reconnects >= 1, 3.0)
    assert wait_for(lambda: session.state == ONLINE and session.reconnects >= 1, 4.0)
    assert read_value(session) == 1234


def test_one_bad_address_does_not_drop_the_session(rig):
    session, ecu, _ = rig
    session.start(CRO, DTO, 0)
    assert wait_for(lambda: session.state == ONLINE)
    assert read_value(session) == 1234
    ecu.force_error_on[ccp.SHORT_UP] = ccp.RC_OUT_OF_RANGE      # tek adres hatası (oturum geçerli)
    for _ in range(10):
        try:
            read(session)
        except ccp.CCPError:
            pass
        except ccp.CCPTimeoutError:
            pass
        time.sleep(0.05)
    assert session.state == ONLINE


def test_guarded_client_fails_fast_when_ecu_is_gone_and_reports_timeouts(rig):
    session, ecu, _ = rig
    session.start(CRO, DTO, 0)
    assert wait_for(lambda: session.state == ONLINE)
    client = session.client
    client.write_memory(ADDR, b"\x00\x07")
    assert ecu.read_memory_bytes(ADDR, 2) == b"\x00\x07"
    ecu.power_off()
    # açık işlem de zaman aşımına uğrar ama devre kesici açılınca anında hata verir
    for _ in range(3):
        try:
            client.write_memory(ADDR, b"\x00\x08")
        except ccp.CCPTimeoutError:
            pass
    assert wait_for(lambda: session.state == LOST, 3.0)
    t0 = time.perf_counter()
    with pytest.raises(EcuSilent):
        client.write_memory(ADDR, b"\x00\x09")
    assert time.perf_counter() - t0 < 0.02
    assert client.test_connection() is False


def test_manual_stop_disconnects_and_does_not_auto_reconnect(rig):
    session, ecu, _ = rig
    session.start(CRO, DTO, 0)
    assert wait_for(lambda: session.state == ONLINE)
    session.stop(graceful=True)
    assert session.state == IDLE and session.client is None
    assert wait_for(lambda: not ecu._connected, 1.0)            # DISCONNECT gitti
    time.sleep(0.5)
    assert session.state == IDLE                                # kendiliğinden bağlanmadı


def test_unread_addresses_are_dropped_from_the_poll_list(rig, monkeypatch):
    monkeypatch.setattr(cw, "WANT_TTL_S", 0.3)
    session, ecu, _ = rig
    session.start(CRO, DTO, 0)
    assert wait_for(lambda: session.state == ONLINE)
    assert read_value(session) == 1234
    assert session.items == 1
    assert wait_for(lambda: session.items == 0, 2.0)


def test_dashboard_ticks_stay_fast_with_silent_ecu_and_recover(qapp, monkeypatch):
    """Ana Sayfa'nın 10 sinyalli tiki ECU sessizken de ms'de döner; ECU gelince değerler akar."""
    from app.ui.main_window import MainWindow
    from app.dashboard_config import SOURCE_A2L, Binding, DashboardConfig, SignalMap
    monkeypatch.setattr(cw, "SHORT_TIMEOUT_S", 0.08)
    monkeypatch.setattr(cw, "LOST_PROBE_S", 0.15)
    monkeypatch.setattr(cw, "BACKOFF", (0.05, 0.1, 0.2))
    data = os.path.join(os.path.dirname(__file__), "data")
    w = MainWindow()
    w.a2l_tab.db.load(os.path.join(data, "sample.a2l"))
    w._on_dashboard_sources_changed()
    channel = f"ccp-dash-{next(_ch)}"
    w._on_connect("virtual", channel, 500_000)
    ecu_bus = can.Bus(interface="virtual", channel=channel)
    ecu = CCPSlaveSimulator(ecu_bus, CRO, DTO)
    ecu.strict_session = True
    ecu.start()
    ecu.power_off()
    try:
        cfg = DashboardConfig()
        names = {"RPM": "N_RPM", "Ps3": "Tt2_raw", "FP": "FP_bar"}
        for k, n in names.items():
            cfg.sensors[k] = SignalMap(value=Binding(SOURCE_A2L, a2l_name=n))
        w.dashboard_tab.set_config(cfg)
        pump = lambda: (qapp.processEvents(), w._on_ccp_events())
        # otomatik bağlanma ECU yokken denemeye devam eder; arayüz hiç donmaz
        for _ in range(20):
            t0 = time.perf_counter()
            w._on_dashboard_tick(list(names.values()))
            assert time.perf_counter() - t0 < 0.05
            pump()
            time.sleep(0.02)
        assert w.ccp_session.state == CONNECTING and "bağlanıyor" in w.ccp_chip.text()
        assert "bağlanıyor" in w.dashboard_tab._reasons["RPM"].lower()
        # ECU geldi -> otomatik bağlandı, değerler akıyor
        ecu.write_memory_bytes(0x1000, (9040).to_bytes(2, "little"))
        ecu.power_on()
        assert wait_for(lambda: w.ccp_session.state == ONLINE, 5.0, pump=pump)
        assert wait_for(lambda: (w._on_dashboard_tick(list(names.values())), "RPM" in w.dashboard_tab._values)[1],
                        4.0, pump=pump)
        assert w.dashboard_tab._values["RPM"][0] == pytest.approx(4520.0)
        assert "çevrimiçi" in w.ccp_chip.text()
        # güç kesildi -> ECU YOK, arayüz hızlı; güç geldi -> kendiliğinden döner
        ecu.power_off()
        assert wait_for(lambda: w.ccp_session.state == LOST, 4.0, pump=pump)
        t0 = time.perf_counter()
        w._on_dashboard_tick(list(names.values()))
        assert time.perf_counter() - t0 < 0.05
        assert "ECU YOK" in w.ccp_chip.text()
        ecu.power_on()
        assert wait_for(lambda: w.ccp_session.state == ONLINE, 5.0, pump=pump)
        assert any("yeniden kuruldu" in e.message for e in w.event_log.entries)
    finally:
        w._on_disconnect()
        ecu.stop()
        ecu_bus.shutdown()
        w.close()


def test_stopped_thread_cannot_be_revived_by_restart(monkeypatch):
    """join zaman aşımına uğrayan eski iş parçacığının bayrağı start() ile SIFIRLANMAZ (zombi dirilmez)."""
    import threading
    from app.ccp import worker as w
    release = threading.Event()
    entered = threading.Event()

    class Conn:
        bus = object()
        recovering = False
        ccp_queue = None
        ccp_dto_id = None

    class SlowClient:
        timeout, retries, bus = 0.1, 0, None

        def __init__(self, *a, **k):
            pass

        def connect(self):
            entered.set()
            release.wait(5)             # takılmış bus yazması

        def get_ccp_version(self):
            return (2, 1)

    monkeypatch.setattr(w, "CCPClient", SlowClient)
    monkeypatch.setattr(threading.Thread, "join", lambda self, timeout=None: None)   # join zaman aşımı
    s = w.CcpSession(Conn())
    s.start(1, 2, 0)
    assert entered.wait(2)
    old_stop, old_thread = s._stop, s._thread
    s.stop(graceful=False)
    s.start(1, 2, 0)                    # yeniden başlat: eski iş parçacığı hâlâ connect() içinde
    assert old_stop.is_set() and s._stop is not old_stop
    release.set()
    s.stop(graceful=False)
    assert old_thread is not s._thread
