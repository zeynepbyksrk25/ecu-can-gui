"""Motor Kontrol (Start/Spark/Gaz Kolu/Birincil Yakıt) ve Motor Komutları artık Eyleyiciler gibi çalışır:
değer + (isteğe bağlı) _sw, CAN ya da A2L, kilitle açılır; ayrıca Ana Sayfa'nın renk/son olaylar bileşenleri."""
import os

import pytest
from PySide6.QtWidgets import QMessageBox

from app.dashboard_config import (
    CONTROL_KEYS, EYLEYICI_KEYS, SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, MotorCommand, SignalMap,
    config_from_dict,
)
from app.user_roles import Role

DATA = os.path.join(os.path.dirname(__file__), "data")


# ---------------------------------------------------------------- yapılandırma
def test_control_keys_follow_actuator_model_and_roundtrip():
    from dataclasses import asdict
    cfg = DashboardConfig()
    assert set(CONTROL_KEYS) <= set(cfg.actuators) and not set(CONTROL_KEYS) & set(EYLEYICI_KEYS)
    cfg.actuators["start"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="eng_start"),
                                       sw=Binding(SOURCE_CAN, "CMD", "start_sw"))
    cfg.motor_stop = MotorCommand(Binding(SOURCE_CAN, "CMD", "stop_req"), 1.0, sw=Binding(SOURCE_A2L, a2l_name="stop_sw"))
    back = config_from_dict(asdict(cfg))
    assert back.actuators["start"].value == Binding(SOURCE_A2L, a2l_name="eng_start")
    assert back.actuators["start"].sw == Binding(SOURCE_CAN, "CMD", "start_sw")
    assert back.motor_stop.sw == Binding(SOURCE_A2L, a2l_name="stop_sw")


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
    assert dt._act_rows["start"]["kind"] == "toggle" and dt._act_rows["throttle"]["kind"] == "valve"
    assert not hasattr(dt.sim_inputs, "control_card")                       # eski doğrudan gönderim kalktı
    from app.sim_interface import FLIGHT_DEFS
    assert set(dt.sim_inputs._ctrl) == {d.key for d in FLIGHT_DEFS}


def test_control_unlock_needs_value_mapping_only_and_is_role_gated(win, monkeypatch):
    dt, calls = _tab(win, Role.OPERATOR)
    cfg = DashboardConfig()
    cfg.actuators["start"] = SignalMap(value=Binding(SOURCE_CAN, "CMD", "start_req"))      # _sw YOK
    dt.set_config(cfg)
    dt._on_actuator_lock("start", True)
    assert not dt._act_open["start"] and calls == []                                       # Operatör: açılmaz
    dt.set_role(Role.ENGINEER)
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))   # onay
    dt._on_actuator_lock("start", True)
    assert dt._act_open["start"] and calls == []                                           # değer yazılmadı, sw yok


def test_control_without_sw_writes_value_and_zero_on_lock(win, monkeypatch):
    dt, calls = _tab(win)
    cfg = DashboardConfig()
    cfg.actuators["spark"] = SignalMap(value=Binding(SOURCE_CAN, "CMD", "start_req"))
    dt.set_config(cfg)
    dt._on_actuator_lock("spark", True)
    dt._act_rows["spark"]["control"].setChecked(True)                                      # ON
    assert calls[-1] == ("CMD.start_req", 1.0)
    dt._on_actuator_lock("spark", False)                                                   # kilitle -> değer 0'a çekilir
    assert calls[-1] == ("CMD.start_req", 0.0)
    assert not dt._act_rows["spark"]["control"].isChecked() and not dt._act_open["spark"]


def test_control_with_sw_follows_actuator_order_and_sources_can_differ(win):
    dt, calls = _tab(win)
    cfg = DashboardConfig()
    cfg.actuators["throttle"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="thr_cmd"),
                                          sw=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw"))
    dt.set_config(cfg)
    box = dt._act_rows["throttle"]["control"]
    box.setText("40")
    dt._on_actuator_lock("throttle", True)
    assert calls == [("thr_cmd", 40.0), ("OVERRIDE.valf_cmd_sw", 1.0)]                    # önce değer, sonra _sw=1
    calls.clear()
    dt._on_actuator_lock("throttle", False)
    assert calls == [("OVERRIDE.valf_cmd_sw", 0.0)]                                        # _sw=0


def test_control_not_mapped_shows_message_and_stays_locked(win):
    dt, calls = _tab(win)
    dt.set_config(DashboardConfig())
    dt._on_actuator_lock("start", True)
    assert not dt._act_open["start"] and calls == [] and win._info_boxes


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
    d.control_ed["start"]["value"].set_binding(Binding(SOURCE_A2L, a2l_name="eng_start"))
    d.control_ed["throttle"]["value"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"))
    d.control_ed["throttle"]["sw"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"))
    d.motor_ed["motor_start"][0].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"))
    d.motor_ed["motor_start"][1].setValue(1.0)
    d.motor_sw_ed["motor_start"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw"))
    cfg = d.result_config()
    assert cfg.actuators["start"].value == Binding(SOURCE_A2L, a2l_name="eng_start")
    assert cfg.actuators["throttle"].sw == Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw")
    assert cfg.motor_start.sw == Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw")
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
    assert {"blue", "green", "orange", "teal", "slate"} <= accents


def test_recent_events_card_is_newest_first_capped_and_colored(win):
    dt = win.dashboard_tab
    win._log_event("MOTOR", "birinci")
    win._log_event("HATA", "ikinci")
    assert dt.events_list.item(0).text().endswith("HATA  ·  ikinci")             # en yeni üstte
    assert dt.events_list.item(0).foreground().color().name() == "#c22a1d"
    assert not dt.events_empty.isVisibleTo(dt)
    for i in range(dt.EVENT_MAX + 20):
        win._log_event("AYAR", f"olay {i}")
    assert dt.events_list.count() == dt.EVENT_MAX


def test_estop_warning_opens_mappings_and_auto_sw_covers_motor_commands(win, monkeypatch):
    dt = win.dashboard_tab
    opened = []
    monkeypatch.setattr(type(dt), "open_mappings", lambda self: opened.append(1))
    dt.estop_warn.clicked.disconnect()
    dt.estop_warn.clicked.connect(dt.open_mappings)
    dt.estop_warn.click()
    assert opened == [1]                                              # uyarı tıklanınca Eşleşmeler açılır

    from app.ui.mapping_dialog import MappingDialog
    d = MappingDialog(win.dashboard_tab.config, win.dashboard_tab.sim_inputs, win.transmit_tab.dbc, None, win)
    d.motor_ed["estop"][0].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"))
    d._auto_sw()                                                      # _sw, komutun ADINDAN bulunur
    assert d.motor_sw_ed["estop"].binding() == Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw")
    assert not d.motor_ed["motor_stop"][0].text()                     # komutun KENDİSİ otomatik bağlanmaz
    d.close()
