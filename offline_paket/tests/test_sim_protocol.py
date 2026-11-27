import struct

import pytest

from app import sim_protocol as p


def test_can_roundtrip_standard_and_extended():
    pkt = p.encode_can(7, 1.25, 0x1A0, b"\x01\x02\x03", extended=False)
    assert len(pkt) == 30
    d = p.decode(pkt)
    assert (d.type, d.seq, d.sim_time, d.can_id, d.extended, d.data) == (p.T_CAN, 7, 1.25, 0x1A0, False, b"\x01\x02\x03")
    d = p.decode(p.encode_can(1, 0.0, 0x18FF0001, bytes(range(8)), extended=True, rtr=False))
    assert d.extended and d.can_id == 0x18FF0001 and d.data == bytes(range(8))


def test_encode_rejects_bad_input():
    with pytest.raises(p.ProtocolError):
        p.encode_can(0, 0, 0x800, b"")                 # standart ID > 0x7FF
    with pytest.raises(p.ProtocolError):
        p.encode_can(0, 0, 0x100, bytes(9))            # DLC 9
    with pytest.raises(p.ProtocolError):
        p.encode_can(0, 0, 0x20000000, b"", True)


def test_heartbeat_and_control():
    d = p.decode(p.encode_heartbeat(3, 2.5, p.MS_RUNNING))
    assert d.type == p.T_HEARTBEAT and d.model_state == p.MS_RUNNING and d.sim_time == 2.5
    assert p.decode(p.encode_heartbeat(3, 0, 99)).model_state == p.MS_UNKNOWN
    c = p.decode(p.encode_control(1, p.CMD_SPEED, 2.0))
    assert c.command == p.CMD_SPEED and c.arg == 2.0
    with pytest.raises(p.ProtocolError):
        p.decode(p.encode_control(1, 9, 0.0))


@pytest.mark.parametrize("mutate,msg", [
    (lambda b: b[:10], "kısa"),
    (lambda b: b"\x00\x00" + b[2:], "magic"),
    (lambda b: b[:2] + b"\x09" + b[3:], "sürüm"),
    (lambda b: b[:3] + b"\x09" + b[4:], "tür"),
    (lambda b: b + b"\x00", "boyut"),
    (lambda b: b[:-1], "boyut"),
])
def test_decode_rejects_malformed(mutate, msg):
    good = p.encode_can(1, 0.0, 0x100, b"\x01")
    with pytest.raises(p.ProtocolError, match=msg):
        p.decode(mutate(good))


def test_decode_rejects_dlc_over_8_id_range_and_nan_time():
    good = bytearray(p.encode_can(1, 0.0, 0x100, b"\x01"))
    bad = bytearray(good); bad[21] = 9
    with pytest.raises(p.ProtocolError, match="DLC"):
        p.decode(bytes(bad))
    bad = bytearray(good); struct.pack_into("<I", bad, 16, 0x800)
    with pytest.raises(p.ProtocolError, match="ID"):
        p.decode(bytes(bad))
    bad = bytearray(good); struct.pack_into("<d", bad, 8, float("nan"))
    with pytest.raises(p.ProtocolError, match="sonlu"):
        p.decode(bytes(bad))
