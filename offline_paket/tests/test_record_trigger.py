import math

import pytest

from app.record_trigger import COUNTER_INCREASE, THRESHOLD, TRANSITION, Trigger, TriggerEngine


def test_threshold_is_edge_triggered_with_pre_and_post():
    e = TriggerEngine([Trigger(THRESHOLD, "rpm", ">", 5000)], pre_s=2.0, post_s=3.0)
    for i in range(10):
        assert e.feed("rpm", 4000 + i, float(i)) is None
    assert e.feed("rpm", 5001, 10.0) is not None and e.fired_at == 10.0
    pre = e.take_pre_buffer()
    assert pre[0][0] >= 8.0 and pre[-1] == (10.0, "rpm", 5001.0)      # yalnızca son 2 sn
    assert not e.should_stop(12.9) and e.should_stop(13.0)
    assert e.feed("rpm", 6000, 11.0) is None                          # tetik bir kez


def test_already_above_threshold_at_start_does_not_fire_until_edge():
    e = TriggerEngine([Trigger(THRESHOLD, "egt", ">=", 900)])
    assert e.feed("egt", 950, 0.0) is not None                        # ilk örnek: önceki yok → kenar sayılır
    e2 = TriggerEngine([Trigger(THRESHOLD, "egt", ">=", 900)])
    e2.feed("egt", 100, 0.0)
    e2.feed("egt", 950, 1.0)
    assert e2.fired is not None


def test_counter_increase_and_transition():
    e = TriggerEngine([Trigger(COUNTER_INCREASE, "can_err", value=2)])
    e.feed("can_err", 10, 0)
    assert e.feed("can_err", 11, 1) is None
    assert e.feed("can_err", 13, 2) is not None
    t = TriggerEngine([Trigger(TRANSITION, "mode", from_value=1, to_value=3)])
    t.feed("mode", 1, 0)
    assert t.feed("mode", 2, 1) is None
    t.feed("mode", 1, 2)
    assert t.feed("mode", 3, 3) is not None
    any_change = TriggerEngine([Trigger(TRANSITION, "mode")])
    any_change.feed("mode", 1, 0)
    assert any_change.feed("mode", 5, 1) is not None


def test_nan_inf_ignored_and_validation_and_rearm():
    e = TriggerEngine([Trigger(THRESHOLD, "x", ">", 1)])
    assert e.feed("x", math.nan, 0) is None and e.feed("x", math.inf, 1) is None and e.feed("x", "a", 2) is None
    for bad in (Trigger("nope", "x"), Trigger(THRESHOLD, ""), Trigger(THRESHOLD, "x", "~", 1),
                Trigger(COUNTER_INCREASE, "x", value=0), Trigger(THRESHOLD, "x", ">", math.nan)):
        with pytest.raises(ValueError):
            TriggerEngine([bad])
    e.feed("x", 0, 3)
    e.feed("x", 5, 4)
    assert e.fired
    e.rearm()
    assert e.fired is None and e.take_pre_buffer() == []
