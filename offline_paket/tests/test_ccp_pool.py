import threading
import time
from types import SimpleNamespace

import can
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from app.ccp.client import CCPClient
from app.ccp.simulator import CCPSlaveSimulator
from app.ccp_poll import CcpReadPool

CRO, DTO = 0x110, 0x111


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def pump(cond, timeout=3.0):
    end = time.time() + timeout
    while time.time() < end and not cond():
        QCoreApplication.processEvents()
        time.sleep(0.005)
    return cond()


@pytest.fixture
def rig(qapp):
    a = can.Bus(interface="virtual", channel="pool")
    b = can.Bus(interface="virtual", channel="pool")
    sim = CCPSlaveSimulator(b, CRO, DTO)
    sim.start()
    cli = CCPClient(a, CRO, DTO, timeout=0.1, retries=0)
    cli.connect()
    pool = CcpReadPool()
    yield pool, cli, sim
    pool.shutdown()
    try:
        cli.disconnect()
    except Exception:
        pass            # test ECU'yu kasten susturmuş olabilir
    sim.stop()
    a.shutdown()
    b.shutdown()


def meas(addr):
    return SimpleNamespace(datatype="UWORD", address=addr, address_extension=0,
                           byte_order="MSB_FIRST", compu_method=None)


def test_values_arrive_on_ui_thread(rig):
    pool, cli, sim = rig
    sim.write_memory_bytes(0x100, (1234).to_bytes(2, "big"))
    got = []
    tid = threading.get_ident()
    assert pool.submit("k", cli, [("A", meas(0x100))], lambda t, v: got.append((t, v, threading.get_ident())))
    assert pump(lambda: got)
    assert got[0][:2] == ("A", 1234) and got[0][2] == tid


def test_timeout_backs_off_and_does_not_block_ui(rig):
    pool, cli, sim = rig
    sim.stop()                                    # ECU sustu
    flags, errs = [], []
    pool.unresponsive_changed.connect(flags.append)
    t0 = time.time()
    assert pool.submit("k", cli, [("A", meas(0x100)), ("B", meas(0x102))], lambda t, v: None,
                       lambda t, e: errs.append(t))
    assert time.time() - t0 < 0.05                # submit bloklamaz
    assert pump(lambda: flags)
    assert flags == [True] and errs == ["A"]      # 1. timeout'ta durdu, B denenmedi
    assert not pool.submit("k", cli, [("A", meas(0x100))], lambda t, v: None)   # backoff
    pool.reset()
    assert pool.submit("k", cli, [("A", meas(0x100))], lambda t, v: None)


def test_one_inflight_per_key(rig):
    pool, cli, sim = rig
    sim.stop()
    assert pool.submit("k", cli, [("A", meas(0x100))], lambda t, v: None)
    assert not pool.submit("k", cli, [("A", meas(0x100))], lambda t, v: None)
