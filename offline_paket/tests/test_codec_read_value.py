"""ccp.codec.read_value: tek okuma kuralı (ham + fiziksel) ve hata yayılımı."""
import struct
from types import SimpleNamespace

import pytest

from app.ccp import codec, protocol


class FakeReader:
    def __init__(self, data=b"", exc=None):
        self.data, self.exc, self.calls = data, exc, []

    def read_memory(self, address, length, address_extension=0):
        self.calls.append((address, length, address_extension))
        if self.exc is not None:
            raise self.exc
        return self.data


def _info(**kw):
    base = dict(address=0x1000, datatype="UWORD", byte_order=None, address_extension=None, compu_method=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_reads_raw_and_physical_with_defaults():
    r = FakeReader(struct.pack(">H", 9040))
    rd = codec.read_value(r, _info())
    assert rd.raw == 9040 and rd.phys == 9040 and rd.raw_bytes == struct.pack(">H", 9040)
    assert r.calls == [(0x1000, 2, 0)]                 # adres uzantısı None -> 0


def test_byte_order_address_extension_and_compu_method():
    class Compu:                                       # birebir pya2l evaluator arayüzü
        class evaluator:
            @staticmethod
            def int_to_physical(raw):
                return raw * 0.5
    r = FakeReader(struct.pack("<H", 9040))
    rd = codec.read_value(r, _info(byte_order="MSB_LAST", address_extension=3, compu_method=Compu))
    assert rd.raw == 9040 and rd.phys == pytest.approx(4520.0)
    assert rd.raw_bytes == struct.pack("<H", 9040)       # Worksheets değer penceresi HAM BAYT bekler
    assert r.calls == [(0x1000, 2, 3)]


def test_info_without_optional_attributes_is_accepted():
    info = SimpleNamespace(address=0x20, datatype="FLOAT32_IEEE")      # byte_order/compu_method/uzantı yok
    rd = codec.read_value(FakeReader(struct.pack(">f", 1.5)), info)
    assert rd.raw == pytest.approx(1.5) and rd.phys == pytest.approx(1.5)


def test_errors_propagate_unchanged():
    with pytest.raises(protocol.CCPTimeoutError):
        codec.read_value(FakeReader(exc=protocol.CCPTimeoutError("zaman aşımı")), _info())
    with pytest.raises(codec.UnknownDatatypeError):
        codec.read_value(FakeReader(b"\x00\x00"), _info(datatype="NOPE"))
    with pytest.raises(ValueError):
        codec.read_value(FakeReader(b"\x01"), _info())                 # 2 bayt gerekir, 1 geldi


def test_control_panel_helper_returns_physical_only():
    from app import control_panel as cpanel
    r = FakeReader(struct.pack(">H", 7))
    assert cpanel.ccp_read_value(r, _info()) == 7
