"""MIL kalibrasyon köprüsü: manifest eşleme + UDP parametre kanalı (sahte model; gerçek Simulink'te doğrulanmadı)."""
import struct

import pytest

from app import sim_protocol as proto
from app.a2l import CharacteristicInfo
from app.ccp import protocol as ccp
from app.sim_bridge.param_client import SimParamClient, SimParamError
from app.sim_bridge.parameters import ManifestError, parse_manifest
from app.sim_bus import SimulinkUdpBus
from tests.fake_simulink import FakeSimulink

MANIFEST = {"version": 1, "parameters": [
    {"a2l": "Kp", "simulink": "Gov/Kp", "index": 1, "datatype": "double", "tunable_running": True},
    {"a2l": "Fuel", "simulink": "Fuel/Lim", "index": 2, "datatype": "uint8", "factor": 2.0, "offset": 10.0},
    {"a2l": "RO", "simulink": "X/Ro", "index": 3, "access": "ro"},
    {"a2l": "Tab", "simulink": "Fuel/Table", "index": 10, "count": 3, "datatype": "double"},
]}


def _c(name, addr, dt="FLOAT32_IEEE", kind="SCALAR"):
    return CharacteristicInfo(name, "", kind, addr, "", dt, None, None, False, 0, byte_order="LITTLE_ENDIAN")


@pytest.fixture
def rig():
    bus = SimulinkUdpBus(channel="0:127.0.0.1:1", heartbeat=False)
    model = FakeSimulink(0, bus.local_port)
    bus.remote_port = model.port
    model.params = {1: 1.2, 2: 30.0, 3: 5.0, 10: 1.0, 11: 2.0, 12: 3.0}
    model.tunable_running = {1}
    chars = [_c("Kp", 0x100), _c("Fuel", 0x200, "UBYTE"), _c("RO", 0x300), _c("Tab", 0x400, kind="ARRAY"), _c("Yok", 0x500)]
    cl = SimParamClient(bus, parse_manifest(MANIFEST), chars, lambda: model.state)
    cl.timeout = 0.3
    yield cl, model, bus
    bus.shutdown()
    model.close()


def f32(v):
    return struct.pack("<f", v)


def test_manifest_validation():
    for bad, msg in (
        ({}, "parameters"),
        ({"parameters": [{"a2l": "A", "simulink": "S", "index": 1, "datatype": "string"}]}, "veri tipi"),
        ({"parameters": [{"a2l": "A", "simulink": "S", "index": 1, "access": "x"}]}, "erişim"),
        ({"parameters": [{"a2l": "A", "simulink": "S", "index": 1, "factor": 0}]}, "factor"),
        ({"parameters": [{"a2l": "A", "simulink": "S", "index": 1}, {"a2l": "A", "simulink": "T", "index": 2}]}, "tekrar"),
        ({"parameters": [{"a2l": "A", "simulink": "S", "index": 1, "count": 3},
                         {"a2l": "B", "simulink": "T", "index": 2}]}, "çakışma"),
        ({"parameters": [{"a2l": "A"}]}, "zorunlu"),
    ):
        with pytest.raises(ManifestError, match=msg):
            parse_manifest(bad)
    m = parse_manifest(MANIFEST).by_a2l()
    assert m["Fuel"].to_model(10) == 30.0 and m["Fuel"].from_model(30.0) == 10.0


def test_read_applies_inverse_scaling_and_ignores_unmapped(rig):
    cl, model, _ = rig
    assert struct.unpack("<f", cl.read_memory(0x100, 4))[0] == pytest.approx(1.2, rel=1e-6)
    assert cl.read_memory(0x200, 1) == bytes([10])                      # (30-10)/2
    assert "Yok" in cl.unmapped and cl.mapped_names() == ["Fuel", "Kp", "RO", "Tab"]
    with pytest.raises(SimParamError, match="eşlemesi yok"):
        cl.read_memory(0x500, 4)


def test_write_verify_readback_and_scaling(rig):
    cl, model, _ = rig
    cl.write_memory(0x100, f32(1.35), verify=True)
    assert model.params[1] == pytest.approx(1.35, rel=1e-6)
    cl.write_memory(0x200, bytes([20]), verify=True)
    assert model.params[2] == 50.0                                      # 20*2+10


def test_array_cells_read_and_write(rig):
    cl, model, _ = rig
    cl.write_memory(0x400, struct.pack("<fff", 7.0, 8.0, 9.0), verify=True)
    assert [model.params[i] for i in (10, 11, 12)] == [7.0, 8.0, 9.0]
    assert struct.unpack("<fff", cl.read_memory(0x400, 12)) == (7.0, 8.0, 9.0)


def test_read_only_and_flash_refused(rig):
    cl, model, _ = rig
    with pytest.raises(SimParamError, match="salt-okunur"):
        cl.write_memory(0x300, f32(1.0))
    with pytest.raises(SimParamError, match="flaş"):
        cl.write_flash_memory(0x100, f32(1.0), 0)
    assert model.params[3] == 5.0


def test_running_model_non_tunable_requires_stop(rig):
    cl, model, _ = rig
    model.state = proto.MS_RUNNING
    with pytest.raises(SimParamError, match="ÇALIŞIRKEN"):
        cl.write_memory(0x200, bytes([1]))                              # tunable_running yok → gönderilmeden reddedilir
    assert model.params[2] == 30.0
    cl.write_memory(0x100, f32(2.0), verify=True)                       # tunable → serbest
    assert model.params[1] == pytest.approx(2.0)
    model.state = proto.MS_STOPPED
    cl.write_memory(0x200, bytes([1]))
    assert model.params[2] == 12.0


def test_model_side_nak_is_reported_with_reason(rig):
    cl, model, _ = rig
    model.reject_range[1] = (0.0, 2.0)
    with pytest.raises(SimParamError, match="aralık dışı"):
        cl.write_memory(0x100, f32(5.0))
    assert model.params[1] == 1.2


def test_applied_value_mismatch_fails_verification(rig):
    cl, model, _ = rig
    model.clamp[1] = 9.0                                                # model başka değer uyguladı
    with pytest.raises(SimParamError, match="doğrulama"):
        cl.write_memory(0x100, f32(1.5), verify=True)


def test_integer_range_checked_before_sending(rig):
    cl, model, _ = rig
    with pytest.raises(SimParamError, match="uint8"):
        cl.write_memory(0x200, bytes([250]))                            # 250*2+10=510 > 255
    assert model.params[2] == 30.0


def test_timeout_when_model_silent(rig):
    cl, model, _ = rig
    model.ignore_params = True
    with pytest.raises(ccp.CCPTimeoutError):
        cl.read_memory(0x100, 4)


def test_session_adopts_sim_client_and_cached_reader_works(rig, qapp):
    """Mevcut CcpSession (arka plan okuma + önbellek) SimParamClient ile aynen çalışır."""
    import time
    from app.can_worker import CanConnection
    from app.ccp.worker import CcpSession, ONLINE
    cl, model, bus = rig
    conn = CanConnection()
    conn.bus = bus                                                      # bağlantı nesnesi aynı bus'ı kullanır
    sess = CcpSession(conn)
    sess.adopt(cl)
    try:
        assert sess.state == ONLINE
        end = time.time() + 3
        val = None
        while time.time() < end:
            try:
                val = struct.unpack("<f", sess.reader.read_memory(0x100, 4))[0]
                break
            except Exception:
                time.sleep(0.05)
        assert val == pytest.approx(1.2, rel=1e-6)
    finally:
        sess.stop(graceful=False)
        conn.bus = None
