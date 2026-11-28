"""MIL kalibrasyon: .m (Simulink.Parameter/LookupTable) + MATLAB Engine; SAHTE engine ile (gerçek MATLAB'da doğrulanmadı)."""
import json
import re

import pytest

from app.ccp import mapio
from app.sim_bridge import engine_params as ep

LISTING = [
    {"name": "IGN_ON_SPD", "kind": "param", "mclass": "single", "dims": [1, 1], "unit": "rev/min", "min": 0,
     "max": 117000, "storage": "ExportedGlobal", "breakpoints": []},
    {"name": "INLINED", "kind": "param", "mclass": "double", "dims": [1, 1], "unit": "", "min": [], "max": [],
     "storage": "Auto", "breakpoints": []},
    {"name": "VEC", "kind": "param", "mclass": "uint8", "dims": [1, 3], "unit": "", "min": 0, "max": 200,
     "storage": "ExportedGlobal", "breakpoints": []},
    {"name": "CURVE1", "kind": "lut", "mclass": "double", "dims": [3, 1], "unit": "%", "min": [], "max": [],
     "storage": "ExportedGlobal", "bpspec": "Explicit values",
     "breakpoints": [{"values": [0, 10, 20], "unit": "C"}]},
    {"name": "MAP1", "kind": "lut", "mclass": "double", "dims": [2, 3], "unit": "kg", "min": 0, "max": 100,
     "storage": "ExportedGlobal", "bpspec": "Explicit values",
     "breakpoints": [{"values": [1000, 2000], "unit": "rpm"}, {"values": [10, 20, 30], "unit": "%"}]},
    {"name": "BADFIX", "kind": "param", "mclass": "fixdt(1,16,4)", "dims": [1, 1], "breakpoints": []},
    {"name": "BADREF", "kind": "lut", "mclass": "double", "dims": [2, 2], "bpspec": "Reference",
     "breakpoints": [{"values": [1, 2]}, {"values": [1, 2]}]},
]


class FakeEngine:
    def __init__(self):
        self.ws = {"IGN_ON_SPD": [5000.0], "INLINED": [1.5], "VEC": [1.0, 2.0, 3.0], "CURVE1": [1.0, 2.0, 3.0],
                   "MAP1": [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]}          # MAP1: MATLAB (2x3) satır-majör gösterim
        self.calls, self.fail_update = [], False

    def eval(self, expr, nargout=0):
        self.calls.append(expr)
        if expr.startswith("mil_list_params"):
            return json.dumps(LISTING)
        m = re.match(r"jsonencode\(double\((\w+)\.(?:Table\.)?Value\)\)", expr)
        if m:
            v = self.ws[m.group(1)]
            return json.dumps(v[0] if len(v) == 1 else v)
        m = re.match(r"(\w+)\.(?:Table\.)?Value(?:\((\d+),?(\d+)?\))? = (?:\w+\()?([-\d.e+]+|true|false)\)?;", expr)
        if m:
            name, a, b, val = m.groups()
            val = float(val)
            if a is None:
                self.ws[name] = [val]
            elif b is None:
                self.ws[name][int(a) - 1] = val
            else:
                self.ws[name][int(a) - 1][int(b) - 1] = val
            return None
        if expr.startswith(("addpath", "evalin")):
            return None
        raise AssertionError(f"beklenmeyen ifade: {expr}")

    def set_param(self, m, k, v, nargout=0):
        if self.fail_update:
            raise RuntimeError("update hatası")
        self.calls.append(("set_param", m, k, v))


def _client(eng, running=False):
    params, _ = ep.parse_listing(json.dumps(LISTING))
    ep.build_summary(params)
    return EngineClientHelper(eng, params, running)


def EngineClientHelper(eng, params, running):
    state = {"running": running}
    c = ep.EngineParamClient(lambda: eng, params, lambda: state["running"], lambda: "mdl")
    c.state = state
    return c


def test_parse_listing_skips_and_maps():
    params, skipped = ep.parse_listing(json.dumps(LISTING))
    names = [p.name for p in params]
    assert names == ["IGN_ON_SPD", "INLINED", "VEC", "CURVE1", "MAP1"]
    assert {n for n, _ in skipped} == {"BADFIX", "BADREF"}
    p = {x.name: x for x in params}
    assert p["IGN_ON_SPD"].minimum == 0 and p["IGN_ON_SPD"].maximum == 117000 and p["INLINED"].minimum is None
    assert p["CURVE1"].dims == (1, 3)            # sütun tablo -> 1xN


def test_summary_kinds_and_axes():
    params, _ = ep.parse_listing(json.dumps(LISTING))
    s = ep.build_summary(params)
    c = {x.name: x for x in s.characteristics}
    assert c["IGN_ON_SPD"].kind == "SCALAR" and c["IGN_ON_SPD"].datatype == "FLOAT32_IEEE" and c["IGN_ON_SPD"].unit == "rev/min"
    assert c["VEC"].kind == "ARRAY" and c["VEC"].dims == (3,)
    assert c["CURVE1"].kind == "CURVE" and c["CURVE1"].axes[0].values == [0, 10, 20]
    m = c["MAP1"]
    assert m.kind == "MAP" and mapio.grid_shape(m) == (2, 3)          # 2 satır (bp1), 3 sütun (bp2)
    assert m.axes[0].values == [10, 20, 30] and m.axes[1].values == [1000, 2000]
    assert mapio.layout_support(m)[0]
    assert len({x.address for x in s.characteristics}) == len(s.characteristics)


def test_scalar_write_read_and_limits():
    eng = FakeEngine()
    c = _client(eng)
    ch = {x.name: x for x in ep.build_summary(list(c.params.values())).characteristics}["IGN_ON_SPD"]
    from app.ccp import codec
    raw = codec.encode_value("FLOAT32_IEEE", 5200.0, "LITTLE_ENDIAN")
    c.write_memory(ch.address, raw, verify=True)
    assert eng.ws["IGN_ON_SPD"] == [5200.0]
    assert codec.decode_value("FLOAT32_IEEE", c.read_memory(ch.address, 4), "LITTLE_ENDIAN") == 5200.0
    bad = codec.encode_value("FLOAT32_IEEE", 200000.0, "LITTLE_ENDIAN")
    with pytest.raises(ep.EngineParamError, match="Min/Max"):
        c.write_memory(ch.address, bad)
    assert eng.ws["IGN_ON_SPD"] == [5200.0]


def test_map_roundtrip_via_mapio_row_major():
    eng = FakeEngine()
    c = _client(eng)
    ch = {x.name: x for x in ep.build_summary(list(c.params.values())).characteristics}["MAP1"]
    assert mapio.read_grid(c, ch) == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]]
    old = mapio.write_grid(c, ch, [[10.0, 20.0, 30.0], [40.0, 50.0, 60.0]])
    assert old[1][2] == 6.0 and eng.ws["MAP1"] == [[10.0, 20.0, 30.0], [40.0, 50.0, 60.0]]
    with pytest.raises(Exception):                                       # Max=100 aşımı
        mapio.write_grid(c, ch, [[1.0, 2.0, 3.0], [4.0, 5.0, 600.0]])
    assert eng.ws["MAP1"] == [[10.0, 20.0, 30.0], [40.0, 50.0, 60.0]]


def test_running_model_rules_and_update():
    eng = FakeEngine()
    c = _client(eng, running=True)
    cs = {x.name: x for x in ep.build_summary(list(c.params.values())).characteristics}
    from app.ccp import codec
    with pytest.raises(ep.EngineParamError, match="ÇALIŞIRKEN"):
        c.write_memory(cs["INLINED"].address, codec.encode_value("FLOAT64_IEEE", 2.0, "LITTLE_ENDIAN"))
    assert eng.ws["INLINED"] == [1.5]
    c.write_memory(cs["IGN_ON_SPD"].address, codec.encode_value("FLOAT32_IEEE", 5100.0, "LITTLE_ENDIAN"))
    assert ("set_param", "mdl", "SimulationCommand", "update") in eng.calls
    eng.fail_update = True
    with pytest.raises(ep.EngineParamError, match="güncelleme"):
        c.write_memory(cs["IGN_ON_SPD"].address, codec.encode_value("FLOAT32_IEEE", 5000.0, "LITTLE_ENDIAN"))


def test_no_engine_and_bad_address():
    params, _ = ep.parse_listing(json.dumps(LISTING))
    ep.build_summary(params)
    c = ep.EngineParamClient(lambda: None, params)
    with pytest.raises(ep.EngineParamError, match="bağlı değil"):
        c.read_memory(params[0].address, 4)
    c2 = ep.EngineParamClient(lambda: FakeEngine(), params)
    with pytest.raises(ep.EngineParamError):
        c2.read_memory(0xDEAD, 4)


def test_load_from_engine(tmp_path):
    f = tmp_path / "p.m"
    f.write_text("IGN_ON_SPD=Simulink.Parameter;")
    eng = FakeEngine()
    params, skipped = ep.load_from_engine(eng, str(f))
    assert len(params) == 5 and len(skipped) == 2
    assert any("run(" in c for c in eng.calls if isinstance(c, str))
    with pytest.raises(ep.EngineParamError):
        ep.load_from_engine(eng, str(tmp_path / "yok.m"))


def test_attach_backend_does_not_quit_user_session():
    from app.sim_bridge import matlab_ctl as mc

    class E:
        quit_called = False
        def load_system(self, m, nargout=0): pass
        def quit(self): E.quit_called = True

    own = mc.MatlabEngineBackend(engine_factory=E)
    own.connect("m"); own.close()
    assert E.quit_called
    E.quit_called = False
    att = mc.MatlabEngineBackend(engine_factory=E, attach=True)
    att.connect("m"); assert att.engine is not None; att.close()
    assert not E.quit_called


class _GuiEngine(FakeEngine):
    def load_system(self, m, nargout=0):
        pass

    def get_param(self, m, k):
        return "stopped"

    def quit(self):
        pass


def test_gui_loads_m_file_and_writes_through_engine(qapp, tmp_path, monkeypatch):
    """Ana pencere: model paneli MATLAB Engine ile bağlı -> .m seç -> sentetik A2L -> kalibrasyon yazımı workspace'e gider."""
    import time
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    from app.sim_bridge import matlab_ctl as mc
    from tests.qt_helpers import dispose
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        mfile = tmp_path / "params.m"
        mfile.write_text("IGN_ON_SPD=Simulink.Parameter;")
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(mfile), "")))
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
        monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
        w._on_sim_mfile_requested()                       # model bağlı değil: hiçbir şey yüklenmez
        assert w.mil_engine_params is None
        eng = _GuiEngine()
        w.model_ctl = mc.ModelController(mc.MatlabEngineBackend(engine_factory=lambda: eng))
        w.model_ctl.connect("mdl")
        end = time.time() + 3
        while time.time() < end and w.model_ctl.state != "READY":
            time.sleep(0.02)
        assert w.model_ctl.state == "READY"
        w._on_sim_mfile_requested()
        assert [p.name for p in w.mil_engine_params][:1] == ["IGN_ON_SPD"]
        summary = w.a2l_tab.db.summary
        assert summary is not None and w.a2l_tab.db.path is None
        w._apply_engine_params()
        assert w.ccp_client is not None
        ch = next(c for c in summary.characteristics if c.name == "IGN_ON_SPD")
        from app.ccp import codec
        w.ccp_client.write_memory(ch.address, codec.encode_value("FLOAT32_IEEE", 5300.0, "LITTLE_ENDIAN"), verify=True)
        assert eng.ws["IGN_ON_SPD"] == [5300.0]
    finally:
        if w.model_ctl is not None:
            w.model_ctl.close()
        dispose(w)
