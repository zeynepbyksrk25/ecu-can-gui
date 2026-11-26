"""Senaryo paneli + MainWindow bağlamı (MIL, sahte model)."""
import os
import time

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_mil_integration import DATA, mil  # noqa: F401 (fixture)


def _pump(cond, t=8.0):
    end = time.time() + t
    while time.time() < end:
        QApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_scenario_runs_against_mil_model_and_records_markers(mil, tmp_path):  # noqa: F811
    import json
    w, model = mil
    panel = w.session_tab.scenario_panel
    raw = {"name": "MIL deneme", "steps": [
        {"do": "set", "signal": "OVERRIDE.pump_dc", "value": 30},
        {"do": "wait", "signal": "ENG_STATUS.rpm", "op": ">=", "value": 2000, "timeout": 6},
        {"do": "marker", "label": "RPM tamam"},
        {"do": "check", "signal": "ENG_STATUS.rpm", "op": ">=", "value": 1, "requirement": "DENEME-1"},
        {"do": "check", "signal": "ENG_STATUS.rpm", "op": "<=", "value": 1}]}
    p = tmp_path / "s.json"
    p.write_text(json.dumps(raw), encoding="utf-8")
    assert panel.open_path(str(p))
    w.session_tab.name_edit.setText("senaryo")
    w.session_tab._on_start()
    dbc = w.transmit_tab.dbc
    cid, data, ext = dbc.encode("ENG_STATUS", {"rpm": 2500.0, "tt2_c": 50.0, "tt2_fault": 0})
    panel.run()

    def feed():
        model.send_frame(cid, data, ext)
        w._drain_rx_queue()
        return panel._runner.status != "RUNNING"
    assert _pump(feed)
    panel._refresh()
    r = panel._runner
    assert [x.status for x in r.results] == ["DONE", "DONE", "DONE", "PASS", "SKIPPED"]
    assert r.verdict == "PASS"
    end = time.time() + 2
    while time.time() < end and not model.received_frames:
        QApplication.processEvents()
        time.sleep(0.01)
    assert model.received_frames and "Sonuç: PASS" in panel.verdict_label.text()
    rep = tmp_path / "rapor.txt"
    panel.write_report(str(rep))
    assert "DENEME-1" in rep.read_text(encoding="utf-8") and os.path.exists(str(rep) + ".json")
    path = w.session_recorder.path
    w.session_tab._on_stop()
    ev = open(path[:-4] + ".events.csv", encoding="utf-8").read()
    assert "RPM tamam" in ev and "SENARYO" in ev
    assert not w.latest_signals_enabled


def test_scenario_model_step_without_controller_errors_safely(mil, tmp_path):  # noqa: F811
    import json
    w, model = mil
    panel = w.session_tab.scenario_panel
    p = tmp_path / "s2.json"
    p.write_text(json.dumps({"steps": [{"do": "model", "cmd": "start"}, {"do": "marker", "label": "x"}]}), encoding="utf-8")
    panel.open_path(str(p))
    panel.run()
    assert _pump(lambda: panel._runner.status != "RUNNING")
    panel._refresh()
    assert [x.status for x in panel._runner.results] == ["ERROR", "ABORTED"]
    assert "Model denetimi bağlı değil" in panel._runner.results[0].detail
