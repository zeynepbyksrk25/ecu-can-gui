
from app import session_export as sx
from app import session_report as sr
from app.session_recorder import SessionRecorder
from app.ui.session_browser import SessionBrowser


def _session(tmp_path):
    dbc = tmp_path / "x.dbc"
    dbc.write_text("VERSION \"\"", encoding="utf-8")
    from app.session_recorder import file_fingerprint
    rec = SessionRecorder()
    rec.start(str(tmp_path), "Rapor <deneme>", meta={"user": "z", "mode": "MIL", "dbc": file_fingerprint(str(dbc))})
    t0 = rec._t0
    rec.register_signal("dbc:E.rpm", "rpm", "Simulink MIL", "simulation_time")
    for i in range(10):
        rec.record("dbc:E.rpm", 1000 + 10 * i, t0 + i)
    rec.record("cal:FuelLimit", 90.0, t0 + 2)
    rec.record("cal:FuelLimit", 95.0, t0 + 6)
    rec.record_event("HATA", "iletişim <hatası>", t0 + 4)
    rec.add_marker("Idle", t0 + 5)
    rec.stop()
    return sx.load_session(rec.path)


def test_report_contains_facts_and_escapes_html(tmp_path):
    sd = _session(tmp_path)
    h = sr.build_report_html(sd)
    assert "Rapor &lt;deneme&gt;" in h and "iletişim &lt;hatası&gt;" in h and "<deneme>" not in h
    assert "1000" in h and "1090" in h and "FuelLimit" in h and "MIL" in h and "SHA-256" in h
    assert "PASS/FAIL kararı içermez" in h and "tamamlandı" in h


def test_calibration_changes_and_stats(tmp_path):
    sd = _session(tmp_path)
    ch = sr.calibration_changes(sd)
    assert [(c["old"], c["new"]) for c in ch] == [(None, 90.0), (90.0, 95.0)]
    st = {r["signal"]: r for r in sr.signal_stats(sd)}
    assert st["dbc:E.rpm"]["min"] == 1000 and st["dbc:E.rpm"]["max"] == 1090 and st["dbc:E.rpm"]["mean"] == 1045


def test_recovered_session_flagged(tmp_path):
    sd = _session(tmp_path)
    sd.meta["status"] = "recording"
    assert "KURTARILDI" in sr.build_report_html(sd)


def test_browser_report_button(qapp, tmp_path):
    _session(tmp_path)
    b = SessionBrowser(lambda: str(tmp_path))
    b.refresh()
    b.table.selectRow(0)
    out = b.report_selected(str(tmp_path / "r.html"))
    assert out and "Test raporu" in open(out, encoding="utf-8").read()
