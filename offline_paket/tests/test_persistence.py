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


def test_modas_sheet_store_garbage_is_tolerated(tmp_path):
    from app.ui.modas.workspace import ModasSheetStore
    p = str(tmp_path / "w.json")
    json.dump({"current": "x", "sheets": [{"name": "S", "windows": [5, {"name": "A"}, {"x": 1}]}, 7, {"name": 3}],
               "math": {"math:ok": {"kind": "scale", "src": "a2l:A"}, "math:bad": 5, "math:nokind": {"src": "x"}}},
              open(p, "w"))
    st = ModasSheetStore(p).load()
    assert [s["name"] for s in st["sheets"]] == ["S"] and st["sheets"][0]["windows"] == [{"name": "A"}]
    assert st["current"] == 0 and set(st["math"]) == {"math:ok"}               # bozuk matematik tanımları atlanır
    open(p, "w").write("{{{")
    assert ModasSheetStore(p).load() is None
    json.dump({"sheets": [{"name": "S", "windows": []}], "math": [1, 2]}, open(p, "w"))
    assert ModasSheetStore(p).load()["math"] == {}                              # math liste ise yok sayılır

