"""_sw kapısı: anahtar 0 iken değer yazılamaz; kilit açılınca önce DEĞER sonra ANAHTAR yazılır."""
import pytest
from PySide6.QtWidgets import QMessageBox

from app.dashboard_config import SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, SignalMap
from app.user_roles import Role


@pytest.fixture
def tab(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    from app.ui.dashboard_tab import DashboardTab
    t = DashboardTab()
    t.calls = []
    t.writer = lambda b, v, label: (t.calls.append((b.text, v)), True)[1]
    cfg = DashboardConfig()
    cfg.actuators["valf"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="valf_cmd"),
                                      sw=Binding(SOURCE_CAN, "OVR", "valf_cmd_sw"))
    cfg.actuators["pompa_fuel"] = SignalMap(value=Binding(SOURCE_CAN, "OVR", "pump"),
                                            sw=Binding(SOURCE_CAN, "OVR", "pump_sw"))
    cfg.sensors["RPM"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="rpm"),
                                   sw=Binding(SOURCE_A2L, a2l_name="rpm_sw"))
    t.set_config(cfg)
    t.set_role(Role.ENGINEER)
    return t


def test_locked_actuator_controls_are_disabled_and_write_nothing(tab):
    row = tab._act_rows["valf"]
    assert not row["control"].isEnabled()
    row["control"].setValue(30.0)           # kilitliyken sinyal yok
    assert tab.calls == []


def test_unlock_writes_value_first_then_sw_and_enables_control(tab):
    tab._act_rows["valf"]["control"].setValue(0.0)
    tab._on_actuator_lock("valf", True)
    assert tab.calls == [("valf_cmd", 0.0), ("OVR.valf_cmd_sw", 1.0)]
    assert tab._act_rows["valf"]["control"].isEnabled()
    tab._act_rows["valf"]["control"].setValue(45.0)
    assert tab.calls[-1] == ("valf_cmd", 45.0)


def test_lock_again_writes_sw_zero_and_disables(tab):
    tab._on_actuator_lock("valf", True)
    tab.calls.clear()
    tab._on_actuator_lock("valf", False)
    assert tab.calls == [("OVR.valf_cmd_sw", 0.0)]
    assert not tab._act_rows["valf"]["control"].isEnabled()
    tab._act_rows["valf"]["control"].setValue(70.0)
    assert tab.calls == [("OVR.valf_cmd_sw", 0.0)]


def test_actuator_sends_0_to_100_value_only_when_unlocked(tab):
    spin = tab._act_rows["pompa_fuel"]["control"]
    spin.setValue(40.0)
    assert tab.calls == []                   # kilitli: gönderim yok
    spin.setValue(0.0)
    tab._on_actuator_lock("pompa_fuel", True)
    tab.calls.clear()
    spin.setValue(55.5)
    spin.setValue(100.0)
    spin.setValue(0.0)
    assert tab.calls == [("OVR.pump", 55.5), ("OVR.pump", 100.0), ("OVR.pump", 0.0)]


def test_operator_role_cannot_unlock(tab):
    tab.set_role(Role.OPERATOR)
    tab._on_actuator_lock("valf", True)
    assert tab.calls == []
    assert not tab._act_open["valf"]


def test_unbound_sw_cannot_unlock(tab):
    tab._on_actuator_lock("glow_plug", True)
    assert tab.calls == [] and not tab._act_open["glow_plug"]


def test_failed_write_keeps_lock_closed(tab):
    tab.writer = lambda b, v, label: False
    tab._on_actuator_lock("valf", True)
    assert not tab._act_open["valf"]
    assert not tab._act_rows["valf"]["lock"].is_open


def test_sensor_unlock_writes_current_value_then_sw(tab):
    tab.set_gauge_value("RPM", 4520.0)
    tab._on_sensor_lock("RPM", True)
    assert tab.calls == [("rpm", 4520.0), ("rpm_sw", 1.0)]
    assert tab._gauge_cards["RPM"].lock.is_open
    tab.calls.clear()
    tab._on_sensor_lock("RPM", False)
    assert tab.calls == [("rpm_sw", 0.0)]


def test_home_tab_cannot_be_closed_or_moved(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    assert w.nav_bar.tabText(0) == "Ana Sayfa"
    assert not w.nav_bar.tabsClosable() and not w.nav_bar.isMovable()
    assert w.stack.widget(0) is w.dashboard_tab        # kaydırma sarmalayıcısı yok


def test_sensor_health_lists_faulty_sensor_with_reason(tab):
    tab.set_sensor_fault("Tt2", "Açık devre")
    labels = [l.text() for l in tab._health_labels]
    assert "1 arıza" in labels and any("Tt2" in t and "Açık devre" in t for t in labels)
    tab.set_sensor_fault("Tt2", None)
    assert [l.text() for l in tab._health_labels] == ["Arıza yok"]
