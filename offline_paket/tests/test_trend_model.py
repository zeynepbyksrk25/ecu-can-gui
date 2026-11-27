import math

import numpy as np
import pytest

from app.trend_model import (
    GAP, OUTSIDE, EMPTY, SignalView, TrendLayout, apply_view_transform, cursor_rows, cut_at, range_stats, sample_at,
)

T = [0.0, 1.0, 2.0, 10.0, 11.0]
V = [0.0, 10.0, 20.0, 100.0, 110.0]


def test_sample_exact_and_interpolated():
    assert sample_at(T, V, 1.0) == (10.0, "ok")
    assert sample_at(T, V, 0.5) == (5.0, "ok")


def test_sample_gap_is_not_interpolated():
    val, why = sample_at(T, V, 5.0, max_gap=5.0)          # 2 s ile 10 s arası 8 s boşluk
    assert val is None and why == GAP
    assert sample_at(T, V, 5.0, max_gap=10.0)[0] == pytest.approx(20 + 80 * 3 / 8)


def test_sample_outside_and_empty():
    assert sample_at(T, V, -1) == (None, OUTSIDE)
    assert sample_at(T, V, 12) == (None, OUTSIDE)
    assert sample_at([], [], 1) == (None, EMPTY)
    assert sample_at(T, V, float("nan"))[0] is None


def test_sample_nan_neighbour_gives_no_value():
    assert sample_at([0, 1, 2], [1.0, math.nan, 3.0], 0.5)[0] is None
    assert sample_at([0, 1, 2], [1.0, math.nan, 3.0], 1.0)[0] is None


def test_cursor_rows_delta_and_rate_different_units():
    series = {"rpm": (T, V), "egt": ([0, 1, 2, 3], [500, 510, 520, 530])}
    rows = {r.key: r for r in cursor_rows(series, ["rpm", "egt", "yok"], 0.5, 2.0)}
    assert set(rows) == {"rpm", "egt"}
    assert rows["rpm"].a == 5.0 and rows["rpm"].b == 20.0 and rows["rpm"].dy == 15.0
    assert rows["rpm"].dydt(0.5, 2.0) == pytest.approx(10.0)
    assert rows["egt"].dy == pytest.approx(15.0)          # birimler bağımsız hesaplanır
    gap = cursor_rows(series, ["rpm"], 5.0, 11.0)[0]       # A boşlukta
    assert gap.a is None and gap.dy is None and gap.dydt(5.0, 11.0) is None


def test_dydt_zero_dt():
    r = cursor_rows({"x": (T, V)}, ["x"], 1.0, 1.0)[0]
    assert r.dy == 0.0 and r.dydt(1.0, 1.0) is None


def test_range_stats_ignores_nonfinite():
    s = range_stats([0, 1, 2, 3], [1.0, math.nan, 5.0, math.inf], 0, 3)
    assert s == {"count": 2, "min": 1.0, "max": 5.0, "mean": 3.0}
    assert range_stats(T, V, 3, 9)["count"] == 0
    assert range_stats(T, V, 2, 0)["count"] == 3            # ters aralık düzeltilir
    assert range_stats([], [], 0, 1)["count"] == 0


def test_view_transform_does_not_touch_original():
    v = np.array([1.0, 2.0])
    out = apply_view_transform(v, offset=10, scale=2)
    assert list(out) == [12.0, 14.0] and list(v) == [1.0, 2.0]


def test_cut_at_freeze():
    t, v = cut_at(T, V, 2.0)
    assert list(t) == [0.0, 1.0, 2.0]
    t, v = cut_at(T, V, None)
    assert len(t) == 5


def test_layout_roundtrip_and_robustness():
    lay = TrendLayout(order=["a", "b"], views={"a": SignalView("a", "#fff", False, offset=3, scale=2, group="G"),
                                              "b": SignalView("b")}, strip_mode=False, window_s=300)
    back = TrendLayout.from_json(lay.to_json())
    assert back.order == ["a", "b"] and back.strip_mode is False and back.window_s == 300
    assert back.views["a"].visible is False and back.views["a"].group == "G" and back.views["a"].scale == 2
    bad = TrendLayout.from_json('{"window_s": -1, "views": [1, {"key": "x", "scale": 0, "offset": "q"}, {"nokey": 1}]}')
    assert bad.window_s == 60.0 and bad.order == ["x"] and bad.views["x"].scale == 1.0 and bad.views["x"].offset == 0.0
    with pytest.raises(ValueError):
        TrendLayout.from_json("{bozuk")
    with pytest.raises(ValueError):
        TrendLayout.from_json("[1]")
