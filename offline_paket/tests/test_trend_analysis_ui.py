"""Canlı Trend (Aşama 2): sinyal tablosu, imleç değer paneli, freeze, ofset/ölçek, sıralama, yerleşim."""
import time

import numpy as np
import pytest

from app.ui import trend_panel as tp
from app.ui import trend_signal_table as st

SPECS = [{"key": "g:RPM", "label": "RPM", "unit": "rpm", "source": "PCAN"},
         {"key": "g:Tt5", "label": "Tt5", "unit": "°C", "source": "Simulink MIL"},
         {"key": "g:FP", "label": "Fp", "unit": "bar"}]


@pytest.fixture
def panel(qapp):
    p = tp.TrendPanel()
    p.resize(1000, 480)
    p.show()
    p.set_series(SPECS)
    p.t0 = time.time() - 40
    for i in range(30):
        p.append("g:RPM", 4000 + 10 * i, p.t0 + i)
        p.append("g:Tt5", 600 + i, p.t0 + i)
    for i in range(10):                                   # g:FP: 8-30 s arası veri yok (boşluk)
        p.append("g:FP", 5 + i * 0.1, p.t0 + i)
    p.append("g:FP", 7.0, p.t0 + 29)
    p._tick()
    return p


def test_table_lists_signals_with_color_source_unit(panel):
    t = panel.signal_table
    assert t.keys_in_order() == ["g:RPM", "g:Tt5", "g:FP"]
    assert t.item_text("g:RPM", st.C_SOURCE) == "PCAN" and t.item_text("g:Tt5", st.C_SOURCE) == "Simulink MIL"
    assert t.item_text("g:RPM", st.C_UNIT) == "rpm"
    assert t.item_text("g:RPM", st.C_VALUE) == "4290"          # anlık değer


def test_main_and_difference_cursor_values_gap_and_rate(panel):
    panel.btn_cursor.setChecked(True)
    panel._cur_a.setPos(panel.t0 + 2.0)
    panel._cur_b.setPos(panel.t0 + 6.0)
    panel._update_cursor_readout()
    t = panel.signal_table
    assert not t.isColumnHidden(st.C_B)
    assert t.item_text("g:RPM", st.C_VALUE) == "4020" and t.item_text("g:RPM", st.C_B) == "4060"
    assert t.item_text("g:RPM", st.C_DY) == "+40" and t.item_text("g:RPM", st.C_DYDT) == "+10"
    assert t.item_text("g:Tt5", st.C_DY) == "+4"                  # farklı birimde bağımsız
    assert t.item_text("g:RPM", st.C_MIN) == "4020" and t.item_text("g:RPM", st.C_MAX) == "4060"
    panel._cur_a.setPos(panel.t0 + 15.0)                        # g:FP için 9 → 29 s arası boşluk
    panel._cur_b.setPos(panel.t0 + 20.0)
    panel._update_cursor_readout()
    assert t.item_text("g:FP", st.C_VALUE) == st.NO_DATA and t.item_text("g:FP", st.C_DY) == "—"
    assert t.item_text("g:RPM", st.C_VALUE) == "4150"            # diğer sinyal etkilenmez
    panel.btn_cursor.setChecked(False)
    assert t.isColumnHidden(st.C_B)


def test_freeze_all_stops_display_but_keeps_acquiring(panel):
    n = len(panel._series["g:RPM"].t)
    panel.freeze_all(True)
    assert panel.is_frozen() and not panel.is_live()
    frozen_last = panel._series["g:RPM"].view_arrays()[0][-1]
    panel.append("g:RPM", 9999, time.time() + 5)
    assert len(panel._series["g:RPM"].t) == n + 1             # veri alımı sürer
    assert panel._series["g:RPM"].view_arrays()[0][-1] == frozen_last
    panel.freeze_all(False)
    assert not panel.is_frozen() and panel.is_live()
    assert panel._series["g:RPM"].view_arrays()[1][-1] == 9999


def test_single_signal_freeze_via_table(panel):
    it = panel.signal_table._items["g:Tt5"]
    from PySide6.QtCore import Qt
    it.setCheckState(st.C_FREEZE, Qt.Checked)
    assert panel.is_frozen("g:Tt5") and not panel.is_frozen("g:RPM")
    it.setCheckState(st.C_FREEZE, Qt.Unchecked)
    assert not panel.is_frozen("g:Tt5")


def test_offset_and_scale_change_view_only(panel):
    ser = panel._series["g:RPM"]
    raw_before = ser.arrays()[1].copy()
    panel.set_signal_offset("g:RPM", 100.0)
    panel.set_signal_scale("g:RPM", 2.0)
    panel._tick()
    shown = ser.curve.getData()[1]
    assert shown[-1] == pytest.approx(4290 * 2 + 100)
    assert np.array_equal(ser.arrays()[1], raw_before)         # orijinal veri değişmedi
    assert panel.values_at(panel.t0 + 2.0)["g:RPM"] == pytest.approx(4020)   # imleç değeri ham veriden
    panel.set_signal_scale("g:RPM", 0.0)                       # geçersiz ölçek yok sayılır
    assert ser.scale == 2.0


def test_visibility_and_reorder_and_color(panel):
    from PySide6.QtCore import Qt
    panel.signal_table._items["g:Tt5"].setCheckState(st.C_SHOW, Qt.Unchecked)
    panel._tick()
    assert panel._series["g:Tt5"].visible is False
    panel.signal_table.order_changed.emit(["g:FP", "g:RPM", "g:Tt5"])
    assert panel._order[:3] == ["g:FP", "g:RPM", "g:Tt5"]
    panel._on_table_color("g:RPM", "#123456")
    assert panel._series["g:RPM"].color == "#123456"
    panel.set_series(SPECS)                                     # yeniden kurulumda özel renk korunur
    assert panel._series["g:RPM"].color == "#123456"


def test_own_strip_moves_signal_to_separate_strip(panel):
    n = len(panel._strips)
    panel._toggle_own_strip("g:FP")                             # g:FP bar şeridi zaten tek; rpm ile deneyelim
    panel._toggle_own_strip("g:FP")
    panel.set_series(SPECS + [{"key": "g:FP2", "label": "Fp2", "unit": "bar"}])
    base = len(panel._strips)
    panel._toggle_own_strip("g:FP2")
    assert len(panel._strips) == base + 1
    assert n >= 1


def test_y_free_mode_toggles_autorange(panel):
    panel.btn_yfree.setChecked(True)
    assert all(p.vb.state["mouseEnabled"][1] for p in panel._strips)
    panel.btn_yfree.setChecked(False)
    assert not any(p.vb.state["mouseEnabled"][1] for p in panel._strips)


def test_zoom_to_cursor_range(panel):
    panel.btn_cursor.setChecked(True)
    panel._cur_a.setPos(panel.t0 + 5)
    panel._cur_b.setPos(panel.t0 + 15)
    panel.zoom_to_cursors()
    lo, hi = panel._xvb().viewRange()[0]
    assert lo == pytest.approx(panel.t0 + 5, abs=0.5) and hi == pytest.approx(panel.t0 + 15, abs=0.5)
    assert not panel.is_live()


def test_layout_roundtrip_via_file(panel, tmp_path):
    panel.set_signal_offset("g:RPM", 7.0)
    panel._on_table_color("g:Tt5", "#abcdef")
    panel.signal_table.order_changed.emit(["g:FP", "g:RPM", "g:Tt5"])
    panel.btn_strips.setChecked(False)
    path = str(tmp_path / "lay.json")
    assert panel.save_layout(path)
    p2 = tp.TrendPanel()
    p2.set_series(SPECS)
    assert p2.load_layout(path)
    assert p2._order[:3] == ["g:FP", "g:RPM", "g:Tt5"]
    assert p2._series["g:RPM"].offset == 7.0 and p2._series["g:Tt5"].color == "#abcdef"
    assert p2._strip_mode is False
    (tmp_path / "bad.json").write_text("{bozuk")
    assert p2.load_layout(str(tmp_path / "bad.json")) is False
    assert p2.load_layout(str(tmp_path / "yok.json")) is False


def test_autosave_layout_only_when_path_set(panel, tmp_path):
    path = tmp_path / "auto.json"
    panel.layout_path = str(path)
    panel._on_table_color("g:RPM", "#111111")
    panel._tick()
    assert path.exists()
