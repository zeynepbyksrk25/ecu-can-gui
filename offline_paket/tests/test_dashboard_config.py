from app.dashboard_config import (
    ACTUATOR_KEYS, SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, DashboardConfigStore, SignalMap,
    config_from_dict,
)


def test_legacy_measurement_fields_migrate_to_a2l_sensor_bindings():
    cfg = config_from_dict({"measurement_rpm": "N_RPM", "measurement_tt2": " T_T2 ",
                            "graph_signals": ["g:RPM", "m:X"]})
    assert cfg.sensors["RPM"].value == Binding(SOURCE_A2L, a2l_name="N_RPM")
    assert cfg.sensors["Tt2"].value.a2l_name == "T_T2"
    assert cfg.gauge_a2l_map() == {"RPM": "N_RPM", "Tt2": "T_T2"}
    assert cfg.graph_signals == ["g:RPM", "m:X"]
    assert "Tt5" in cfg.unbound_gauges()


def test_legacy_actuator_can_and_a2l_channels_migrate():
    cfg = config_from_dict({"actuators": {
        "valf": {"message": "ACT", "enable_signal": "Valf_Ovr_En", "value_signal": "Valf_Ovr_Val", "channel": "can"},
        "starter": {"channel": "a2l", "a2l_enable": "starter_sw", "a2l_value": "starter_cmd"},
    }})
    v = cfg.actuators["valf"]
    assert v.value == Binding(SOURCE_CAN, "ACT", "Valf_Ovr_Val")
    assert v.sw == Binding(SOURCE_CAN, "ACT", "Valf_Ovr_En")
    s = cfg.actuators["starter"]
    assert s.value == Binding(SOURCE_A2L, a2l_name="starter_cmd")
    assert s.sw == Binding(SOURCE_A2L, a2l_name="starter_sw")


def test_legacy_motor_commands_become_can_bindings_and_new_ones_can_be_a2l():
    cfg = config_from_dict({"motor_start": {"message": "CMD", "signal": "Start", "value": 1},
                            "estop": {"binding": {"source": "a2l", "a2l_name": "estop_req"}, "value": 2}})
    assert cfg.motor_start.binding == Binding(SOURCE_CAN, "CMD", "Start")
    assert cfg.estop.binding.source == SOURCE_A2L and cfg.estop.value == 1.0      # eski değer yok sayılır: sabit 1
    assert not cfg.motor_stop.binding.is_set


def test_roundtrip_keeps_independent_sources_for_value_and_sw(tmp_path):
    cfg = DashboardConfig()
    cfg.actuators["pompa_fuel"] = SignalMap(value=Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc"),
                                            sw=Binding(SOURCE_CAN, "OVR", "clbc_Fuel_pump_dc_perc_sw"))
    cfg.sensors["RPM"] = SignalMap(value=Binding(SOURCE_CAN, "ENG", "rpm"), fault=Binding(SOURCE_A2L, a2l_name="rpm_flt"))
    store = DashboardConfigStore(str(tmp_path / "d.json"))
    store.save(cfg)
    back = store.load()
    assert back.actuators["pompa_fuel"] == cfg.actuators["pompa_fuel"]
    assert back.sensors["RPM"].value.text == "ENG.rpm"
    assert back.sensors["RPM"].fault.text == "rpm_flt"
    assert back.gauge_can_map() == {"RPM": ("ENG", "rpm")}
    assert set(back.actuators) == set(ACTUATOR_KEYS)


def test_corrupt_file_gives_defaults(tmp_path):
    p = tmp_path / "d.json"
    p.write_text("{bozuk", encoding="utf-8")
    assert DashboardConfigStore(str(p)).load().unbound_gauges()
