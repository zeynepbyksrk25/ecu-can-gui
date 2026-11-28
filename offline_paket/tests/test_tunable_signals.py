"""Ayarlanabilir (CHARACTERISTIC/VALUE) clbc_* parametreleri grafik, trend, çalışma alanı, performansta."""
import itertools
import os
import struct
import time

import can
import pytest

from app.a2l import A2LDatabase
from app.ccp.client import CCPClient
from app.ccp.simulator import CCPSlaveSimulator

DATA = os.path.join(os.path.dirname(__file__), "data")
_ch = itertools.count()


@pytest.fixture(scope="module")
def summary():
    db = A2LDatabase()
    return db.load(os.path.join(DATA, "sample.a2l"))


def test_summary_exposes_tunable_scalars_and_measurements_win_name_clashes(summary):
    tun = {c.name for c in summary.tunable_scalars()}
    assert {"clbc_Fuel_pump_gain", "clbc_Temp_limit"} <= tun
    assert tun.isdisjoint({m.name for m in summary.measurements})
    names = {o.name for o in summary.readable()}
    assert "N_RPM" in names and "clbc_Fuel_pump_gain" in names
    by = summary.readable_by_name()
    assert by["clbc_Fuel_pump_gain"].address == 0x1100 and by["clbc_Fuel_pump_gain"].datatype == "FLOAT32_IEEE"
    assert by["clbc_Temp_limit"].byte_order == "MSB_LAST"           # MOD_COMMON'dan


def test_graph_signal_dialog_lists_tunables_in_their_own_group(qapp):
    from app.ui.graph_signal_dialog import GraphSignalDialog
    d = GraphSignalDialog(["RPM"], ["N_RPM"], ["m:clbc_Fuel_pump_gain"], tunable_names=["clbc_Fuel_pump_gain", "clbc_Temp_limit"])
    assert "Ayarlanabilir" in d._tun_root.text(0) and d._tun_root.childCount() == 2
    assert d.selected_ids() == ["m:clbc_Fuel_pump_gain"]
    d.search.setText("temp")
    hidden = [d._tun_root.child(i).isHidden() for i in range(2)]
    assert hidden == [True, False]


def test_signal_sources_include_tunables(qapp, summary):
    from app.sim_interface import list_sources

    keys = {s.key for s in list_sources(None, summary)}
    assert "a2l:clbc_Fuel_pump_gain" in keys and "a2l:N_RPM" in keys


@pytest.fixture
def win(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
    w._on_dashboard_sources_changed()
    w._sync_dashboard_measurements()
    channel = f"tun-{next(_ch)}"
    a = can.Bus(interface="virtual", channel=channel)
    b = can.Bus(interface="virtual", channel=channel)
    ecu = CCPSlaveSimulator(a, 0x6F9, 0x6F8)
    ecu.start()
    client = CCPClient(b, 0x6F9, 0x6F8, timeout=0.3, retries=1)
    client.start_listening()
    client.connect()
    w.ccp_client = client
    yield w, ecu
    w.ccp_session.stop(graceful=False)
    client.stop_listening()
    ecu.stop()
    a.shutdown()
    b.shutdown()
    w.close()


def test_trend_plots_a_tunable_parameter_and_shows_the_step_when_it_changes(win):
    w, ecu = win
    dt = w.dashboard_tab
    addr = w.a2l_tab.db.summary.readable_by_name()["clbc_Fuel_pump_gain"].address
    assert "clbc_Fuel_pump_gain" in dt._tunable_names
    dt.set_graph_signals(["g:RPM", "m:clbc_Fuel_pump_gain"])
    ecu.write_memory_bytes(addr, struct.pack("<f", 2.0))
    series = dt.trend._series["m:clbc_Fuel_pump_gain"]

    def tick_until(cond, timeout=5.0):
        end = time.time() + timeout
        while time.time() < end:
            w._on_dashboard_tick(["clbc_Fuel_pump_gain"])
            if cond():
                return True
            time.sleep(0.05)
        return False

    assert tick_until(lambda: 2.0 in series.v)
    ecu.write_memory_bytes(addr, struct.pack("<f", 3.5))        # Kalibrasyon sayfasından değiştirilmiş gibi
    assert tick_until(lambda: 3.5 in series.v)
    assert series.unit == "bar"                                 # birim A2L COMPU_METHOD'dan
    assert dt.graph_measurement_names() == ["clbc_Fuel_pump_gain"]


def test_scope_measurement_round_reads_tunable_parameters(win):
    """Worksheets Scope, ayarlanabilir parametreleri CCP ile okuyup hub'a yazar (eski Çalışma Alanı'nın yerine)."""
    w, ecu = win
    info = w.a2l_tab.db.summary.readable_by_name()["clbc_Temp_limit"]
    ecu.write_memory_bytes(info.address, (4000).to_bytes(2, "little"))
    w.modas_tab.set_summary(w.a2l_tab.db.summary)
    w.modas_tab.add_scope(["clbc_Temp_limit"])
    got = []
    w.modas_tab.push_sample = lambda name, v: got.append((name, v))
    end = time.time() + 5
    while time.time() < end and not got:
        w._modas_scope_sample("clbc_Temp_limit")
        time.sleep(0.05)
    assert got and got[0][0] == "clbc_Temp_limit" and got[0][1] == pytest.approx(2000.0)   # LINEAR 0.5x

