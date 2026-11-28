"""Motor Kontrol (Start / Gaz Kolu): CAN ya da A2L DEĞER kutusu, direkt komut (kilit yok); switch (_sw) YOK (yalnızca
Eyleyicilerde var). Ayrıca Ana Sayfa'nın renk/son olaylar bileşenleri."""
import os

import pytest
from PySide6.QtWidgets import QMessageBox

from app.dashboard_config import (
    CONTROL_KEYS, EYLEYICI_KEYS, SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, SignalMap,
    config_from_dict,
)
from app.user_roles import Role

DATA = os.path.join(os.path.dirname(__file__), "data")


# ---------------------------------------------------------------- yapılandırma
def test_control_keys_are_start_and_throttle_and_switches_are_dropped_except_for_actuators():
    from dataclasses import asdict
    cfg = DashboardConfig()
    assert CONTROL_KEYS == ["start", "throttle"]                              # Spark ve Birincil Yakıt kaldırıldı
    assert set(CONTROL_KEYS) <= set(cfg.actuators) and not set(CONTROL_KEYS) & set(EYLEYICI_KEYS)
    assert "spark" not in cfg.actuators and "primary_fuel" not in cfg.actuators
    cfg.actuators["start"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="eng_start"),
                                       sw=Binding(SOURCE_CAN, "CMD", "start_sw"))
    cfg.actuators["valf"] = SignalMap(value=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"),
                                      sw=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw"))
    cfg.sensors["RPM"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="N_RPM"), sw=Binding(SOURCE_A2L, a2l_name="rpm_sw"))
    back = config_from_dict(asdict(cfg))
    assert back.actuators["start"].value == Binding(SOURCE_A2L, a2l_name="eng_start")
    assert not back.actuators["start"].sw.is_set                               # Motor Kontrol: switch temizlenir
    assert not back.sensors["RPM"].sw.is_set and back.sensors["RPM"].value.is_set      # sensör: switch temizlenir
    assert back.actuators["valf"].sw == Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw")  # Eyleyici: switch KALIR


def test_old_config_without_sw_on_motor_commands_still_loads():
    cfg = config_from_dict({"motor_start": {"binding": {"source": "can", "message": "CMD", "signal": "start_req"},
                                            "value": 1}})
    assert cfg.motor_start.binding.is_set and not cfg.motor_start.sw.is_set


# ---------------------------------------------------------------- Ana Sayfa satırları
@pytest.fixture
def win(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.Ok))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a) or QMessageBox.Ok))
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    w._on_dashboard_sources_changed()
    w._info_boxes = shown
    yield w
    w.close()


def _tab(win, role=Role.ENGINEER):
    dt = win.dashboard_tab
    dt.set_role(role)
    calls = []
    dt.writer = lambda binding, value, label: calls.append((binding.text, value)) or True
    return dt, calls


def test_motor_kontrol_rows_are_actuator_rows_separate_from_eyleyiciler(win):
    dt = win.dashboard_tab
    assert set(CONTROL_KEYS) <= set(dt._act_rows) and set(EYLEYICI_KEYS) <= set(dt._act_rows)
    assert set(CONTROL_KEYS) == {"start", "throttle"} and "spark" not in dt._act_rows
    assert dt._act_rows["start"]["kind"] == "valve" and dt._act_rows["throttle"]["kind"] == "valve"
    from app.ui.dash_widgets import ToggleSwitch
    assert not dt.findChildren(ToggleSwitch), "Ana Sayfa'da ON/OFF anahtarı (switch) kalmamalı"
    assert not hasattr(dt.sim_inputs, "control_card")                       # eski doğrudan gönderim kalktı
    from app.sim_interface import FLIGHT_DEFS
    assert set(dt.sim_inputs._ctrl) == {d.key for d in FLIGHT_DEFS}


def test_control_has_no_lock_and_enter_sends_directly(win):
    dt, calls = _tab(win)
    cfg = DashboardConfig()
    cfg.actuators["start"] = SignalMap(value=Binding(SOURCE_CAN, "CMD", "start_req"))
    dt.set_config(cfg)
    assert dt._act_rows["start"]["lock"] is None and dt._act_rows["throttle"]["lock"] is None   # kilit yok
    assert dt._act_rows["start"]["control"].isEnabled()                                          # her zaman etkin
    dt._act_rows["start"]["control"].setText("1")
    dt._on_actuator_submit("start")                                                              # Enter: direkt gider
    assert calls == [("CMD.start_req", 1.0)]
    dt._act_rows["start"]["control"].setText("0")
    dt._on_actuator_submit("start")
    assert calls[-1] == ("CMD.start_req", 0.0)


def test_control_direct_command_is_role_gated_and_needs_mapping(win, monkeypatch):
    dt, calls = _tab(win, Role.OPERATOR)
    cfg = DashboardConfig()
    cfg.actuators["start"] = SignalMap(value=Binding(SOURCE_CAN, "CMD", "start_req"))
    dt.set_config(cfg)
    shown = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(a[1])))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[1])))
    dt._act_rows["start"]["control"].setText("1")
    dt._on_actuator_submit("start")
    assert calls == [] and shown == ["Yetki yok"]                                               # Operatör: gitmez
    dt.set_role(Role.ENGINEER)
    dt._act_rows["throttle"]["control"].setText("40")
    dt._on_actuator_submit("throttle")                                                           # eşleşme yok
    assert calls == [] and shown[-1] == "Eşleşme yok"


def test_control_ignores_any_sw_even_if_present_in_the_config(win):
    """Switch yalnızca Eyleyicilerde çalışır: Motor Kontrol satırında eski bir _sw eşlemesi olsa bile yazılmaz."""
    dt, calls = _tab(win)
    cfg = DashboardConfig()
    cfg.actuators["throttle"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="thr_cmd"),
                                          sw=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw"))
    dt.set_config(cfg)
    dt._act_rows["throttle"]["control"].setText("40")
    dt._on_actuator_submit("throttle")
    assert calls == [("thr_cmd", 40.0)]                                                         # yalnızca değer


def test_control_lock_requests_are_ignored(win):
    dt, calls = _tab(win)
    dt._on_actuator_lock("start", True)
    assert not dt._act_open["start"] and calls == []


def test_eyleyici_still_requires_sw(win):
    dt, calls = _tab(win)
    cfg = DashboardConfig()
    cfg.actuators["valf"] = SignalMap(value=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"))   # sw yok
    dt.set_config(cfg)
    dt._on_actuator_lock("valf", True)
    assert not dt._act_open["valf"]                                                        # Eyleyicide _sw ZORUNLU


# ---------------------------------------------------------------- eski ayarların göçü
def test_legacy_input_map_control_bindings_migrate_to_actuator_model(win):
    win.sim_config.input_map.update({"start": "dbc:CMD.start_req", "altitude": "dbc:AIRCRAFT.altitude"})
    win.sim_config.input_values["start"] = 1.0
    win.dashboard_tab.config.actuators["start"] = SignalMap()
    win._migrate_control_bindings()
    assert win.dashboard_tab.config.actuator_map("start").value == Binding(SOURCE_CAN, "CMD", "start_req")
    assert "start" not in win.sim_config.input_map and "start" not in win.sim_config.input_values
    assert win.sim_config.input_map["altitude"] == "dbc:AIRCRAFT.altitude"                 # uçuş koşulları dokunulmaz


# ---------------------------------------------------------------- eşleşme penceresi
def test_dialog_roundtrips_control_and_command_sw_with_a2l_or_can(win):
    from app.ui.mapping_dialog import MappingDialog
    d = MappingDialog(win.dashboard_tab.config, win.dashboard_tab.sim_inputs, win.transmit_tab.dbc, None, win)
    assert set(d.control_ed["throttle"]) == {"value"}                                      # Motor Kontrol'de switch yok
    d.control_ed["start"]["value"].set_binding(Binding(SOURCE_A2L, a2l_name="eng_start"))
    d.control_ed["throttle"]["value"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"))
    d.motor_ed["motor_start"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"))
    cfg = d.result_config()
    assert cfg.actuators["start"].value == Binding(SOURCE_A2L, a2l_name="eng_start")
    assert cfg.actuators["throttle"].value == Binding(SOURCE_CAN, "OVERRIDE", "pump_dc") and not cfg.actuators["throttle"].sw.is_set
    assert cfg.motor_start.binding == Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd")
    assert cfg.motor_start.value == 1.0 and not cfg.motor_start.sw.is_set          # komutta Değer/Switch yok
    d.close()


# ---------------------------------------------------------------- Ana Sayfa görünümü
def test_gauges_and_cards_have_accent_colors(win):
    from app.ui.dash_widgets import GAUGE_ACCENT
    dt = win.dashboard_tab
    assert len(set(GAUGE_ACCENT.values())) == len(GAUGE_ACCENT)                  # her gösterge ayrı renk
    for key, gc in dt._gauge_cards.items():
        assert gc.gauge._accent == GAUGE_ACCENT[key]
    accents = {w.property("accent") for w in win.dashboard_tab.findChildren(type(dt.sim_inputs.flight_card))
               if w.objectName() == "card"}
    assert {"blue", "green", "orange", "teal"} <= accents


def test_estop_warning_opens_mappings_and_motor_commands_have_only_a_mapping(win, monkeypatch):
    dt = win.dashboard_tab
    opened = []
    monkeypatch.setattr(type(dt), "open_mappings", lambda self: opened.append(1))
    dt.estop_warn.clicked.disconnect()
    dt.estop_warn.clicked.connect(dt.open_mappings)
    dt.estop_warn.click()
    assert opened == [1]                                              # uyarı tıklanınca Eşleşmeler açılır

    from app.ui.mapping_dialog import MappingDialog
    d = MappingDialog(win.dashboard_tab.config, win.dashboard_tab.sim_inputs, win.transmit_tab.dbc, None, win)
    d.motor_ed["estop"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"))
    d._auto_sw()                                                      # yalnızca Eyleyicilerin _sw'si aranır
    assert not hasattr(d, "motor_sw_ed") and d.result_config().estop.binding.text == "OVERRIDE.pump_dc"
    assert not d.motor_ed["motor_stop"].text()                        # komutun KENDİSİ otomatik bağlanmaz
    d.close()
