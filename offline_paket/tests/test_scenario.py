import json

import pytest

from app.sim_bridge import scenario as sc


class Ctx:
    def __init__(self):
        self.signals, self.sets, self.cmds, self.markers = {}, [], [], []
        self.script = []        # (zaman çağrı sayısı) -> değişiklikler

    def get_signal(self, name):
        return self.signals.get(name)

    def set_signal(self, name, value):
        self.sets.append((name, value))
        self.signals[name] = value

    def model_command(self, cmd, arg=0.0):
        self.cmds.append((cmd, arg))

    def marker(self, label):
        self.markers.append(label)

    def log(self, text):
        pass


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += max(s, 1e-6)


def run(raw, ctx, hook=None):
    clk = Clock()
    ctx_sleep = clk.sleep
    r = sc.ScenarioRunner(sc.parse_scenario(raw), ctx, clock=clk.now, sleep=(lambda s: (ctx_sleep(s), hook and hook(clk.t))),
                          poll_s=0.1)
    r.run()
    return r


def test_parse_validation():
    for bad in ({}, {"steps": []}, {"steps": [{"do": "x"}]}, {"steps": [{"do": "wait", "signal": "a", "op": ">", "value": 1}]},
                {"steps": [{"do": "wait", "signal": "a", "op": "~", "value": 1, "timeout": 1}]},
                {"steps": [{"do": "model", "cmd": "boom"}]}, {"steps": [{"do": "set", "signal": "a", "value": "x"}]},
                {"steps": [{"do": "marker", "label": " "}]}):
        with pytest.raises(sc.ScenarioError):
            sc.parse_scenario(bad)


def test_sequence_set_wait_marker_and_conditional_progress():
    ctx = Ctx()
    raw = {"name": "t", "steps": [
        {"do": "model", "cmd": "start"}, {"do": "set", "signal": "CMD.start_req", "value": 1},
        {"do": "wait", "signal": "ENG.rpm", "op": ">=", "value": 1000, "timeout": 5},
        {"do": "marker", "label": "Idle"}, {"do": "model", "cmd": "stop"}]}
    r = run(raw, ctx, hook=lambda t: ctx.signals.__setitem__("ENG.rpm", 400 * t))      # rpm zamanla artar
    assert [x.status for x in r.results] == ["DONE"] * 5 and ctx.markers == ["Idle"]
    assert ctx.cmds == [("start", 0.0), ("stop", 0.0)] and ctx.sets == [("CMD.start_req", 1.0)]
    assert r.verdict.startswith("TAMAMLANDI")                          # gereksinim yok → otomatik karar yok


def test_wait_timeout_is_timeout_not_pass():
    ctx = Ctx()
    r = run({"steps": [{"do": "wait", "signal": "x", "op": ">", "value": 1, "timeout": 1}, {"do": "marker", "label": "sonra"}]}, ctx)
    assert r.results[0].status == "TIMEOUT" and "veri yok" in r.results[0].detail
    assert r.verdict == "FAIL" and ctx.markers == ["sonra"]            # senaryo ilerler ama sonuç FAIL


def test_check_without_requirement_is_skipped_never_invents_limit():
    ctx = Ctx()
    ctx.signals["egt"] = 1e9
    r = run({"steps": [{"do": "check", "signal": "egt", "op": "<=", "value": 900}]}, ctx)
    assert r.results[0].status == "SKIPPED" and "gereksinim tanımlı değil" in r.results[0].detail
    assert r.verdict.startswith("TAMAMLANDI")


def test_check_with_requirement_pass_and_fail_and_missing_data():
    ctx = Ctx()
    ctx.signals["egt"] = 850.0
    steps = [{"do": "check", "signal": "egt", "op": "<=", "value": 900, "requirement": "R1"},
             {"do": "check", "signal": "egt", "op": ">=", "value": 900, "requirement": "R2"},
             {"do": "check", "signal": "yok", "op": ">=", "value": 1, "requirement": "R3"}]
    r = run({"steps": steps}, ctx)
    assert [x.status for x in r.results] == ["PASS", "FAIL", "FAIL"] and r.verdict == "FAIL"
    assert "veri yok" in r.results[2].detail


def test_monitor_marks_violation_and_fails():
    ctx = Ctx()
    raw = {"steps": [{"do": "monitor", "signal": "egt", "op": "<=", "value": 900, "requirement": "R9"},
                     {"do": "delay", "seconds": 3}]}
    r = run(raw, ctx, hook=lambda t: ctx.signals.__setitem__("egt", 800 + 100 * t))
    assert r.verdict == "FAIL" and r.violations and any("İHLAL" in m for m in ctx.markers)
    assert "R9" in r.report_text()


def test_monitor_without_requirement_skipped():
    ctx = Ctx()
    r = run({"steps": [{"do": "monitor", "signal": "egt", "op": "<=", "value": 1}, {"do": "delay", "seconds": 0.2}]}, ctx)
    assert r.results[0].status == "SKIPPED"


def test_step_error_aborts_remaining_safely():
    class Bad(Ctx):
        def set_signal(self, *a):
            raise RuntimeError("yazılamadı")
    ctx = Bad()
    r = run({"steps": [{"do": "set", "signal": "a", "value": 1}, {"do": "model", "cmd": "start"}]}, ctx)
    assert [x.status for x in r.results] == ["ERROR", "ABORTED"] and ctx.cmds == [] and r.verdict == "ABORTED"


def test_abort_from_another_thread_stops_wait():
    import time
    ctx = Ctx()
    r = sc.ScenarioRunner(sc.parse_scenario({"steps": [{"do": "wait", "signal": "x", "op": ">", "value": 1, "timeout": 60},
                                                       {"do": "model", "cmd": "stop"}]}), ctx, poll_s=0.01)
    r.start()
    time.sleep(0.1)
    r.abort()
    r.join(2)
    assert r.verdict == "ABORTED" and r.results[0].status == "ABORTED" and ctx.cmds == []


def test_example_scenario_file_is_valid_and_has_no_limits():
    import os
    p = os.path.join(os.path.dirname(__file__), "..", "..", "simulink", "scenarios", "ornek_motor_start.json")
    s = sc.load_scenario(p)
    assert all(not st.get("requirement") for st in s.steps)
    with pytest.raises(sc.ScenarioError):
        sc.load_scenario(p + ".yok")
