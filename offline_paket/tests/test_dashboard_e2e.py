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
    assert dt._gauge_cards["RPM"].gauge.fraction() == pytest.approx(4520 / 140000)   # ibre hareket eder (0-140.000 ölçek)


def test_reasons_are_shown_when_value_cannot_be_read(win):
    dt = win.dashboard_tab
    _cfg(win, RPM=Binding(SOURCE_A2L, a2l_name="N_RPM"))
    win._on_dashboard_tick(["N_RPM"])                       # CCP bağlı değil
    assert dt._reasons["RPM"] == "CCP bağlı değil"
    assert dt._gauge_cards["RPM"].status.text() == "CCP bağlı değil"


def test_missing_a2l_name_and_missing_address_reasons(win, ccp):
    dt = win.dashboard_tab
    _cfg(win, RPM=Binding(SOURCE_A2L, a2l_name="YOK_DEGISKEN"), Ps3=Binding(SOURCE_A2L, a2l_name="NoAddr"))
    win._on_dashboard_tick(["YOK_DEGISKEN", "NoAddr"])
    assert "yok" in dt._reasons["RPM"]
    assert dt._reasons["Ps3"] == "ECU adresi yok"


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
    cfg.sensors["Ps3"] = SignalMap(value=Binding(SOURCE_CAN, "ENG_STATUS", "tt2_c"),
                                   fault=Binding(SOURCE_CAN, "ENG_STATUS", "tt2_fault"))
    dt.set_config(cfg)
    win._rebuild_dash_can_map()
    can_id, data, _ext = win.transmit_tab.dbc.encode("ENG_STATUS", {"rpm": 4520, "tt2_c": 38.0, "tt2_fault": 0})
    win._dash_on_can_frame(can_id, data)
    assert dt._values["RPM"][0] == 4520 and dt._values["Ps3"][0] == pytest.approx(38.0, abs=0.1)
    assert dt._faults == {}
    _id, data, _ext = win.transmit_tab.dbc.encode("ENG_STATUS", {"rpm": 4520, "tt2_c": 38.0, "tt2_fault": 1})
    win._dash_on_can_frame(can_id, data)
    assert dt._faults == {"Ps3": "Sensör arızası"}
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


def _hata(win):
    return [e.message for e in win.event_log.entries if e.category == "HATA"]


def _motor_notes(win):
    return [e.message for e in win.event_log.entries if e.category == "MOTOR"]


# Motor komutları (Başlat / Durdur / Acil Durdurma) basılınca eşlenen sinyale SABİT 1 yazar; Değer ve Switch yoktur.
# Güvenlik komutlarının (Durdur / Acil Durdurma) A2L/DBC sınırını aşabilmesi ve bit genişliğini yine de denetlemesi
# artık komut değeri yapılandırılamadığı için DOĞRUDAN yazma yolundan (_write_binding safety=True) sınanır.
def test_safety_write_over_a2l_is_not_blocked_by_a2l_limits_but_normal_writes_are(win, ccp):
    """clbc_Fuel_pump_dc_perc_sw: UBYTE, A2L sınırı 0..1. Güvenlik yazımı 5 sınır dışı olsa da gider; normal yazım reddedilir."""
    name = "clbc_Fuel_pump_dc_perc_sw"
    addr = _addr(win, name)
    b = Binding(SOURCE_A2L, a2l_name=name)
    assert win._write_binding(b, 5.0, "Motor Başlat", merge=False, safety=False) is False       # normal: sınır açık
    assert ccp.read_memory_bytes(addr, 1) == b"\x00"
    assert any("Motor Başlat A2L yazılamadı" in m for m in _hata(win))
    assert win._write_binding(b, 5.0, "ACİL DURDURMA", merge=False, safety=True) is True          # güvenlik: sınır atlanır
    assert ccp.read_memory_bytes(addr, 1) == b"\x05"
    assert any("güvenlik komutu olduğu için atlandı" in m for m in _motor_notes(win))


def test_safety_write_over_a2l_still_rejects_value_that_does_not_fit_the_datatype(win, ccp):
    name = "clbc_Fuel_pump_dc_perc_sw"                  # UBYTE: 300 sığmaz
    addr = _addr(win, name)
    assert win._write_binding(Binding(SOURCE_A2L, a2l_name=name), 300.0, "ACİL DURDURMA", merge=False, safety=True) is False
    assert ccp.read_memory_bytes(addr, 1) == b"\x00"
    assert any("ACİL DURDURMA A2L yazılamadı" in m for m in _hata(win))


def test_safety_write_over_can_is_not_blocked_by_dbc_limits_but_normal_writes_are(win, can_out):
    """OVERRIDE.valf_cmd: 16 bit, DBC sınırı 0..100. 150 bit genişliğine sığar: güvenlik yazımı gider, normal gitmez."""
    b = Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd")
    assert win._write_binding(b, 150.0, "Motor Başlat", merge=False, safety=False) is False
    assert can_out == []
    assert any("Motor Başlat gönderilemedi" in m for m in _hata(win))
    assert win._write_binding(b, 150.0, "ACİL DURDURMA", merge=False, safety=True) is True
    assert len(can_out) >= 1
    vals = win.transmit_tab.dbc.get_message("OVERRIDE").decode(can_out[0][1], decode_choices=False)
    assert vals["valf_cmd"] == pytest.approx(150.0, abs=0.1)
    assert any("DBC sınır denetimi güvenlik komutu olduğu için atlandı" in m for m in _motor_notes(win))


def test_safety_write_over_can_still_rejects_value_that_does_not_fit_the_bit_width(win, can_out):
    b = Binding(SOURCE_CAN, "CMD", "estop_req")                                  # 1 bit
    assert win._write_binding(b, 5.0, "ACİL DURDURMA", merge=False, safety=True) is False
    assert can_out == []
    assert any("ACİL DURDURMA gönderilemedi" in m for m in _hata(win))


def test_motor_commands_send_a_fixed_1_with_no_value_or_switch(win, ccp, can_out):
    """Eski kayıtta Değer/Switch olsa bile basınca yalnızca eşlenen sinyale 1 yazılır (tek kare, _sw yok)."""
    cfg = DashboardConfig()
    cfg.motor_start = MotorCommand(Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"), 50.0,           # eski: değer 50 + _sw
                                   sw=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw"))
    cfg.estop = MotorCommand(Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw"), 7.0,
                             sw=Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"))
    win.dashboard_tab.set_config(cfg)
    win._on_motor_start()
    assert len(can_out) == 1                                                     # tek kare: _sw için ikinci kare YOK
    v = win.transmit_tab.dbc.get_message("OVERRIDE").decode(can_out[0][1], decode_choices=False)
    assert v["valf_cmd"] == pytest.approx(1.0, abs=0.1) and v["valf_cmd_sw"] == 0
    win._on_estop()
    assert ccp.read_memory_bytes(_addr(win, "clbc_Fuel_pump_dc_perc_sw"), 1) == b"\x01"   # 7 değil, 1
    assert len(can_out) == 1                                                     # estop'un eski _sw'si gönderilmedi
    assert any("ACİL DURDURMA gönderildi (clbc_Fuel_pump_dc_perc_sw=1)" in m for m in _motor_notes(win))


def test_motor_command_not_mapped_is_reported_and_nothing_is_sent(win, can_out):
    win.dashboard_tab.set_config(DashboardConfig())
    assert win._send_motor_command("Motor Start", win.dashboard_tab.config.motor_start) is False
    assert can_out == [] and any("Motor Start GÖNDERİLEMEDİ" in m for m in _hata(win))



def test_safety_command_repeats_the_same_frame_five_times(win, can_out):
    from PySide6.QtTest import QTest
    cfg = DashboardConfig()
    cfg.motor_stop = MotorCommand(Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"))
    win.dashboard_tab.set_config(cfg)
    win._on_motor_stop()
    end = 0
    while len(can_out) < 5 and end < 5000:
        QTest.qWait(20)
        end += 20
    assert len(can_out) == 5 and len(set(can_out)) == 1                          # ilk kare + 4 tekrar: AYNI kare
    v = win.transmit_tab.dbc.get_message("OVERRIDE").decode(can_out[0][1], decode_choices=False)
    assert v["valf_cmd"] == pytest.approx(1.0, abs=0.1) and v["valf_cmd_sw"] == 0     # sabit 1, _sw yok


def test_dbc_encode_strict_default_rejects_out_of_range_and_non_strict_allows_it(win):
    dbc = win.transmit_tab.dbc
    with pytest.raises(ValueError):
        dbc.encode("OVERRIDE", {"valf_cmd": 150.0})                  # varsayılan strict: davranış aynı
    can_id, data, _ext = dbc.encode("OVERRIDE", {"valf_cmd": 150.0}, strict=False)
    assert can_id == 0x200 and len(data) > 0
    with pytest.raises(ValueError):
        dbc.encode("CMD", {"estop_req": 5.0}, strict=False)          # bit genişliği her halde denetlenir


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
