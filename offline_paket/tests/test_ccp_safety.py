"""CCP yazma güvenliği: retry semantiği, doğrulama, geri okuma, harita yazımı."""
import os
from types import SimpleNamespace

import can
import pytest

from app.ccp import codec, mapio, protocol as ccp
from app.ccp.client import CCPClient, CCPVerifyError
from app.ccp.simulator import CCPSlaveSimulator

CRO, DTO = 0x100, 0x101


@pytest.fixture
def link():
    a = can.Bus(interface="virtual", channel="t1")
    b = can.Bus(interface="virtual", channel="t1")
    sim = CCPSlaveSimulator(b, CRO, DTO)
    sim.start()
    cli = CCPClient(a, CRO, DTO, timeout=0.15, retries=2)
    cli.connect()
    yield cli, sim
    cli.disconnect()
    sim.stop()
    a.shutdown()
    b.shutdown()


def info(**kw):
    d = dict(name="X", datatype="UWORD", byte_order="MSB_FIRST", compu_method=None,
             minimum=0.0, maximum=100.0, read_only=False, address=0x2000, address_extension=0)
    d.update(kw)
    return SimpleNamespace(**d)


# ---- codec -----------------------------------------------------------------
@pytest.mark.parametrize("dt,val", [("UBYTE", 300), ("UBYTE", -1), ("SWORD", 40000),
                                    ("UWORD", float("inf")), ("FLOAT32_IEEE", 1e40),
                                    ("UWORD", float("nan"))])
def test_encode_rejects_out_of_range_as_valueerror(dt, val):
    with pytest.raises(ValueError):
        codec.encode_value(dt, val)


def test_encode_rounds_half_up_and_byte_order():
    assert codec.encode_value("UBYTE", 2.5) == b"\x03"
    assert codec.encode_value("UWORD", 0x0102, "MSB_FIRST") == b"\x01\x02"
    assert codec.encode_value("UWORD", 0x0102, "MSB_LAST") == b"\x02\x01"


def test_validate_write_limits_and_readonly():
    assert codec.validate_write(info(), 50) == 50.0
    for bad in (-1, 101, float("nan"), float("inf"), "abc"):
        with pytest.raises(codec.WriteValidationError):
            codec.validate_write(info(), bad)
    with pytest.raises(codec.WriteValidationError):
        codec.validate_write(info(read_only=True), 1)
    # alt == üst sınır -> "sınır tanımsız"
    assert codec.validate_write(info(minimum=0.0, maximum=0.0), 5000) == 5000.0


def test_physical_to_raw_never_falls_back_silently():
    class Bad:
        class evaluator:
            @staticmethod
            def physical_to_int(_):
                raise RuntimeError("tab")
    with pytest.raises(codec.UnsupportedConversionError):
        codec.physical_to_raw(Bad, 2.5)


# ---- client ----------------------------------------------------------------
def test_lost_dto_does_not_reexecute_dnload(link):
    cli, sim = link
    sim.drop_dto_count[ccp.DNLOAD] = 1          # DNLOAD çalışır ama cevabı kaybolur
    with pytest.raises(ccp.CCPTimeoutError):
        cli.write_memory(0x2000, b"\x11\x22")
    assert sim.executed.count(ccp.DNLOAD) == 1  # tekrar GÖNDERİLMEMELİ
    assert sim.read_memory_bytes(0x2000, 3) == b"\x11\x22\x00"  # bitişik bayt bozulmadı


def test_lost_dto_on_short_up_is_retried(link):
    cli, sim = link
    sim.write_memory_bytes(0x3000, b"\xAA\xBB\xCC")
    sim.drop_dto_count[ccp.SHORT_UP] = 1
    assert cli.read_memory(0x3000, 3) == b"\xAA\xBB\xCC"
    assert sim.executed.count(ccp.SHORT_UP) == 2


def test_read_memory_long_uses_short_up_only(link):
    cli, sim = link
    data = bytes(range(23))
    sim.write_memory_bytes(0x4000, data)
    assert cli.read_memory(0x4000, 23) == data
    assert ccp.UPLOAD not in sim.executed


def test_verify_detects_mismatch(link):
    cli, sim = link
    cli.write_memory(0x5000, b"\x01\x02\x03", verify=True)

    orig = sim._handle_dnload

    def corrupt(data, ctr):                       # ECU yazdığını bozuyor
        orig(data, ctr)
        sim.memory[sim._mta_address - 1] ^= 0xFF
    sim._handle_dnload = corrupt
    with pytest.raises(CCPVerifyError):
        cli.write_memory(0x5100, b"\x01\x02\x03", verify=True)


def test_ctr_allocation_thread_safe():
    import threading
    c = CCPClient(None, CRO, DTO)
    seen, lock = [], threading.Lock()

    def work():
        for _ in range(100):
            v = c._next_ctr()
            with lock:
                seen.append(v)
    ts = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert len(seen) == 400 and sum(1 for _ in seen) == 400


# ---- mapio -------------------------------------------------------------------
def ch(**kw):
    d = dict(name="MAP1", kind="ARRAY", datatype="UWORD", byte_order="MSB_FIRST", compu_method=None,
             minimum=0.0, maximum=1000.0, read_only=False, address=0x6000, address_extension=0,
             axes=[], dims=(2, 3), index_mode="ROW_DIR")
    d.update(kw)
    return SimpleNamespace(**d)


def test_write_grid_roundtrip_and_returns_old(link):
    cli, sim = link
    c = ch()
    old = [[1, 2, 3], [4, 5, 6]]
    sim.write_memory_bytes(0x6000, b"".join(v.to_bytes(2, "big") for r in old for v in r))
    new = [[10, 20, 30], [40, 50, 60]]
    prev = mapio.write_grid(cli, c, new)
    assert prev == old
    assert mapio.read_grid(cli, c) == new


def test_column_dir_is_transposed(link):
    cli, sim = link
    c = ch(index_mode="COLUMN_DIR")
    mapio.write_grid(cli, c, [[1, 2, 3], [4, 5, 6]])
    mem = sim.read_memory_bytes(0x6000, 12)
    assert [int.from_bytes(mem[i:i + 2], "big") for i in range(0, 12, 2)] == [1, 4, 2, 5, 3, 6]
    assert mapio.read_grid(cli, c) == [[1, 2, 3], [4, 5, 6]]


def test_write_grid_rejects_bad_input_before_touching_ecu(link):
    cli, sim = link
    c = ch()
    before = len(sim.executed)
    for grid in ([[1, 2, 3]], [[1, 2, 3], [4, 5, float("nan")]], [[1, 2, 3], [4, 5, 5000]]):
        with pytest.raises(ValueError):
            mapio.write_grid(cli, c, grid)
    assert len(sim.executed) == before


def test_write_grid_unsupported_layouts_refused(link):
    cli, _ = link
    axes = [SimpleNamespace(attribute="STD_AXIS", count=3)]
    with pytest.raises(mapio.UnsupportedLayoutError):
        mapio.write_grid(cli, ch(axes=axes), [[1, 2, 3], [4, 5, 6]])
    with pytest.raises(mapio.UnsupportedLayoutError):
        mapio.write_grid(cli, ch(index_mode="ALTERNATE_CURVES"), [[1, 2, 3], [4, 5, 6]])
    with pytest.raises(codec.WriteValidationError):
        mapio.write_grid(cli, ch(read_only=True), [[1, 2, 3], [4, 5, 6]])


def test_write_grid_rolls_back_on_failure(link):
    cli, sim = link
    c = ch()
    old = [[1, 2, 3], [4, 5, 6]]
    sim.write_memory_bytes(0x6000, b"".join(v.to_bytes(2, "big") for r in old for v in r))
    orig = sim._handle_dnload6
    calls = {"n": 0}

    def flaky(data, ctr):
        calls["n"] += 1
        if calls["n"] == 2:                        # ikinci parçada DTO kaybı
            sim.drop_dto_count[ccp.DNLOAD_6] = 1
        orig(data, ctr)
    sim._handle_dnload6 = flaky
    with pytest.raises(ccp.CCPTimeoutError):
        mapio.write_grid(cli, c, [[10, 20, 30], [40, 50, 60]])
    sim._handle_dnload6 = orig
    assert mapio.read_grid(cli, c) == old


# ---- a2l ---------------------------------------------------------------------
def test_a2l_default_byte_order_and_index_mode():
    pytest.importorskip("pya2l")
    from app.a2l import A2LDatabase
    db = A2LDatabase()
    s = db.load(os.path.join(os.path.dirname(__file__), "sample.a2l"))
    assert s.default_byte_order == "MSB_LAST"
    assert all(m.byte_order == "MSB_LAST" for m in s.measurements)
    blk = next(c for c in s.characteristics if c.name == "BLK_A")
    assert blk.byte_order == "MSB_LAST" and blk.index_mode == "COLUMN_DIR" and blk.dims == (3, 2)
    # bozuk dosya önceki geçerli A2L'i bozmamalı
    bad = os.path.join(os.path.dirname(__file__), "bad.a2l")
    with open(bad, "w") as f:
        f.write("/begin PROJECT")
    try:
        with pytest.raises(ValueError):
            db.load(bad)
    finally:
        os.remove(bad)
    assert db.is_loaded and db.summary is s
