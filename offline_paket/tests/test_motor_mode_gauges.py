"""Motor Modu çipi, yeni gösterge aralıkları + kırmızı sınırlar, eski kayıt uyumu ve PLA sürgüsü."""

import pytest
from PySide6.QtWidgets import QMessageBox

from app.dashboard_config import (
    GAUGE_KEYS, MODE_KEY, MOTOR_MODE_NAMES, SENSOR_KEYS, SOURCE_CAN, Binding, DashboardConfigStore, SignalMap,
    config_from_dict, motor_mode_name,
)
from app.user_roles import Role


@pytest.fixture
def tab(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    from app.ui.dashboard_tab import DashboardTab
    t = DashboardTab()
    t.calls = []
    t.writer = lambda b, v, label: (t.calls.append((b.text, v)), True)[1]
    return t


def test_mode_names():
    assert [motor_mode_name(i) for i in range(7)] == ["POWER ON", "READY", "START UP", "IDLE", "RUN", "COOLING", "STOP"]
    assert motor_mode_name(4.0) == "RUN"
    assert motor_mode_name(9) == "BİLİNMİYOR (9)"
    assert motor_mode_name(None) == "—" and motor_mode_name("x") == "—" and motor_mode_name(float("nan")) == "—"
    assert len(MOTOR_MODE_NAMES) == 7


def test_gauge_set_changed_and_mode_is_a_sensor_binding():
    assert GAUGE_KEYS == ["RPM", "İtki", "PLA", "Tt5", "FP", "FT", "Ps2", "Ps3"] and "Tt2" not in GAUGE_KEYS
    assert MODE_KEY in SENSOR_KEYS and MODE_KEY not in GAUGE_KEYS


def test_mode_chip_shows_name_only_and_goes_blank_when_stale(tab, monkeypatch):
    assert tab.motor_mode_text == "—"
    for v, name in ((0, "POWER ON"), (4, "RUN"), (6, "STOP")):
        tab.set_gauge_value(MODE_KEY, v)
        assert tab.motor_mode_text == name                      # sayı değil, yalnız ad
    tab.set_gauge_value(MODE_KEY, 42)
    assert tab.motor_mode_text == "BİLİNMİYOR (42)"
    tab.set_gauge_value(MODE_KEY, 3)
    import app.ui.dashboard_tab as dtab
    real = dtab.time.monotonic
    monkeypatch.setattr(dtab.time, "monotonic", lambda: real() + dtab.STALE_S + 1)
    tab._refresh_gauge_states()
    assert tab.motor_mode_text == "—"                           # bayat veri
    assert MODE_KEY not in tab._gauge_cards                     # mod bir gösterge değil


@pytest.mark.parametrize("key,lo,hi,red", [
    ("RPM", 0, 140000, 118000), ("İtki", 0, 270, 255), ("PLA", 0, 100, None), ("Tt5", -40, 1200, 900),
    ("FP", 0, 5, 4.5), ("FT", -30, 40, None), ("Ps2", 0, 2.5, 1.6), ("Ps3", 0, 5, None)])
def test_ranges_and_red_limits(tab, key, lo, hi, red):
    g = tab._gauge_cards[key].gauge
    assert (g._min, g._max, g.red_limit) == (lo, hi, red)


def test_red_only_above_limit_and_card_alarm(tab):
    gc = tab._gauge_cards["RPM"]
    tab.set_gauge_value("RPM", 118000)
    assert not gc.gauge.is_over_limit and gc.property("state") in ("", None)    # tam sınırda kırmızı değil
    tab.set_gauge_value("RPM", 118001)
    assert gc.gauge.is_over_limit and gc.property("state") == "alarm" and gc.tag.text() == "OVERSPEED"
    tab.set_gauge_value("RPM", 90000)
    assert not gc.gauge.is_over_limit and not gc.tag.isVisibleTo(gc)
    tab.set_gauge_value("Ps2", 1.7)
    assert tab._gauge_cards["Ps2"].tag.text() == "LİMİT"
    tab.set_gauge_value("PLA", 100)                                              # sınırsız gösterge asla alarm vermez
    assert tab._gauge_cards["PLA"].property("state") in ("", None)
    tab.set_gauge_value("Tt5", -40)                                              # negatif alt sınır
    assert tab._gauge_cards["Tt5"].gauge.fraction() == 0.0
    tab.set_gauge_value("FT", 5)
    assert tab._gauge_cards["FT"].gauge.fraction() == pytest.approx(35 / 70)


def test_fault_tag_has_priority_over_limit(tab):
    gc = tab._gauge_cards["Tt5"]
    tab.set_gauge_value("Tt5", 950)
    assert gc.tag.text() == "AŞIRI SICAK"
    tab.set_sensor_fault("Tt5", "Sensör arızası")
    assert gc.tag.text() == "ARIZA"


def test_gauges_paint_without_error(tab):
    tab.resize(1400, 800)
    for k, v in {"RPM": 127300, "İtki": 188, "Ps3": 3.3}.items():
        tab.set_gauge_value(k, v)
    assert tab.grab().width() == 1400


def test_legacy_tt2_config_loads_and_mode_roundtrips(tmp_path):
    cfg = config_from_dict({"sensors": {"Tt2": {"value": {"source": "can", "message": "M", "signal": "S"}},
                                        "RPM": {"value": {"source": "can", "message": "E", "signal": "rpm"}}}})
    assert "Tt2" not in cfg.sensors and cfg.sensor_map("RPM").value.signal == "rpm"
    cfg.sensors[MODE_KEY] = SignalMap(value=Binding(SOURCE_CAN, "ENG", "motor_mode"))
    cfg.sensors["Ps3"] = SignalMap(value=Binding(SOURCE_CAN, "ENG", "ps3"))
    store = DashboardConfigStore(str(tmp_path / "c.json"))
    assert store.save(cfg)
    back = store.load()
    assert back.sensor_map(MODE_KEY).value.text == "ENG.motor_mode" and back.sensor_map("Ps3").value.signal == "ps3"
    assert back.gauge_can_map()[MODE_KEY] == ("ENG", "motor_mode")
    assert "Ps3" not in back.unbound_gauges() and MODE_KEY not in back.unbound_gauges()


def test_old_measurement_format_does_not_break():
    cfg = config_from_dict({"measurement_tt2": "tt2_a2l", "measurement_rpm": "rpm_a2l"})
    assert cfg.sensor_map("RPM").value.a2l_name == "rpm_a2l" and "Tt2" not in cfg.sensors


# ---- PLA sürgüsü -------------------------------------------------------------
def _armed(tab):
    from app.dashboard_config import DashboardConfig
    cfg = DashboardConfig()
    cfg.actuators["throttle"] = SignalMap(value=Binding(SOURCE_CAN, "CTRL", "pla"))
    tab.set_config(cfg)
    tab.set_role(Role.ENGINEER)


def test_throttle_slider_disabled_without_role_or_mapping(tab):
    tab.set_role(Role.OPERATOR)
    assert not tab.throttle_slider.isEnabled()
    _armed(tab)
    assert tab.throttle_slider.isEnabled()
    tab.set_role(Role.OPERATOR)
    assert not tab.throttle_slider.isEnabled()


def test_throttle_slider_syncs_box_and_sends(tab):
    _armed(tab)
    box = tab._act_rows["throttle"]["control"]
    tab.throttle_slider.setValue(35)
    assert box.text() == "35" and tab.throttle_pct.text() == "35 %"
    assert tab.calls[-1] == ("CTRL.pla", 35.0)                    # ilk değişiklik hemen gider
    tab._throttle_timer.stop()
    tab.throttle_slider.setValue(80)
    tab._throttle_timer.stop()
    tab._throttle_pending = False
    tab.calls.clear()
    tab.throttle_slider.sliderPressed.emit()
    tab.throttle_slider.setValue(90)
    tab.throttle_slider.setValue(91)                              # kısıtlama aralığında: yalnız kuyruğa alınır
    assert len(tab.calls) <= 1
    tab.throttle_slider.sliderReleased.emit()
    assert tab.calls[-1] == ("CTRL.pla", 91.0)                    # bırakınca SON değer kesin gider
    # kutuya yazılan değer sürgüyü taşır, komut yalnız Enter ile gider
    tab.calls.clear()
    box.setText("20")
    box.textEdited.emit("20")
    assert tab.throttle_slider.value() == 20 and not tab.calls


def test_throttle_failure_stops_resending_during_drag(tab):
    _armed(tab)
    tab.writer = lambda b, v, label: (tab.calls.append((b.text, v)), False)[1]
    tab.throttle_slider.sliderPressed.emit()
    tab.throttle_slider.setValue(10)
    n = len(tab.calls)
    tab._throttle_timer.stop()
    tab.throttle_slider.setValue(20)
    tab._on_throttle_tick()
    assert len(tab.calls) == n                                    # hata sonrası sürükleme boyunca tekrar denemez


def test_fp_red_above_4_5_bar(tab):
    gc = tab._gauge_cards["FP"]
    tab.set_gauge_value("FP", 4.5)
    assert not gc.gauge.is_over_limit and gc.property("state") in ("", None)
    tab.set_gauge_value("FP", 4.6)
    assert gc.gauge.is_over_limit and gc.property("state") == "alarm" and gc.tag.text() == "LİMİT"


def test_throttle_slider_real_mouse_drag(tab):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    _armed(tab)
    sl = tab.throttle_slider
    sl.resize(300, 26)
    sl.show()
    tab.calls.clear()
    y = sl.height() // 2
    QTest.mousePress(sl, Qt.LeftButton, Qt.NoModifier, QPoint(13, y))        # sol uç
    assert sl.value() == 0
    QTest.mouseMove(sl, QPoint(150, y))
    assert abs(sl.value() - 50) <= 1 and tab._act_rows["throttle"]["control"].text() == str(sl.value())
    QTest.mouseMove(sl, QPoint(900, y))                                      # aralık dışı: 100'e kıskaç
    assert sl.value() == 100
    QTest.mouseRelease(sl, Qt.LeftButton, Qt.NoModifier, QPoint(900, y))
    assert tab.calls[-1] == ("CTRL.pla", 100.0) and not sl.isSliderDown()


def test_throttle_slider_ignores_mouse_when_disabled(tab):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    tab.set_role(Role.OPERATOR)
    sl = tab.throttle_slider
    sl.resize(300, 26)
    QTest.mouseClick(sl, Qt.LeftButton, Qt.NoModifier, QPoint(250, 13))
    assert sl.value() == 0
