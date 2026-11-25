"""Motor Başlat / Durdur / Acil Durdurma toggle'ları: ON=1, OFF=0 yazar; altında sinyalin o anki değeri görünür."""

from PySide6.QtWidgets import QMessageBox

from app.dashboard_config import SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, MotorCommand
from tests import test_dashboard_e2e as e2e
from tests.test_dashboard_e2e import _addr, _tick_until

# Ortak fixture'lar test_dashboard_e2e'den alınır (atama olarak: doğrudan import F811 uyarısı verir)
win = e2e.win
ccp = e2e.ccp
can_out = e2e.can_out


def _cfg_can():
    cfg = DashboardConfig()
    cfg.motor_start = MotorCommand(Binding(SOURCE_CAN, "CMD", "start_req"), 1.0)
    cfg.motor_stop = MotorCommand(Binding(SOURCE_CAN, "CMD", "stop_req"), 1.0)
    return cfg


def _decode(win, frame):
    return win.transmit_tab.dbc.get_message("CMD").decode(frame, decode_choices=False)


def test_buttons_are_toggles_with_readout_label(win):
    dt = win.dashboard_tab
    for tg in (dt.start_toggle, dt.stop_toggle, dt.estop_toggle):
        assert tg.switch.isCheckable() and tg.value.text() == "–"
    assert dt.start_button is dt.start_toggle.switch


def test_start_toggle_on_writes_1_and_off_writes_0(win, can_out):
    dt = win.dashboard_tab
    dt.set_config(_cfg_can())
    dt.start_button.click()                              # ON
    assert dt.start_button.isChecked()
    assert _decode(win, can_out[-1][1])["start_req"] == 1
    assert dt.start_toggle.value.text().startswith("1") and "gönderilen" in dt.start_toggle.value.text()
    dt.start_button.click()                              # OFF
    assert not dt.start_button.isChecked()
    assert _decode(win, can_out[-1][1])["start_req"] == 0
    assert dt.start_toggle.value.text().startswith("0")


def test_stop_toggle_on_off(win, can_out):
    dt = win.dashboard_tab
    dt.set_config(_cfg_can())
    dt.stop_button.click()
    assert _decode(win, can_out[0][1])["stop_req"] == 1
    n = len(can_out)
    dt.stop_button.click()
    assert len(can_out) > n and _decode(win, can_out[-1][1])["stop_req"] == 0


def test_failed_send_returns_the_toggle_to_its_previous_state(win, can_out, monkeypatch):
    dt = win.dashboard_tab
    dt.set_config(_cfg_can())
    monkeypatch.setattr(win, "_write_binding", lambda *a, **k: False)
    dt.start_button.click()
    assert not dt.start_button.isChecked()               # gitmedi: ON görünmemeli
    assert dt.start_toggle.value.text() == "–"


def test_estop_off_writes_0_directly_without_confirmation(win, can_out, monkeypatch):
    dt = win.dashboard_tab
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_CAN, "CMD", "estop_req"), 1.0)
    dt.set_config(cfg)
    dt.estop_button.click()
    assert dt.estop_button.isChecked() and _decode(win, can_out[0][1])["estop_req"] == 1
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: asked.append(a) or QMessageBox.No))
    dt.estop_button.click()                              # OFF: onay yok, doğrudan 0
    assert asked == []
    assert not dt.estop_button.isChecked()
    assert _decode(win, can_out[-1][1])["estop_req"] == 0
    assert dt.estop_toggle.value.text().startswith("0")


def test_can_rx_value_is_shown_as_ecu(win, can_out):
    dt = win.dashboard_tab
    dt.set_config(_cfg_can())
    win._rebuild_dash_can_map()
    msg = win.transmit_tab.dbc.get_message("CMD")
    data = msg.encode({"start_req": 1, "stop_req": 0, "estop_req": 0}, strict=False)
    win._dash_on_can_frame(msg.frame_id, data)
    assert dt.start_toggle.value.text() == "1  ·  ECU"
    assert dt.stop_toggle.value.text() == "0  ·  ECU"


def test_ecu_value_beats_sent_then_falls_back_when_stale(win):
    import time
    dt = win.dashboard_tab
    dt.set_motor_state("motor_start", 1, "sent")
    dt.set_motor_state("motor_start", 0, "ecu")
    assert dt.start_toggle.value.text() == "0  ·  ECU"
    dt._motor_ecu["motor_start"] = (0.0, time.monotonic() - 10)          # eskidi
    dt._refresh_motor_readout()
    assert dt.start_toggle.value.text() == "1  ·  gönderilen"


def test_a2l_value_is_read_from_ecu(win, ccp):
    dt = win.dashboard_tab
    name = "clbc_Fuel_pump_dc_perc_sw"
    cfg = DashboardConfig()
    cfg.motor_start = MotorCommand(Binding(SOURCE_A2L, a2l_name=name), 1.0)
    dt.set_config(cfg)
    assert dt.motor_a2l_names() == [name]
    ccp.write_memory_bytes(_addr(win, name), b"\x01")
    ok = _tick_until(win, [name], lambda: dt.start_toggle.value.text().endswith("ECU"))
    assert ok


def test_changing_the_mapping_clears_the_old_readout(win):
    dt = win.dashboard_tab
    dt.set_config(_cfg_can())
    dt.set_motor_state("motor_start", 1, "sent")
    cfg = _cfg_can()
    cfg.motor_start = MotorCommand(Binding(SOURCE_CAN, "CMD", "stop_req"), 1.0)
    dt.set_config(cfg)
    assert dt.start_toggle.value.text() == "–"
