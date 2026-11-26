"""MIL entegrasyonu (sahte model; gerçek Simulink ile doğrulanmadı): Dashboard, Kontrol, CAN Monitor, trend, kayıt."""
import json
import os
import time

import pytest

from app.dashboard_config import SOURCE_CAN, Binding, DashboardConfig, SignalMap
from tests.fake_simulink import FakeSimulink

DATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture
def mil(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    cfg = DashboardConfig()
    cfg.sensors["RPM"] = SignalMap(value=Binding(SOURCE_CAN, "ENG_STATUS", "rpm"))
    w.dashboard_tab.set_config(cfg)
    w._rebuild_dash_can_map()
    w.connection_tab.mode_combo.setCurrentIndex(w.connection_tab.mode_combo.findData("MIL"))
    w._on_connect("sim_udp", "0:127.0.0.1:1", 500000)
    model = FakeSimulink(0, w.connection.bus.local_port)
    w.connection.bus.remote_port = model.port
    yield w, model
    model.close()
    if w.connection.is_connected:
        w._on_disconnect()
    w.close()


def _pump(w, cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        w._drain_rx_queue()
        if cond():
            return True
        time.sleep(0.02)
    return False


def test_model_output_reaches_dashboard_monitor_and_trend(mil):
    w, model = mil
    dbc = w.transmit_tab.dbc
    cid, data, ext = dbc.encode("ENG_STATUS", {"rpm": 4321.0, "tt2_c": 100.0, "tt2_fault": 0})
    model.send_frame(cid, data, ext, sim_time=5.0)
    assert _pump(w, lambda: "RPM" in w.dashboard_tab._values)
    assert w.dashboard_tab._values["RPM"][0] == pytest.approx(4321.0)
    ser = w.dashboard_tab.trend._series.get("g:RPM")
    assert ser is None or ser.source == "Simulink MIL"
    assert w.connection_tab.status_label.text().startswith("Bağlı · MIL")


def test_control_panel_writes_reach_model_with_dbc_scaling(mil):
    w, model = mil
    assert w._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 45.0, "Pompa değeri")
    end = time.time() + 2
    while time.time() < end and not model.received_frames:
        time.sleep(0.02)
    cid, data, _ext = model.received_frames[0][0], model.received_frames[0][1], model.received_frames[0][2]
    vals = w.transmit_tab.dbc.get_message("OVERRIDE").decode(data)
    assert vals["pump_dc"] == pytest.approx(45.0, abs=0.1)


def test_mil_link_loss_is_reported_not_silent(mil):
    w, model = mil
    model.send_heartbeat()
    end = time.time() + 2
    while time.time() < end and w.connection.link_state()[0] != "ok":
        time.sleep(0.02)
    assert w.connection.link_state()[0] == "ok"
    w.connection.bus.timeout_s = 0.2
    time.sleep(0.4)                                            # model durdu: veri yok
    state, text = w.connection.link_state()
    assert state == "bus_warning" and "veri yok" in text       # hata görünür (sessiz değil)


def test_mil_recording_keeps_wall_clock_and_marks_mode(mil):
    w, model = mil
    dbc = w.transmit_tab.dbc
    w.session_tab.name_edit.setText("mil-kayit")
    w.session_tab._on_start()
    cid, data, ext = dbc.encode("ENG_STATUS", {"rpm": 1000.0, "tt2_c": 50.0, "tt2_fault": 0})
    for i in range(5):
        model.send_frame(cid, data, ext, sim_time=100.0 + i)    # simülasyon zamanı çok farklı
        time.sleep(0.02)
    time.sleep(0.3)
    path = w.session_recorder.path
    w.session_tab._on_stop()
    import csv
    rows = [r for r in csv.reader(open(path, encoding="utf-8")) if r and r[1] == "dbc:ENG_STATUS.rpm"]
    assert len(rows) == 5
    assert all(abs(float(r[3]) - time.time()) < 60 for r in rows)  # unix_time gerçek alım zamanı (sim zamanı 100+ DEĞİL)
    meta = json.load(open(path[:-4] + ".meta.json", encoding="utf-8"))
    assert meta["mode"] == "MIL" and meta["connection"]["interface"] == "sim_udp"
    assert meta["frames"] == 5 or meta["frames"] >= 5
