"""Uçtan uca: A2L (CCP simülatörü) ve DBC (CAN) üzerinden Ana Sayfa okuma/yazma."""
import os
import struct
import time

import can
import pytest
from PySide6.QtWidgets import QMessageBox

from app.ccp.client import CCPClient
from app.ccp.simulator import CCPSlaveSimulator
from app.dashboard_config import SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, MotorCommand, SignalMap

DATA = os.path.join(os.path.dirname(__file__), "data")
CRO, DTO = 0x6F9, 0x6F8


@pytest.fixture
def win(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.Ok))
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
    w._on_dashboard_sources_changed()
    yield w
    w.close()


@pytest.fixture
def ccp(win):
    a = can.Bus(interface="virtual", channel="ecu-test")
    b = can.Bus(interface="virtual", channel="ecu-test")
    sim = CCPSlaveSimulator(a, CRO, DTO)
    sim.start()
    client = CCPClient(b, CRO, DTO, timeout=0.5, retries=1)
    client.start_listening()
    client.connect()
    win.ccp_client = client
    yield sim
    client.stop_listening()
    sim.stop()
    a.shutdown()
    b.shutdown()


def _tick_until(win, names, cond, timeout=4.0):
    """Arka plan CCP iş parçacığı değerleri önbelleğe alana kadar Ana Sayfa tikini tekrarla."""
    end = time.time() + timeout
    while time.time() < end:
        win._on_dashboard_tick(names)
        if cond():
            return True
        time.sleep(0.05)
    return False


def _addr(win, name):
    return next(m for m in win.a2l_tab.db.summary.measurements if m.name == name).address


def _cfg(win, **sensors):
    cfg = DashboardConfig()
    for k, b in sensors.items():
        cfg.sensors[k] = SignalMap(value=b)
    win.dashboard_tab.set_config(cfg)
    win._rebuild_dash_can_map()
    return cfg


def test_a2l_little_endian_values_show_real_numbers(win, ccp):
    """Regresyon: MOD_COMMON BYTE_ORDER MSB_LAST okunmadığında RPM çöp (10257) çıkıyordu."""
    ccp.write_memory_bytes(_addr(win, "N_RPM"), struct.pack("<H", 9040))          # 4520 rpm (x0.5)
    ccp.write_memory_bytes(_addr(win, "FP_bar"), struct.pack("<f", 6.8))
    _cfg(win, RPM=Binding(SOURCE_A2L, a2l_name="N_RPM"), FP=Binding(SOURCE_A2L, a2l_name="FP_bar"))
    dt = win.dashboard_tab
    assert _tick_until(win, ["N_RPM", "FP_bar"], lambda: "RPM" in dt._values and "FP" in dt._values)
    assert dt._values["RPM"][0] == pytest.approx(4520.0)
    assert dt._values["FP"][0] == pytest.approx(6.8, rel=1e-5)
    assert dt._gauge_cards["RPM"].gauge.fraction() == pytest.approx(4520 / 6000)   # ibre hareket eder


def test_reasons_are_shown_when_value_cannot_be_read(win):
    dt = win.dashboard_tab
    _cfg(win, RPM=Binding(SOURCE_A2L, a2l_name="N_RPM"))
    win._on_dashboard_tick(["N_RPM"])                       # CCP bağlı değil
    assert dt._reasons["RPM"] == "CCP bağlı değil"
    assert dt._gauge_cards["RPM"].status.text() == "CCP bağlı değil"


def test_missing_a2l_name_and_missing_address_reasons(win, ccp):
    dt = win.dashboard_tab
    _cfg(win, RPM=Binding(SOURCE_A2L, a2l_name="YOK_DEGISKEN"), Tt2=Binding(SOURCE_A2L, a2l_name="NoAddr"))
    win._on_dashboard_tick(["YOK_DEGISKEN", "NoAddr"])
    assert "yok" in dt._reasons["RPM"]
    assert dt._reasons["Tt2"] == "ECU adresi yok"


def test_ecu_timeout_reason(win, ccp):
    _cfg(win, RPM=Binding(SOURCE_A2L, a2l_name="N_RPM"))
    ccp.power_off()                                  # ECU sessiz
    dt = win.dashboard_tab
    from app.ccp.worker import LOST
    assert _tick_until(win, ["N_RPM"], lambda: win.ccp_session.state == LOST, timeout=6.0)
    win._on_dashboard_tick(["N_RPM"])
    assert "cevap" in dt._reasons["RPM"]


def test_can_sensor_values_and_fault_bit_from_dbc(win):
    dt = win.dashboard_tab
    cfg = DashboardConfig()
    cfg.sensors["RPM"] = SignalMap(value=Binding(SOURCE_CAN, "ENG_STATUS", "rpm"))
    cfg.sensors["Tt2"] = SignalMap(value=Binding(SOURCE_CAN, "ENG_STATUS", "tt2_c"),
                                   fault=Binding(SOURCE_CAN, "ENG_STATUS", "tt2_fault"))
    dt.set_config(cfg)
    win._rebuild_dash_can_map()
    can_id, data, _ext = win.transmit_tab.dbc.encode("ENG_STATUS", {"rpm": 4520, "tt2_c": 38.0, "tt2_fault": 0})
    win._dash_on_can_frame(can_id, data)
    assert dt._values["RPM"][0] == 4520 and dt._values["Tt2"][0] == pytest.approx(38.0, abs=0.1)
    assert dt._faults == {}
    _id, data, _ext = win.transmit_tab.dbc.encode("ENG_STATUS", {"rpm": 4520, "tt2_c": 38.0, "tt2_fault": 1})
    win._dash_on_can_frame(can_id, data)
    assert dt._faults == {"Tt2": "Sensör arızası"}
    assert "1 arıza" in [l.text() for l in dt._health_labels]


@pytest.fixture
def can_out(win, monkeypatch):
    sent = []
    monkeypatch.setattr(type(win.connection), "is_connected", property(lambda s: True))
    monkeypatch.setattr(win.connection, "send", lambda i, d, e: sent.append((i, bytes(d))))
    return sent


def test_can_value_and_sw_in_same_message_do_not_overwrite_each_other(win, can_out):
    """Değer ve _sw aynı mesajdaysa ikinci gönderim ilkini sıfırlamamalı."""
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 45.0, "Pompa değeri")
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"), 1.0, "Pompa anahtarı")
    can_id, data = can_out[-1]
    vals = win.transmit_tab.dbc.get_message("OVERRIDE").decode(data)
    assert vals["pump_dc"] == pytest.approx(45.0, abs=0.1) and vals["pump_dc_sw"] == 1


def test_motor_command_over_can_does_not_carry_other_bits(win, can_out):
    cfg = DashboardConfig()
    cfg.motor_start = MotorCommand(Binding(SOURCE_CAN, "CMD", "start_req"), 1.0)
    cfg.motor_stop = MotorCommand(Binding(SOURCE_CAN, "CMD", "stop_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    win._on_motor_start()
    win._on_motor_stop()
    msg = win.transmit_tab.dbc.get_message("CMD")
    assert msg.decode(can_out[0][1])["start_req"] == 1
    last = msg.decode(can_out[1][1])
    assert last["stop_req"] == 1 and last["start_req"] == 0


def test_motor_commands_work_over_a2l_too(win, ccp):
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw"), 1.0)
    win.dashboard_tab.set_config(cfg)
    assert win.dashboard_tab.estop_button.isEnabled()
    win._on_estop()
    assert ccp.read_memory_bytes(_addr(win, "clbc_Fuel_pump_dc_perc_sw"), 1) == b"\x01"


def test_actuator_override_mixed_sources_value_a2l_sw_can(win, ccp, can_out, monkeypatch):
    """Kullanıcı örneği: clbc_Fuel_pump_dc_perc (A2L) + _sw (CAN) bağımsız kaynaklar."""
    from app.user_roles import Role
    dt = win.dashboard_tab
    cfg = DashboardConfig()
    cfg.actuators["pompa_fuel"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc"),
                                            sw=Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"))
    dt.set_config(cfg)
    dt.set_role(Role.ENGINEER)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    dt._on_actuator_lock("pompa_fuel", True)
    assert dt._act_open["pompa_fuel"]
    assert win.transmit_tab.dbc.get_message("OVERRIDE").decode(can_out[-1][1])["pump_dc_sw"] == 1
    box = dt._act_rows["pompa_fuel"]["control"]               # serbest değer kutusu (yalnızca 0/1 değil)
    box.setText("35")
    box.returnPressed.emit()
    assert struct.unpack("<f", ccp.read_memory_bytes(_addr(win, "clbc_Fuel_pump_dc_perc"), 4))[0] == 35.0
    dt._on_actuator_lock("pompa_fuel", False)
    assert win.transmit_tab.dbc.get_message("OVERRIDE").decode(can_out[-1][1])["pump_dc_sw"] == 0
