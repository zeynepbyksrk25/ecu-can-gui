import csv
import time

import numpy as np
import pytest

from app.ui import trend_panel as tp


@pytest.fixture
def panel(qapp):
    p = tp.TrendPanel()
    p.set_series([{"key": "g:RPM", "label": "RPM", "unit": "rpm"},
                  {"key": "g:Tt5", "label": "Tt5", "unit": "°C"},
                  {"key": "g:FP", "label": "FP", "unit": "bar"}])
    t0 = time.time() - 30
    for i in range(30):
        p.append("g:RPM", 4000 + i, t0 + i)
        p.append("g:Tt5", 600 + i, t0 + i + 0.2)
    return p


def test_each_unit_gets_its_own_axis_and_values_are_not_normalized(panel):
    assert len(panel._groups) == 3
    t, v = panel._series["g:RPM"].arrays()
    assert v.max() == 4029 and v.min() == 4000        # gerçek birim, 0-1 değil


def test_same_unit_series_share_an_axis(qapp):
    p = tp.TrendPanel()
    p.set_series([{"key": "a", "label": "A", "unit": "°C"}, {"key": "b", "label": "B", "unit": "°C"}])
    assert len(p._groups) == 1


def test_cursor_values_and_delta(panel):
    ta = panel._series["g:RPM"].t[5]
    tb = panel._series["g:RPM"].t[15]
    a, b = panel.values_at(ta), panel.values_at(tb)
    assert a["g:RPM"] == pytest.approx(4005) and b["g:RPM"] == pytest.approx(4015)


def test_csv_export_has_units_and_event_column(panel, tmp_path):
    panel.start_test()
    panel.end_test()
    out = tmp_path / "t.csv"
    assert panel.export("csv", str(out)) == str(out)
    rows = list(csv.reader(out.read_text(encoding="utf-8-sig").splitlines(), delimiter=";"))
    assert rows[0][-1] == "Olay" and "RPM [rpm]" in rows[0] and "Tt5 [°C]" in rows[0]
    events = [r[-1] for r in rows[1:] if r[-1]]
    assert events == ["Test Başlangıcı", "Test Bitişi"]


def test_mat_export_roundtrip(panel, tmp_path):
    from scipy.io import loadmat
    out = tmp_path / "t.mat"
    panel.export("mat", str(out))
    m = loadmat(str(out))
    assert "RPM" in m and np.asarray(m["RPM"]["values"][0, 0]).size == 30
    assert str(m["RPM"]["unit"][0, 0][0]) == "rpm"


def test_mdf_export_if_available(panel, tmp_path):
    pytest.importorskip("asammdf")
    out = tmp_path / "t.mf4"
    assert panel.export("mdf", str(out)) is not None and out.exists()


def test_test_markers_and_timer(panel):
    assert not panel.btn_test_end.isEnabled()
    panel.start_test()
    assert panel.btn_test_end.isEnabled() and not panel.btn_test_start.isEnabled()
    panel.end_test()
    assert [e[1] for e in panel.events] == ["Test Başlangıcı", "Test Bitişi"]


def test_window_selection_and_zoom(panel):
    panel.set_window(300)
    assert panel.window_s() == 300 and panel.is_live()
    panel.zoom(0.5)
    assert panel.window_s() == 150
    panel.zoom(2.0)
    panel.zoom(2.0)
    assert panel.window_s() == 600
