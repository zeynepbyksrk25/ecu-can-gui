"""CCP temel protokol testleri (yazılım ECU simülatörüyle): bağlantı, okuma/yazma, hata kodları,
zaman aşımı, flaş yazma, A2L veri tipleri."""
import itertools
import struct
import time

import can
import pytest

from app.ccp import codec
from app.ccp import protocol as ccp
from app.ccp.client import CCPClient
from app.ccp.simulator import CCPSlaveSimulator

CRO, DTO = 0x6F9, 0x6F8
_ch = itertools.count()


@pytest.fixture
def ecu():
    channel = f"ccp-proto-{next(_ch)}"
    a = can.Bus(interface="virtual", channel=channel)
    b = can.Bus(interface="virtual", channel=channel)
    sim = CCPSlaveSimulator(a, CRO, DTO)
    sim.start()
    client = CCPClient(b, CRO, DTO, timeout=0.2, retries=1)
    client.start_listening()
    yield client, sim
    client.stop_listening()
    sim.stop()
    a.shutdown()
    b.shutdown()


def test_connect_version_test_and_disconnect(ecu):
    client, sim = ecu
    client.connect()
    assert client.is_connected and sim._connected
    assert client.get_ccp_version() == (2, 1)
    assert client.test_connection() is True
    client.disconnect()
    assert not client.is_connected and not sim._connected


def test_test_command_is_denied_without_session_on_strict_ecu(ecu):
    client, sim = ecu
    sim.strict_session = True
    assert client.test_connection() is False                 # CONNECT yok -> ACCESS_DENIED
    client.connect()
    assert client.test_connection() is True


@pytest.mark.parametrize("size", [1, 2, 3, 4, 5, 6, 7, 11])
def test_read_memory_any_length(ecu, size):
    client, sim = ecu
    client.connect()
    blob = bytes(range(1, 40))
    sim.write_memory_bytes(0x3000, blob)
    assert client.read_memory(0x3000, size) == blob[:size]
    assert client.read_memory(0x3005, size) == blob[5:5 + size]


@pytest.mark.parametrize("size", [1, 2, 5, 6, 7, 12, 13])
def test_write_memory_any_length_roundtrip(ecu, size):
    client, sim = ecu
    client.connect()
    data = bytes((i * 7 + 3) % 256 for i in range(size))
    client.write_memory(0x4000, data)
    assert sim.read_memory_bytes(0x4000, size) == data
    assert client.read_memory(0x4000, size) == data


def test_error_return_codes_raise_ccp_error_with_names(ecu):
    client, sim = ecu
    client.connect()
    sim.force_error_on[ccp.SHORT_UP] = ccp.RC_OUT_OF_RANGE
    with pytest.raises(ccp.CCPError) as ei:
        client.read_memory(0x1000, 2)
    assert ei.value.return_code == ccp.RC_OUT_OF_RANGE
    assert ccp.return_code_name(ccp.RC_OUT_OF_RANGE) in str(ei.value)
    sim.force_error_on.clear()
    sim.force_error_on[ccp.DNLOAD] = ccp.RC_ACCESS_DENIED
    with pytest.raises(ccp.CCPError) as ei:
        client.write_memory(0x1000, b"\x01")
    assert ei.value.return_code == ccp.RC_ACCESS_DENIED


def test_silent_ecu_times_out_after_the_configured_retries(ecu):
    client, sim = ecu
    client.connect()
    sim.power_off()
    t0 = time.perf_counter()
    with pytest.raises(ccp.CCPTimeoutError):
        client.read_memory(0x1000, 2)
    elapsed = time.perf_counter() - t0
    assert 0.35 <= elapsed <= 0.8                            # timeout 0.2 × (1 + 1 yeniden deneme)
    assert sim.requests_seen >= 1


def test_unknown_command_gets_cmd_unknown(ecu):
    client, sim = ecu
    client.connect()
    ctr = client._next_ctr()
    with pytest.raises(ccp.CCPError) as ei:
        client._command(bytes([0x77, ctr, 0, 0, 0, 0, 0, 0]), ctr, 0x77)
    assert ei.value.return_code == ccp.RC_CMD_UNKNOWN


def test_stale_responses_with_wrong_counter_are_ignored(ecu):
    client, sim = ecu
    client.connect()
    sim.write_memory_bytes(0x5000, b"\xAA\xBB")
    stale = ccp.PID_COMMAND_RETURN
    client._response_queue.put(can.Message(arbitration_id=DTO, data=bytes([stale, 0, 250, 1, 2, 3, 4, 5])))
    assert client.read_memory(0x5000, 2) == b"\xAA\xBB"      # eski cevap karıştırılmadı


def test_diag_service_passthrough(ecu):
    client, sim = ecu
    client.connect()
    assert client.diag_service(0x0102, b"\x09") == bytes([0x02, 0x01, 0x09, 0, 0])


def test_flash_write_goes_to_flash_not_ram(ecu):
    client, sim = ecu
    client.connect()
    data = bytes(range(10, 21))                              # 11 bayt: 6 + 5 parça
    client.write_flash_memory(0x8000, data)
    assert sim.read_flash_bytes(0x8000, len(data)) == data
    assert sim.read_memory_bytes(0x8000, len(data)) == bytes(len(data))


@pytest.mark.parametrize("dtype,value", [
    ("UBYTE", 200), ("SBYTE", -100), ("UWORD", 51234), ("SWORD", -12345), ("ULONG", 4000000000),
    ("SLONG", -2000000000), ("FLOAT32_IEEE", 6.75), ("FLOAT64_IEEE", 1234.5678), ("A_UINT64", 2 ** 40),
])
@pytest.mark.parametrize("order", ["MSB_FIRST", "MSB_LAST", None])
def test_codec_roundtrip_every_datatype_and_byte_order(dtype, value, order):
    raw = codec.encode_value(dtype, value, order)
    assert len(raw) == codec.datatype_size(dtype)
    assert codec.decode_value(dtype, raw, order) == pytest.approx(value)
    expected = struct.pack((("<" if order == "MSB_LAST" else ">") + codec._STRUCT_CODES[dtype]),
                           value if dtype.startswith("FLOAT") else int(value))
    assert raw == expected                                   # MSB_LAST = küçük-endian


def test_end_to_end_float_via_ccp_with_little_endian_ecu(ecu):
    client, sim = ecu
    client.connect()
    sim.write_memory_bytes(0x6000, struct.pack("<f", 12.5))
    raw = client.read_memory(0x6000, 4)
    assert codec.decode_value("FLOAT32_IEEE", raw, "MSB_LAST") == 12.5
    client.write_memory(0x6000, codec.encode_value("FLOAT32_IEEE", 40.0, "MSB_LAST"))
    assert struct.unpack("<f", sim.read_memory_bytes(0x6000, 4))[0] == 40.0
