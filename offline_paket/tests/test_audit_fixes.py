"""Denetim listesinden düzeltilenler: periyodik gönderimin Acil Durdurma'yı ezmesi, sonsuz değer, döngüsel
matematik sinyali, dönüşüm hatası, sınırsız CCP olay kuyruğu, toplu yazmada geri okuma, tablo uyarısı."""
import math

import pytest

from app.ccp import codec
from app.dashboard_config import SOURCE_CAN, Binding, DashboardConfig, MotorCommand
from app.signal_hub import SignalHub
from tests import test_dashboard_e2e as e2e

win = e2e.win
ccp = e2e.ccp
can_out = e2e.can_out


# ---- 1.1 Acil Durdurma periyodik gönderimle ezilmesin ------------------------------------------------------
def _cmd(win, frame):
    return win.transmit_tab.dbc.get_message("CMD").decode(frame, decode_choices=False)


def test_estop_is_not_overwritten_by_the_next_periodic_frame(win, can_out):
    # Mesaj Kontrol Paneli / eyleyici yolundan ZATEN periyodik gönderiliyor
    assert win._write_binding(Binding(SOURCE_CAN, "CMD", "start_req"), 1.0, "Eyleyici")
    assert win.tx_scheduler.is_running("CMD")
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_CAN, "CMD", "estop_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    win._on_estop()
    assert _cmd(win, can_out[-1][1])["estop_req"] == 1
    win.tx_scheduler._tick("CMD")                       # periyodik iş parçacığının bir sonraki tiki
    periodic = _cmd(win, can_out[-1][1])
    assert periodic["estop_req"] == 1, "periyodik kare Acil Durdurma'yı 0'la ezmemeli"
    assert periodic["start_req"] == 1, "mesajın diğer sinyalleri periyodik karedeki değerinde kalır"
    win._on_estop_released()                            # kilit açılınca periyodik kareler de 0'a döner
    win.tx_scheduler._tick("CMD")
    assert _cmd(win, can_out[-1][1])["estop_req"] == 0


def test_safety_value_outside_dbc_limits_still_goes_when_message_is_periodic(win, can_out):
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 10.0, "Eyleyici")
    assert win.tx_scheduler.is_running("OVERRIDE")
    b = Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd")      # DBC sınırı 0..100, 150 bit genişliğine sığar
    assert win._write_binding(b, 150.0, "Motor Başlat", merge=False, safety=False) is False
    assert win._write_binding(b, 150.0, "ACİL DURDURMA", merge=False, safety=True) is True
    win.tx_scheduler._tick("OVERRIDE")
    v = win.transmit_tab.dbc.get_message("OVERRIDE").decode(can_out[-1][1], decode_choices=False)
    assert v["valf_cmd"] == pytest.approx(150.0, abs=0.1) and v["pump_dc"] == pytest.approx(10.0, abs=0.1)


# ---- 3.3 sonsuz değer ---------------------------------------------------------------------------------------
def test_hub_rejects_infinite_values():
    h = SignalHub()
    h.set_active({"a2l:x"})
    for bad in (math.inf, -math.inf, math.nan):
        h.push("a2l:x", bad)
    assert "a2l:x" not in h._last
    h.push("a2l:x", 1.5)
    assert h._last["a2l:x"] == 1.5


# ---- 3.4 döngüsel türetilmiş sinyal ---------------------------------------------------------------------------
def test_circular_derived_signals_are_rejected():
    h = SignalHub()
    h.define_derived("A", {"kind": "scale", "src": "a2l:x", "gain": 1.0, "offset": 0.0})
    h.define_derived("B", {"kind": "scale", "src": "math:A", "gain": 1.0, "offset": 1.0})
    assert h.would_cycle("A", {"kind": "scale", "src": "math:B"})
    with pytest.raises(ValueError, match="döngüsel"):
        h.define_derived("A", {"kind": "scale", "src": "math:B", "gain": 1.0, "offset": 1.0})
    with pytest.raises(ValueError):
        h.define_derived("C", {"kind": "scale", "src": "math:C"})            # kendine bağımlı
    assert h.derived["math:A"]["src"] == "a2l:x"                              # eski tanım bozulmadı


def test_recompute_does_not_recurse_forever_on_a_cycle_loaded_from_outside():
    h = SignalHub()
    h.derived["math:A"] = {"kind": "scale", "src": "math:B", "gain": 1.0, "offset": 1.0}
    h.derived["math:B"] = {"kind": "scale", "src": "math:A", "gain": 1.0, "offset": 1.0}
    h.recompute("math:A")                                                      # RecursionError olmamalı


# ---- 2.2 COMPU_METHOD dönüşüm hatası ----------------------------------------------------------------------------
class _Conv:
    def __init__(self, kind, fail):
        self.conversionType = kind
        self._fail = fail

    def int_to_physical(self, raw):
        if self._fail:
            raise RuntimeError("katsayı eksik")
        return raw * 0.001


def test_failed_conversion_raises_instead_of_showing_the_raw_number_as_physical():
    assert codec.raw_to_physical(_Conv("LINEAR", False), 2500) == pytest.approx(2.5)
    with pytest.raises(codec.ConversionError):
        codec.raw_to_physical(_Conv("LINEAR", True), 2500)
    assert issubclass(codec.ConversionError, ValueError)                       # çağıranlar ValueError'u zaten yakalar


def test_verbal_table_keeps_the_raw_status_code():
    assert codec.raw_to_physical(_Conv("TAB_VERB", True), 4) == 4


# ---- sınırsız CCP olay kuyruğu --------------------------------------------------------------------------------------
def test_ccp_event_queue_is_bounded_and_keeps_the_newest_events():
    from app.ccp import worker as w
    s = w.CcpSession(object())
    for i in range(w.EVENT_QUEUE_MAX + 50):
        s._emit("e", i)
    events = s.poll_events()
    assert len(events) == w.EVENT_QUEUE_MAX
    assert events[-1] == ("e", w.EVENT_QUEUE_MAX + 49) and s.events_dropped == 50


# ---- 5 yazmada geri okuma ---------------------------------------------------------------------------------------------
def test_worksheet_value_write_verifies_by_reading_back(win, ccp):
    win.modas_tab.set_summary(win.a2l_tab.db.summary)
    obj = next(c for c in win.a2l_tab.db.summary.characteristics if c.name == "clbc_Fuel_pump_gain")
    w = win.modas_tab.add_label(obj.name)
    calls = []
    client = win.ccp_client
    orig = client.write_memory
    client.write_memory = lambda *a, **k: (calls.append(k), orig(*a, **k))[1]
    win._modas_write_value(w, "12")
    assert calls and all(c.get("verify") is True for c in calls)
