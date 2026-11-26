"""Model yaşam döngüsü denetleyicisi (sahte MATLAB Engine + sahte model; gerçek MATLAB'da doğrulanmadı)."""
import threading
import time

import pytest

from app import sim_protocol as proto
from app.sim_bridge import matlab_ctl as mc
from app.sim_bus import SimulinkUdpBus
from tests.fake_simulink import FakeSimulink


class FakeEngine:
    def __init__(self, fail_start=False, hang=0.0):
        self.calls, self.status = [], "stopped"
        self.fail_start, self.hang = fail_start, hang

    def load_system(self, m, nargout=0):
        self.calls.append(("load", m))

    def set_param(self, m, k, v, nargout=0):
        if self.hang:
            time.sleep(self.hang)
        if k == "SimulationCommand" and self.fail_start:
            raise RuntimeError("model derlenemedi")
        self.calls.append((k, v))
        if k == "SimulationCommand":
            self.status = {"start": "running", "pause": "paused", "continue": "running", "stop": "stopped"}[v]

    def get_param(self, m, k):
        return self.status

    def quit(self):
        self.calls.append(("quit",))


def _wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_lifecycle_with_matlab_engine_backend():
    eng = FakeEngine()
    seen = []
    c = mc.ModelController(mc.MatlabEngineBackend(lambda: eng), on_change=seen.append)
    assert c.state == mc.NOT_CONNECTED and not c.allowed("start")
    c.connect("engmodel")
    assert _wait(lambda: c.state == mc.READY) and ("load", "engmodel") in eng.calls
    assert c.command("start") and _wait(lambda: c.state == mc.RUNNING)
    assert not c.command("start")                               # çalışırken tekrar start reddedilir
    assert c.command("pause") and _wait(lambda: c.state == mc.PAUSED)
    assert c.command("resume") and _wait(lambda: c.state == mc.RUNNING)
    assert c.command("stop") and _wait(lambda: c.state == mc.STOPPED)
    assert c.command("reset") and _wait(lambda: c.state == mc.READY)
    assert [x for x in seen if x in (mc.RUNNING, mc.PAUSED)][:3] == [mc.RUNNING, mc.PAUSED, mc.RUNNING]
    assert [e[1] for e in c.events] == ["Model start", "Model pause", "Model resume", "Model stop", "Model reset"]
    c.close()
    assert ("quit",) in eng.calls and c.state == mc.NOT_CONNECTED


def test_speed_uses_simulink_pacing_not_gui_timer():
    eng = FakeEngine()
    c = mc.ModelController(mc.MatlabEngineBackend(lambda: eng))
    c.connect("m")
    assert _wait(lambda: c.state == mc.READY)
    c.set_speed(2.0)
    assert _wait(lambda: ("PacingRate", "2.0") in eng.calls) and ("EnablePacing", "on") in eng.calls
    c.set_speed(0.0)                                            # Fastest: pacing kapalı
    assert _wait(lambda: ("EnablePacing", "off") in eng.calls)
    assert [s for s, _ in mc.SPEEDS] == ["0.25x", "0.5x", "1x", "2x", "5x", "Fastest"]
    c.close()


def test_matlab_missing_gives_clear_error_and_real_ecu_unaffected():
    c = mc.ModelController(mc.MatlabEngineBackend())            # matlab.engine bu ortamda yok
    c.connect("m")
    assert _wait(lambda: c.state == mc.NOT_CONNECTED and "Engine" in c.error)
    c.close()


def test_command_failure_goes_to_error_with_message():
    eng = FakeEngine(fail_start=True)
    c = mc.ModelController(mc.MatlabEngineBackend(lambda: eng))
    c.connect("m")
    assert _wait(lambda: c.state == mc.READY)
    c.command("start")
    assert _wait(lambda: c.state == mc.ERROR) and "derlenemedi" in c.error
    assert c.allowed("reset") and not c.allowed("start")
    c.close()


def test_gui_does_not_block_when_matlab_hangs():
    eng = FakeEngine(hang=1.0)
    c = mc.ModelController(mc.MatlabEngineBackend(lambda: eng))
    c.connect("m")
    assert _wait(lambda: c.state == mc.READY)
    t0 = time.perf_counter()
    c.command("start")                                          # çağıran beklemez
    assert time.perf_counter() - t0 < 0.1
    c.snapshot()
    assert _wait(lambda: c.state == mc.RUNNING, 4.0)
    c.close()


def test_udp_backend_state_follows_heartbeat_and_commands_reach_model():
    bus = SimulinkUdpBus(channel="0:127.0.0.1:1", heartbeat=False)
    model = FakeSimulink(0, bus.local_port)
    bus.remote_port = model.port
    try:
        c = mc.ModelController(mc.UdpControlBackend(bus), bus=bus)
        c.connect("")
        assert _wait(lambda: c.state == mc.READY)
        c.command("start")
        assert _wait(lambda: model.received_cmds == [(proto.CMD_START, 0.0)])
        model.sim_time = 4.5
        model.send_heartbeat()                                   # model durumu RUNNING (sahte model komuttan sonra)
        assert _wait(lambda: c.sim_time == 4.5 and c.state == mc.RUNNING)
        c.set_speed(5.0)
        assert _wait(lambda: (proto.CMD_SPEED, 5.0) in model.received_cmds)
        model.state = proto.MS_ERROR
        model.send_heartbeat()
        assert _wait(lambda: c.state == mc.ERROR)
        snap = c.snapshot()
        assert snap["udp"] == "ok" and snap["sim_time"] == 4.5          # UDP bağlantısı ayrı izlenir
        c.close()
    finally:
        bus.shutdown()
        model.close()
