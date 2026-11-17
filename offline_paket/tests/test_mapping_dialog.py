import os

import pytest

from app.dashboard_config import SOURCE_A2L, SOURCE_CAN, Binding
from app.ui.mapping_dialog import BindingEditor, MappingDialog, find_companion, split_can

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_split_can_and_companion_lookup():
    assert split_can("OVERRIDE.pump_dc") == ("OVERRIDE", "pump_dc")
    assert find_companion("clbc_Fuel_pump_dc_perc", SOURCE_A2L, ["x", "CLBC_FUEL_PUMP_DC_PERC_SW"]) == "CLBC_FUEL_PUMP_DC_PERC_SW"
    assert find_companion("OVERRIDE.pump_dc", SOURCE_CAN, ["OVERRIDE.pump_dc", "OVERRIDE.pump_dc_sw"]) == "OVERRIDE.pump_dc_sw"
    assert find_companion("a", SOURCE_A2L, ["b"]) is None


def test_binding_editor_roundtrip_can_and_a2l(qapp):
    ed = BindingEditor(["ENG.rpm", "ENG.tt2"], ["N_RPM", "Tt2_raw"])
    ed.set_binding(Binding(SOURCE_CAN, "ENG", "rpm"))
    assert ed.binding() == Binding(SOURCE_CAN, "ENG", "rpm")
    ed.set_binding(Binding(SOURCE_A2L, a2l_name="N_RPM"))
    assert ed.source_kind() == SOURCE_A2L and ed.binding() == Binding(SOURCE_A2L, a2l_name="N_RPM")
    ed.source.setCurrentIndex(0)                    # kaynak CAN'a dönünce A2L adı taşınmaz
    assert ed.binding().source == SOURCE_CAN


@pytest.fixture
def dlg(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
    w._on_dashboard_sources_changed()
    w.dashboard_tab.sim_inputs.refresh_sources(w.transmit_tab.dbc)
    d = MappingDialog(w.dashboard_tab.config, w.dashboard_tab.sim_inputs, w.transmit_tab.dbc,
                      w.a2l_tab.db.summary, w)
    yield w, d
    w.close()


def test_switch_column_exists_only_for_actuators(dlg):
    w, d = dlg
    assert set(d.sensor_ed["RPM"]) == {"value", "fault"}                             # sensörde switch yok
    assert set(d.actuator_ed["pompa_fuel"]) == {"value", "sw"}                        # switch YALNIZCA Eyleyicilerde
    assert set(d.control_ed) == {"start", "throttle"}                                # Spark / Birincil Yakıt kaldırıldı
    assert set(d.control_ed["start"]) == {"value"}                                   # Motor Kontrol'de switch yok
    assert set(d.motor_ed) == {"motor_start", "motor_stop", "estop"}                  # komutlarda yalnızca eşleme (Değer/Switch yok)
    assert not hasattr(d, "motor_sw_ed")
    assert [d.tabs.tabText(i) for i in range(d.tabs.count())] == ["Sinyaller", "Uçuş Koşulları"]


def test_result_config_keeps_independent_sources_and_auto_sw(dlg):
    w, d = dlg
    ed = d.actuator_ed["pompa_fuel"]
    ed["value"].set_binding(Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc"))
    d._auto_sw()                                    # aynı kaynakta _sw bulunur
    assert ed["sw"].binding() == Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw")
    d.actuator_ed["valf"]["value"].set_binding(Binding(SOURCE_CAN, "OVERRIDE", "valf_cmd"))
    d.actuator_ed["valf"]["sw"].set_binding(Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw"))
    d.motor_ed["estop"].set_binding(Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw"))
    cfg = d.result_config()
    assert cfg.actuators["valf"].value.source == SOURCE_CAN and cfg.actuators["valf"].sw.source == SOURCE_A2L
    assert cfg.estop.binding.source == SOURCE_A2L


def test_input_tab_saves_dbc_mapping_for_flight_and_control(dlg):
    w, d = dlg
    d._auto_inputs()
    d.input_ed["altitude"].set_binding(Binding(SOURCE_CAN, "AIRCRAFT", "altitude"))
    d.accept()
    assert w.dashboard_tab.sim_inputs.config.input_map["altitude"] == "dbc:AIRCRAFT.altitude"
    assert w.dashboard_tab.sim_inputs.mapped("altitude") == ("AIRCRAFT", "altitude")


def test_flight_inputs_are_sent_over_can_from_the_panel(qapp, monkeypatch):
    from app.user_roles import Role
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    w._on_dashboard_sources_changed()
    panel = w.dashboard_tab.sim_inputs
    panel.refresh_sources(w.transmit_tab.dbc)
    assert panel.mapped("altitude") == ("AIRCRAFT", "altitude")      # isimden otomatik eşleşti
    assert panel.mapped("ma") == ("AIRCRAFT", "mach")
    w.current_role = Role.ENGINEER
    panel.set_allowed(True)
    monkeypatch.setattr(type(w.connection), "is_connected", property(lambda s: True))
    got = []
    monkeypatch.setattr(w.tx_scheduler, "set_values", lambda msg, vals, *a, **k: got.append((msg, dict(vals))))
    panel.send_value("altitude", 8.2)
    assert got == [("AIRCRAFT", {"altitude": 8.2})]
    w.close()


def test_alfa_beta_are_enabled_and_sent_over_can(qapp, monkeypatch):
    from app.user_roles import Role
    from app.ui.main_window import MainWindow
    w = MainWindow()
    panel = w.dashboard_tab.sim_inputs
    panel.config.input_map.update({"alfa": "dbc:AIRCRAFT.altitude", "beta": "dbc:AIRCRAFT.mach"})
    w.current_role = Role.ENGINEER
    panel.set_allowed(True)
    assert panel._ctrl["alfa"]["w"].isEnabled() and panel._ctrl["beta"]["w"].isEnabled()
    panel.refresh_sources(w.transmit_tab.dbc)
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    panel.refresh_sources(w.transmit_tab.dbc)
    assert {"alfa", "beta"} <= set(panel.sendable_keys())
    w.close()


def test_dialog_is_dark_scoped_and_message_boxes_stay_light(dlg):
    from PySide6.QtWidgets import QMessageBox, QWidget
    w, d = dlg
    body = d.findChild(QWidget, "mapBody")
    assert body is not None and "#FFFFFF" in body.styleSheet()          # koyu stil yalnızca gövdede
    assert "mapBody" not in d.styleSheet()                              # iletişim kutusunun kendisinde yalnız zemin rengi
    box = QMessageBox(d)                                                # açık tema korunur (okunaklı kalır)
    assert box.styleSheet() == "" and not body.isAncestorOf(box)
