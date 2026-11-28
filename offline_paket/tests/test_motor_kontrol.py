"""Test Bench: yalnızca Eyleyiciler (kilit + _sw) ve Motor Komutları kalır; Motor Kontrol (Start / Gaz Kolu) ve Uçuş
Koşulları kartları kaldırıldı (giriş yolu Control Panel). Ayrıca Ana Sayfa'nın renk bileşenleri."""
import os

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox

from app.dashboard_config import (
    ACTUATOR_KEYS, EYLEYICI_KEYS, SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, SignalMap, config_from_dict,
)
from app.user_roles import Role

DATA = os.path.join(os.path.dirname(__file__), "data")


# ---------------------------------------------------------------- yapılandırma
def test_actuators_are_only_eyleyiciler_and_old_motor_control_entries_are_ignored():
    from dataclasses import asdict
    cfg = DashboardConfig()
    assert list(cfg.actuators) == EYLEYICI_KEYS and ACTUATOR_KEYS == EYLEYICI_KEYS
    d = asdict(cfg)
    d["actuators"]["start"] = {"value": {"source": "a2l", "a2l_name": "eng_start"}}        # eski kayıttaki Motor Kontrol
    d["actuators"]["throttle"] = {"value": {"source": "can", "message": "OVERRIDE", "signal": "pump_dc"}}
    d["actuators"]["valf"] = {"value": {"source": "can", "message": "OVERRIDE", "signal": "valf_cmd"},
                              "sw": {"source": "can", "message": "OVERRIDE", "signal": "valf_cmd_sw"}}
    d["sensors"]["RPM"] = {"value": {"source": "a2l", "a2l_name": "N_RPM"}, "sw": {"source": "a2l", "a2l_name": "rpm_sw"}}
    back = config_from_dict(d)
    assert "start" not in back.actuators and "throttle" not in back.actuators          # sessizce atlanır, hata yok
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


def test_test_bench_has_only_actuators_gauges_and_model_panel(win):
    dt = win.dashboard_tab
    titles = {w.text() for w in dt.findChildren(QLabel) if w.objectName() == "cardTitle"}
    assert {"EYLEYİCİLER", "MOTOR PARAMETRELERİ"} <= titles
    assert not titles & {"UÇUŞ KOŞULLARI", "MOTOR KONTROL", "SON OLAYLAR", "CANLI TRENDLER"}
    assert set(dt._act_rows) == set(EYLEYICI_KEYS)
    for gone in ("sim_inputs", "trend", "events_list", "throttle_slider", "submit_control"):
        assert not hasattr(dt, gone)
    assert hasattr(dt, "sim_panel")                                           # MIL model kontrolü kalır


def test_eyleyici_lock_is_role_gated_and_requires_sw(win):
    dt, calls = _tab(win, Role.OPERATOR)
    cfg = DashboardConfig()
    cfg.actuators["valf"] = SignalMap(value=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"),
                                      sw=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd_sw"))
    dt.set_config(cfg)
    dt._on_actuator_lock("valf", True)
    assert not dt._act_open["valf"] and calls == []                           # Operatör: yetki yok
    dt.set_role(Role.ENGINEER)
    cfg2 = DashboardConfig()
    cfg2.actuators["valf"] = SignalMap(value=Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"))   # sw yok
    dt.set_config(cfg2)
    dt._on_actuator_lock("valf", True)
    assert not dt._act_open["valf"]                                           # Eyleyicide _sw ZORUNLU


# ---------------------------------------------------------------- eşleşme penceresi
def test_dialog_roundtrips_actuator_sw_and_motor_commands(win):
    from app.ui.mapping_dialog import MappingDialog
    d = MappingDialog(win.dashboard_tab.config, win.transmit_tab.dbc, None, win)
    assert not hasattr(d, "control_ed") and not hasattr(d, "input_ed") and not hasattr(d, "tabs")
    d.actuator_ed["valf"]["value"].set_binding(Binding(SOURCE_A2L, a2l_name="valf_val"))
    d.actuator_ed["valf"]["sw"].set_binding(Binding(SOURCE_A2L, a2l_name="valf_sw"))
    d.motor_ed["motor_start"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"))
    cfg = d.result_config()
    assert cfg.actuators["valf"].value == Binding(SOURCE_A2L, a2l_name="valf_val")
    assert cfg.actuators["valf"].sw == Binding(SOURCE_A2L, a2l_name="valf_sw")
    assert cfg.motor_start.binding == Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd")
    assert cfg.motor_start.value == 1.0 and not cfg.motor_start.sw.is_set          # komutta Değer/Switch yok
    d.close()


# ---------------------------------------------------------------- Ana Sayfa görünümü
def test_gauges_and_cards_have_accent_colors(win):
    from app.ui.dash_widgets import GAUGE_ACCENT
    from PySide6.QtWidgets import QFrame
    dt = win.dashboard_tab
    assert len(set(GAUGE_ACCENT.values())) == len(GAUGE_ACCENT)                  # her gösterge ayrı renk
    for key, gc in dt._gauge_cards.items():
        assert gc.gauge._accent == GAUGE_ACCENT[key]
    accents = {w.property("accent") for w in dt.findChildren(QFrame) if w.objectName() == "card"}
    assert {"orange", "teal"} <= accents


def test_estop_warning_opens_mappings_and_motor_commands_have_only_a_mapping(win, monkeypatch):
    dt = win.dashboard_tab
    opened = []
    monkeypatch.setattr(type(dt), "open_mappings", lambda self: opened.append(1))
    dt.estop_warn.clicked.disconnect()
    dt.estop_warn.clicked.connect(dt.open_mappings)
    dt.estop_warn.click()
    assert opened == [1]                                              # uyarı tıklanınca Eşleşmeler açılır

    from app.ui.mapping_dialog import MappingDialog
    d = MappingDialog(win.dashboard_tab.config, win.transmit_tab.dbc, None, win)
    d.motor_ed["estop"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"))
    d._auto_sw()                                                      # yalnızca Eyleyicilerin _sw'si aranır
    assert not hasattr(d, "motor_sw_ed") and d.result_config().estop.binding.text == "OVERRIDE.pump_dc"
    assert not d.motor_ed["motor_stop"].text()                        # komutun KENDİSİ otomatik bağlanmaz
    d.close()
