import math

from app.change_tracker import (
    BASELINE_A2L, BASELINE_SESSION, BLINK_S, ChangeTracker, direction, format_delta,
)


def test_direction_and_format():
    assert direction(1.0, 2.0) == 1
    assert direction(2.0, 1.0) == -1
    assert direction(1.0, 1.0) == 0
    assert direction(None, 1.0) == 0
    assert direction(1.0, math.nan) == 0
    assert direction(1.0, math.inf) == 0
    assert format_delta(1.2, 1.35) == "↑ +0.15"
    assert format_delta(0.8, 0.65) == "↓ -0.15"
    assert format_delta(85, 90) == "↑ +5"
    assert format_delta(85, 90, "%") == "↑ +5 %"
    assert format_delta(5, 5) == ""


def test_edit_is_not_applied_until_written():
    t = ChangeTracker()
    t.observe("Kp", 1.2, "")
    t.edit("Kp", 1.35)
    assert t.state("Kp").status == "pending"
    arrow, mode = t.arrow("Kp")
    assert (arrow, mode) == ("↑", "pending")           # uygulanmış gibi (blink/steady) gösterilmez
    assert t.delta_text("Kp") == "↑ +0.15"
    t.applied("Kp", 1.2, 1.35, now=100.0)
    assert t.state("Kp").status == "applied"
    assert t.arrow("Kp", now=100.5) == ("↑", "blink")
    assert t.arrow("Kp", now=100.0 + BLINK_S + 0.1) == ("↑", "steady")
    assert t.state("Kp").ecu == 1.35


def test_failed_write_keeps_pending_and_is_not_applied():
    t = ChangeTracker()
    t.observe("Ki", 0.8)
    t.edit("Ki", 0.65)
    t.failed("Ki", "zaman aşımı")
    st = t.state("Ki")
    assert st.status == "pending" and st.ecu == 0.8
    t.discard_edit("Ki")
    assert t.state("Ki").status == "failed"
    assert "BAŞARISIZ" in t.summary("Ki")
    assert t.arrow("Ki") == ("", "")


def test_baseline_reference_source():
    t = ChangeTracker()
    t.observe("A", 10.0)
    assert t.state("A").baseline_source == BASELINE_SESSION
    assert "oturum" in t.baseline_label("A")
    t.observe("B", 10.0, a2l_default=7.0)
    assert t.state("B").baseline == 7.0 and t.state("B").baseline_source == BASELINE_A2L
    t.observe("A", 12.0)                                   # sonraki okuma referansı ezmez
    assert t.state("A").baseline == 10.0
    assert t.baseline_label("yok").startswith("başlangıç referansı yok")


def test_reread_equal_clears_pending_and_default_targets():
    t = ChangeTracker()
    t.observe("A", 10.0)
    t.edit("A", 12.0)
    assert t.undo_targets() == {"A": 10.0}
    t.observe("A", 12.0)                                   # ECU zaten bu değerde
    assert t.state("A").status == "clean"
    assert t.default_targets() == {"A": 10.0}
    t.observe("RO", 1.0, writable=False)
    t.state("RO").ecu = 5.0
    assert "RO" not in t.default_targets()                 # salt okunur: başlangıca yazılmaz
    assert "Salt okunur" in t.summary("RO")


def test_nan_inputs_ignored():
    t = ChangeTracker()
    t.observe("X", math.nan)
    assert t.state("X").baseline is None
    t.observe("X", 1.0)
    t.edit("X", math.inf)
    assert t.state("X").edited is None
