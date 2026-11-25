"""Ana Sayfa > Canlı Trendler: şerit modu (her birim kendi şeridinde), canlı fark eğrisi, veri boşluğu, geçersiz değer."""
import time

import numpy as np
import pytest
from PySide6.QtWidgets import QInputDialog

from app.ui import trend_panel as tp

SPECS = [{"key": "g:RPM", "label": "RPM", "unit": "rpm"},
         {"key": "g:Tt5", "label": "Tt5", "unit": "°C"},
         {"key": "g:FP_main", "label": "Fp Ana", "unit": "bar"},
         {"key": "g:FP_start", "label": "Fp Başl.", "unit": "bar"}]


@pytest.fixture
def panel(qapp):
    p = tp.TrendPanel()
    p.resize(800, 420)
    p.show()
    p.set_series(SPECS)
    t0 = time.time() - 30
    for i in range(30):
        for k, base in (("g:RPM", 4000), ("g:Tt5", 600), ("g:FP_main", 5), ("g:FP_start", 1)):
            p.append(k, base + i, t0 + i)
    p._tick()
    return p


def test_default_is_strip_mode_one_strip_per_unit(panel):
    assert panel._strip_mode and panel.btn_strips.isChecked()
    assert len(panel._strips) == 3                                  # rpm, °C, bar (bar'da iki sinyal ortak şeritte)
    assert [len(g["series"]) for g in panel._groups] == [1, 1, 2]
    assert all(s.curve is not None for s in panel._series.values())


def test_each_strip_shows_name_and_current_value(panel):
    panel._tick()
    texts = [t.toPlainText() for t in panel._strip_texts]
    assert "RPM" in texts[0] and "4029" in texts[0]
    assert "Fp Ana" in texts[2] and "Fp Başl." in texts[2]


def test_strips_share_the_time_axis_and_only_the_last_shows_it(panel):
    lo0, hi0 = panel._strips[0].vb.viewRange()[0]
    for p in panel._strips[1:]:
        lo, hi = p.vb.viewRange()[0]
        assert (lo, hi) == pytest.approx((lo0, hi0))
    assert not panel._strips[0].getAxis("bottom").isVisible() and panel._strips[-1].getAxis("bottom").isVisible()


def test_switching_back_to_single_plot_and_again_keeps_data_and_curves(panel):
    panel.btn_strips.setChecked(False)
    assert not panel._strip_mode and panel._strips == [] and len(panel._groups) == 3
    assert all(s.curve is not None for s in panel._series.values())
    panel._tick()
    panel.btn_strips.setChecked(True)
    assert panel._strip_mode and len(panel._strips) == 3
    t, v = panel._series["g:RPM"].arrays()
    assert len(t) == 30 and v[-1] == 4029


def test_cursor_lines_exist_in_every_strip_and_move_together(panel):
    panel.btn_cursor.setChecked(True)
    assert len(panel._strip_lines) == 3 and all(a.isVisible() and b.isVisible() for a, b in panel._strip_lines)
    assert panel.readout.isHidden()                                  # şerit modunda değerler şeritlerin içinde
    panel._strip_lines[1][0].setPos(panel._series["g:RPM"].t[10])    # 2. şeritteki A çizgisini sürükle
    assert panel._cur_a.value() == pytest.approx(panel._series["g:RPM"].t[10])
    for a, _b in panel._strip_lines:
        assert a.value() == pytest.approx(panel._cur_a.value())
    assert "A" in panel._strip_texts[0].toPlainText() and "4010" in panel._strip_texts[0].toPlainText()


def test_event_markers_are_drawn_in_every_strip(panel):
    panel.start_test()
    assert len(panel._event_items) == 3
    panel.btn_strips.setChecked(False)
    assert len(panel._event_items) == 1


def test_nan_and_infinite_samples_are_ignored(panel):
    n = len(panel._series["g:RPM"].t)
    for bad in (float("nan"), float("inf"), float("-inf")):
        panel.append("g:RPM", bad)
    assert len(panel._series["g:RPM"].t) == n


def test_cursor_does_not_invent_a_value_across_a_long_gap(qapp):
    p = tp.TrendPanel()
    p.set_series([{"key": "x", "label": "X", "unit": "u"}])
    t0 = time.time() - 100
    p.append("x", 5000, t0)
    p.append("x", 8000, t0 + 1)
    p.append("x", 8100, t0 + 60)                       # 59 sn veri boşluğu
    assert p.values_at(t0 + 0.5)["x"] == pytest.approx(6500)        # kısa aralık: doğrusal ara değer doğru
    assert "x" not in p.values_at(t0 + 30)                          # uzun boşluk: değer uydurulmaz
    assert p.values_at(t0 + 60)["x"] == pytest.approx(8100)         # örnek anının kendisi her zaman gösterilir


def test_compare_curve_updates_when_new_samples_arrive(qapp, monkeypatch):
    p = tp.TrendPanel()
    p.set_series([{"key": "a", "label": "A", "unit": "rpm"}, {"key": "b", "label": "B", "unit": "rpm"}])
    t0 = time.time() - 10
    for i in range(5):
        p.append("a", 5000, t0 + i)
        p.append("b", 5200, t0 + i)
    answers = iter([("A", True), ("B", True)])
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda *a, **k: next(answers)))
    p._on_compare()
    diff = next(s for k, s in p._series.items() if k.startswith("d:"))
    assert diff.v[-1] == pytest.approx(-200)
    for i in range(5, 9):                              # RPM yükselir: fark -100'e iner
        p.append("a", 5100, t0 + i)
        p.append("b", 5200, t0 + i)
    p._tick()
    assert diff.v[-1] == pytest.approx(-100) and len(diff.t) > 5
    assert np.isfinite(np.asarray(diff.v)).all()


def test_test_marker_buttons_are_named_as_markers_not_recording(qapp):
    p = tp.TrendPanel()
    assert p.btn_test_start.text() == "İşaretle" and p.btn_test_end.text() == "İşareti bitir"
    assert "KAYDI başlatmaz" in p.btn_test_start.toolTip()
