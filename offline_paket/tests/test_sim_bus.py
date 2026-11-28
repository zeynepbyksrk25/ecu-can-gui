"""MIL UDP CAN backend (sahte model ile; GERÇEK Simulink ile doğrulanmadı)."""
from tests.qt_helpers import dispose
import os
import time

import can
import pytest

from app import sim_protocol as proto
from app.dbc import DbcDatabase
from app.sim_bus import SimulinkUdpBus, parse_channel
from tests.fake_simulink import FakeSimulink

DATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture
def pair():
    bus = SimulinkUdpBus(channel="0:127.0.0.1:1", timeout_s=0.4, heartbeat=False)   # port 0: sistem atar
    model = FakeSimulink(0, bus.local_port)
    bus.remote_port = model.port
    yield bus, model
    bus.shutdown()
    model.close()


def _wait(cond, t=2.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_parse_channel():
    assert parse_channel("") == (25001, "127.0.0.1", 25000)
    assert parse_channel("1:h:2") == (1, "h", 2) and parse_channel("5:6") == (5, "127.0.0.1", 6)
    with pytest.raises(ValueError):
        parse_channel("x:y:z")


def test_dbc_signals_roundtrip_both_directions(pair):
    bus, model = pair
    dbc = DbcDatabase()
    dbc.load(os.path.join(DATA, "sample.dbc"))
    cid, data, ext = dbc.encode("ENG_STATUS", {"rpm": 3456.0, "tt2_c": 123.5, "tt2_fault": 0})
    model.send_frame(cid, data, ext)
    msg = bus.recv(timeout=2.0)
    assert msg is not None and msg.arbitration_id == cid
    dec = dbc.get_message_by_frame_id(msg.arbitration_id).decode(bytes(msg.data))
    assert dec["rpm"] == pytest.approx(3456.0) and dec["tt2_c"] == pytest.approx(123.5)
    cid2, data2, ext2 = dbc.encode("OVERRIDE", {"pump_dc": 42.5, "pump_dc_sw": 1, "valf_cmd": 0, "valf_cmd_sw": 0})
    bus.send(can.Message(arbitration_id=cid2, data=data2, is_extended_id=ext2))
    assert _wait(lambda: model.received_frames)
    got = model.received_frames[0]
    assert got[0] == cid2 and got[1] == data2 and got[2] is False


def test_extended_id_and_time_bases_are_separate(pair):
    bus, model = pair
    model.send_frame(0x18FF0001, b"\x01\x02", extended=True, sim_time=12.5)
    msg = bus.recv(timeout=2.0)
    assert msg.is_extended_id and msg.arbitration_id == 0x18FF0001
    assert msg.sim_time == 12.5                                       # simülasyon zamanı
    assert abs(msg.timestamp - time.time()) < 2.0                      # alım zamanı wall-clock; sim zamanıyla karışmaz
    assert bus.stats()["sim_time"] == 12.5


def test_bad_packets_rejected_and_counted(pair):
    bus, model = pair
    model.send_raw(b"\x00" * 30)
    model.send_raw(b"kisa")
    model.send_raw(proto.encode_can(1, 0, 0x100, b"")[:-3])
    model.send_frame(0x100, b"\x01")
    assert bus.recv(timeout=2.0).arbitration_id == 0x100
    assert bus.bad_packets == 3 and bus.last_bad_reason


def test_link_state_waiting_ok_timeout_and_recovery(pair):
    bus, model = pair
    assert bus.link_state()[0] == "waiting"
    model.send_heartbeat()
    assert _wait(lambda: bus.link_state()[0] == "ok")
    assert _wait(lambda: bus.link_state()[0] == "timeout", 2.0)      # veri gelmiyor → bağlantı hatası
    model.state = proto.MS_RUNNING
    model.send_heartbeat()                                           # model yeniden başladı
    assert _wait(lambda: bus.link_state()[0] == "ok")
    assert bus.stats()["model_state"] == "RUNNING"


def test_lost_packets_detected_by_sequence(pair):
    bus, model = pair
    model.send_frame(0x100, b"", seq=10)
    model.send_frame(0x100, b"", seq=14)                             # 11,12,13 kayıp
    assert _wait(lambda: bus.rx_frames == 2)
    assert bus.lost_packets == 3


def test_control_commands_reach_model(pair):
    bus, model = pair
    bus.send_control(proto.CMD_START)
    bus.send_control(proto.CMD_SPEED, 2.0)
    assert _wait(lambda: len(model.received_cmds) == 2)
    assert model.received_cmds == [(proto.CMD_START, 0.0), (proto.CMD_SPEED, 2.0)]


def test_model_may_start_after_connection_opened():
    bus = SimulinkUdpBus(channel="0:127.0.0.1:1", heartbeat=False)
    try:
        assert bus.link_state()[0] == "waiting"                      # model yokken bağlantı açılabilir
        model = FakeSimulink(0, bus.local_port)
        model.send_frame(0x200, b"\x05")
        assert bus.recv(timeout=2.0).arbitration_id == 0x200
        model.close()
    finally:
        bus.shutdown()


def test_can_connection_integration_no_physical_status(qapp=None):
    from app.can_worker import CanConnection
    conn = CanConnection()
    conn.connect("sim_udp", "0:127.0.0.1:1", 500000)
    try:
        assert conn.is_connected
        state, text = conn.link_state()
        assert state == "bus_warning" and "bekleniyor" in text         # model yok → hata değil uyarı
        model = FakeSimulink(0, conn.bus.local_port)
        conn.bus.remote_port = model.port
        model.send_frame(0x123, b"\x09")
        assert _wait(lambda: not conn.rx_queue.empty())
        assert conn.rx_queue.get().arbitration_id == 0x123
        assert conn.link_state()[0] == "ok"
        model.close()
    finally:
        conn.disconnect()


def test_connection_tab_modes_and_mil_ui(qapp):
    from app.ui.connection_tab import ConnectionTab
    t = ConnectionTab()
    seen = []
    t.mode_changed.connect(seen.append)
    assert t.mode == "REAL" and t.baudrate_combo.isVisibleTo(t)
    t.mode_combo.setCurrentIndex(t.mode_combo.findData("MIL"))
    assert seen == ["MIL"] and t.current_interface() == "sim_udp" and ":" in t.current_channel()
    assert not t.baudrate_combo.isVisibleTo(t) and t.mil_channel_edit.isVisibleTo(t)
    t.set_connected(True)
    assert "MIL" in t.status_label.text() and "kbit" not in t.status_label.text()      # sahte bitrate gösterilmez
    assert not t.mode_combo.isEnabled()
    assert t.set_mode("REAL") is False and t.mode == "MIL"                              # bağlıyken mod değişmez
    t.set_connected(False)
    t.mode_combo.setCurrentIndex(t.mode_combo.findData("VIRTUAL"))
    assert t.current_interface() == "virtual" and seen[-1] == "VIRTUAL"


def test_main_window_mil_connect_records_mode_and_no_ccp(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        w.connection_tab.mode_combo.setCurrentIndex(w.connection_tab.mode_combo.findData("MIL"))
        assert w.backend_mode == "MIL"
        w._on_connect("sim_udp", "0:127.0.0.1:1", 500000)
        assert w.connection.is_connected and w.backend_mode == "MIL"
        w.session_tab.name_edit.setText("mil")
        w.session_tab._on_start()
        import json
        meta = json.load(open(w.session_recorder.meta_path, encoding="utf-8"))
        assert meta["mode"] == "MIL" and meta["timebase"] == "simulation_time"
        w._on_disconnect()
        w.connection_tab.mode_combo.setCurrentIndex(w.connection_tab.mode_combo.findData("REAL"))
        assert not w.session_recorder.is_active              # mod değişimi açık kaydı kapattı
    finally:
        if w.connection.is_connected:
            w._on_disconnect()
        dispose(w)


def test_gui_sends_heartbeat_so_model_knows_gui_is_alive():
    bus = SimulinkUdpBus(channel="0:127.0.0.1:1", heartbeat=True)
    model = FakeSimulink(0, bus.local_port)
    bus.remote_port = model.port
    try:
        assert _wait(lambda: model.heartbeats_rx >= 2, 3.0)
    finally:
        bus.shutdown()
        model.close()


def test_shutdown_is_idempotent_and_send_after_shutdown_errors():
    bus = SimulinkUdpBus(channel="0:127.0.0.1:9", heartbeat=False)
    bus.shutdown()
    bus.shutdown()
    with pytest.raises(can.CanError):
        bus.send(can.Message(arbitration_id=0x100, data=b"\x01", is_extended_id=False))


def test_param_request_times_out_without_model():
    bus = SimulinkUdpBus(channel="0:127.0.0.1:9", heartbeat=False)
    try:
        t0 = time.time()
        with pytest.raises(TimeoutError):
            bus.param_request(proto.OP_READ, 1, timeout=0.1, retries=1)
        assert time.time() - t0 < 1.0
    finally:
        bus.shutdown()


def test_error_frames_and_oversized_payloads_are_rejected_on_send(pair):
    bus, model = pair
    with pytest.raises(can.CanError):
        bus.send(can.Message(is_error_frame=True, arbitration_id=0, data=b""))
    with pytest.raises(can.CanError):
        bus.send(can.Message(arbitration_id=0x900, data=b"\x01", is_extended_id=False))   # standart ID > 0x7FF
