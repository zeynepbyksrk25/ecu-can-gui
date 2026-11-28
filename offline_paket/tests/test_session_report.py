
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


def test_report_calibration_uses_red_arrow_language_and_summary(tmp_path):
    sd = _session(tmp_path)
    h = sr.build_report_html(sd)
    assert "<span class='chg'>↑ +5 </span>" not in h                      # birimsiz parametrede sondaki boşluk yok
    assert "↑ +5</span>" in h                                              # 90 → 95: kırmızı artış oku + fark
    assert ".chg{color:#C22A1D" in h                                       # ok rengi kırmızı (arayüzle aynı)
    assert "referans = kayıttaki ilk değer" in h                           # referans açıkça belirtilir (uydurma yok)
    summ = {r["name"]: r for r in sr.calibration_summary(sr.calibration_changes(sd))}
    r = summ["FuelLimit"]
    assert (r["first"], r["last"], r["net"], r["up"], r["down"]) == (90.0, 95.0, 5.0, 1, 0)   # ilk örnek değişiklik sayılmaz


def test_report_arrow_down_unchanged_and_first_sample_have_no_arrow():
    assert "↓ -10" in sr._arrow_html(100.0, 90.0) and "chg" in sr._arrow_html(100.0, 90.0)
    assert sr._arrow_html(5.0, 5.0) == "—" and sr._arrow_html(None, 5.0) == "—"
    cal = [{"t": 0.0, "name": "K", "old": None, "new": 1.0, "unit": ""},
           {"t": 1.0, "name": "K", "old": 1.0, "new": 3.0, "unit": ""},
           {"t": 2.0, "name": "K", "old": 3.0, "new": 2.0, "unit": ""}]
    r = sr.calibration_summary(cal)[0]
    assert (r["up"], r["down"], r["net"]) == (1, 1, 1.0)
