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
    d = MappingDialog(w.dashboard_tab.config, w.transmit_tab.dbc, w.a2l_tab.db.summary, w)
    yield w, d
    w.close()


def test_switch_column_exists_only_for_actuators(dlg):
    w, d = dlg
    assert set(d.sensor_ed["RPM"]) == {"value", "fault"}                             # sensörde switch yok
    assert set(d.actuator_ed["pompa_fuel"]) == {"value", "sw"}                        # switch YALNIZCA Eyleyicilerde
    assert not hasattr(d, "control_ed") and not hasattr(d, "input_ed")               # Motor Kontrol ve Uçuş Koşulları kalktı
    assert set(d.motor_ed) == {"motor_start", "motor_stop", "estop"}                  # komutlarda yalnızca eşleme (Değer/Switch yok)
    assert not hasattr(d, "motor_sw_ed")
    assert not hasattr(d, "tabs")                                                    # tek sayfa: Sinyaller


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


def test_dialog_is_dark_scoped_and_message_boxes_stay_light(dlg):
    from PySide6.QtWidgets import QMessageBox, QWidget
    w, d = dlg
    body = d.findChild(QWidget, "mapBody")
    assert body is not None and "#FFFFFF" in body.styleSheet()          # koyu stil yalnızca gövdede
    assert "mapBody" not in d.styleSheet()                              # iletişim kutusunun kendisinde yalnız zemin rengi
    box = QMessageBox(d)                                                # açık tema korunur (okunaklı kalır)
    assert box.styleSheet() == "" and not body.isAncestorOf(box)


def test_binding_editor_wheel_does_not_change_mapping(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    ed = BindingEditor(["ENG.rpm", "ENG.tt2"], ["N_RPM", "Tt2_raw"])
    ed.set_binding(Binding(SOURCE_CAN, "ENG", "rpm"))
    before = (ed.source.currentIndex(), ed.name.currentText())
    for w in (ed.source, ed.name):
        for dy in (-120, 120):
            ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy), Qt.NoButton,
                             Qt.NoModifier, Qt.NoScrollPhase, False)
            qapp.sendEvent(w, ev)
    assert (ed.source.currentIndex(), ed.name.currentText()) == before


def test_editors_share_one_name_model_per_source_and_use_uniform_rows(qapp):
    """Pencere geç açılıyordu: her editör tüm adları kopyalıyor, her kutu tüm öğeleri ölçüyordu."""
    from app.ui.mapping_dialog import make_pools
    pools = make_pools(["ENG.rpm", "ENG.tt2"], ["N_RPM", "Tt2_raw"])
    a = BindingEditor(["ENG.rpm", "ENG.tt2"], ["N_RPM", "Tt2_raw"], pools=pools)
    b = BindingEditor(["ENG.rpm", "ENG.tt2"], ["N_RPM", "Tt2_raw"], pools=pools)
    assert a.name.model() is b.name.model() is pools[SOURCE_CAN]
    assert a.name.view().uniformItemSizes()
    a.set_binding(Binding(SOURCE_A2L, a2l_name="N_RPM"))
    assert a.name.model() is pools[SOURCE_A2L] and a.binding() == Binding(SOURCE_A2L, a2l_name="N_RPM")
    assert b.name.model() is pools[SOURCE_CAN]                                       # diğer editör etkilenmez
    a.set_binding(Binding(SOURCE_CAN, "ENG", "tt2"))
    assert a.name.model() is pools[SOURCE_CAN] and a.binding() == Binding(SOURCE_CAN, "ENG", "tt2")
    assert a.name.findText("ENG.rpm") > 0 and a.name.itemText(0) == ""


def test_mapping_dialog_has_a_row_for_each_fuel_pressure_gauge(dlg):
    w, d = dlg
    assert {"FP_start", "FP_main"} <= set(d.sensor_ed) and "FP" not in d.sensor_ed
    d.sensor_ed["FP_start"]["value"].set_binding(Binding(SOURCE_A2L, a2l_name="FP_bar"))
    cfg = d.result_config()
    assert cfg.sensors["FP_start"].value == Binding(SOURCE_A2L, a2l_name="FP_bar")
    assert not cfg.sensors["FP_main"].value.is_set
