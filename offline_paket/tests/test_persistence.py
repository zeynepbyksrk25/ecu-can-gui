import json
import os

import pytest

from app.persist import atomic_write_json, load_json


def corrupt_files(d):
    return [f for f in os.listdir(d) if ".corrupt-" in f]


def test_atomic_write_keeps_backup_and_no_tmp(tmp_path):
    p = str(tmp_path / "a.json")
    assert atomic_write_json(p, {"v": 1})
    assert atomic_write_json(p, {"v": 2})
    assert json.load(open(p)) == {"v": 2}
    assert json.load(open(p + ".bak")) == {"v": 1}
    assert not os.path.exists(p + ".tmp")


def test_failed_write_leaves_existing_file_intact(tmp_path):
    p = str(tmp_path / "a.json")
    atomic_write_json(p, {"v": 1})
    assert atomic_write_json(p, {"bad": object()}) is False       # serileştirilemez
    assert json.load(open(p)) == {"v": 1}
    assert not os.path.exists(p + ".tmp")


def test_corrupt_file_quarantined_and_backup_used(tmp_path):
    p = str(tmp_path / "a.json")
    atomic_write_json(p, {"v": 1})
    atomic_write_json(p, {"v": 2})
    open(p, "w").write("{trunc")
    assert load_json(p, {}, dict) == {"v": 1}                      # .bak'tan döndü
    assert len(corrupt_files(tmp_path)) == 1                       # bozuk dosya korunuyor


def test_wrong_root_type_is_default_not_crash(tmp_path):
    p = str(tmp_path / "a.json")
    open(p, "w").write("[1,2]")
    assert load_json(p, "D", dict) == "D"
    assert len(corrupt_files(tmp_path)) == 1


def test_history_survives_bad_entries_and_never_overwrites_evidence(tmp_path):
    from app.history import CalibrationHistory
    p = str(tmp_path / "h.json")
    good = {"timestamp": 1.0, "user": "u", "role": "r", "object_name": "X", "old_value": 1.0,
            "new_value": 2.0, "unit": "bar"}
    json.dump([good, "çöp", {"x": 1}, dict(good, object_name="Y")], open(p, "w"))
    h = CalibrationHistory(p)
    assert [e.object_name for e in h.entries] == ["X", "Y"]
    open(p, "w").write("garbage")
    h2 = CalibrationHistory(p)
    assert h2.entries == [] and corrupt_files(tmp_path)
    h2.add("u", "r", "Z", None, 1.0, "")
    assert corrupt_files(tmp_path), "bozuk dosya yeni kayıtla ezilmemeli"


def test_profiles_unknown_keys_do_not_drop_everything(tmp_path):
    from app.profiles import ProfileStore
    p = str(tmp_path / "p.json")
    json.dump([{"name": "a", "gelecek_alan": 1}, 5, {"name": "b"}], open(p, "w"))
    st = ProfileStore(path=p)
    assert st.names() == ["a", "b"]


@pytest.mark.parametrize("payload", ['[]', '{"motor_start": 5, "actuators": [], "estop": {"value": "x"}}',
                                     '{"graph_signals": 3, "measurement_rpm": 7}', 'null'])
def test_dashboard_config_tolerates_garbage(tmp_path, payload):
    from app.dashboard_config import DashboardConfigStore
    p = str(tmp_path / "d.json")
    open(p, "w").write(payload)
    cfg = DashboardConfigStore(p).load()
    assert cfg.estop.value == 1.0


@pytest.mark.parametrize("payload", ['[]', '{"input_values": {"a": "x"}, "perf_map": 3, "window_s": "q", "graphs": [1]}'])
def test_sim_config_tolerates_garbage(tmp_path, payload):
    from app.sim_interface import SimConfig
    p = str(tmp_path / "s.json")
    open(p, "w").write(payload)
    c = SimConfig(p)
    assert c.window_s == 60 and c.input_values == {}


@pytest.mark.parametrize("payload", ['[]', '{"views": [], "role_overrides": 3, "scenarios": 1, "cycle_overrides": []}'])
def test_control_panel_config_tolerates_garbage(tmp_path, payload):
    from app.control_panel import ControlPanelConfig
    p = str(tmp_path / "c.json")
    open(p, "w").write(payload)
    ControlPanelConfig(p)


def test_audit_log_single_line_and_failure_visible(tmp_path):
    from app.eventlog import EventLog
    p = str(tmp_path / "audit.txt")
    log = EventLog(file_path=p)
    log.add("A", "satır1\n2024\tSAHTE\tadmin\tYönetici\tgizli", user="u\nx", role="r")
    lines = open(p, encoding="utf-8").read().splitlines()
    assert len(lines) == 1 and lines[0].count("\t") == 4
    bad = EventLog(file_path=str(tmp_path / "yok" / "x"))      # klasör sonradan silindi
    os.rmdir(tmp_path / "yok")
    bad.add("A", "m")
    assert bad.write_failures == 1 and bad.entries


def test_workspace_layout_garbage(tmp_path):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from app.ui.workspace_tab import WorkspaceLayoutStore, WorkspaceTab
    p = str(tmp_path / "w.json")
    bad_panel = {"kind": "plot", "title": "x", "geometry": "oops",
                 "state": {"styles": {"A": {"width": 3}}, "signals": ["A"], "mode": "zz"}}
    json.dump({"layouts": {"k": 5}, "last": {"version": "x", "span": "q", "derived": [],
                                              "panels": [bad_panel, 7, {"kind": "yok"}]}}, open(p, "w"))
    st = WorkspaceLayoutStore(p)
    assert st.names() == []
    w = WorkspaceTab(store=st)                 # çökmemeli
    assert len(w._panels) >= 1
    w.shutdown()
    open(p, "w").write("{{{")
    w2 = WorkspaceTab(store=WorkspaceLayoutStore(p))
    assert len(w2._panels) == 1
    w2.shutdown()
