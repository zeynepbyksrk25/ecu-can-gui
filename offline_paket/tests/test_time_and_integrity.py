"""Gerçek zaman (monotonik) + sistem zamanı ayrı kaydı, saat atlaması, fsync, ECU güç kesintisi olayları, kayıt bütünlüğü
ve sonradan inceleme (rapor / oturum tarayıcı)."""
import csv
import os
import re
import time

import pytest

from app import session_export as sx
from app import session_report as sr
from app.session_recorder import SessionRecorder, system_time_text

SYS_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}$")


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def _recorder(tmp_path, name="T"):
    rec = SessionRecorder()
    rec.start(str(tmp_path), name)
    return rec


# ------------------------------------------------------------------ iki zaman, iki sütun
def test_system_time_text_format_and_ms_rounding():
    t = time.mktime((2026, 11, 28, 14, 3, 22, 0, 0, -1)) + 0.1234
    assert system_time_text(t) == "2026-11-28 14:03:22.123"
    base = time.mktime((2026, 11, 28, 14, 3, 22, 0, 0, -1))
    assert system_time_text(base + 0.5) == "2026-11-28 14:03:22.500" and system_time_text(base + 1.0) == "2026-11-28 14:03:23.000"
    assert system_time_text(base + 0.9996) == "2026-11-28 14:03:22.999"          # ms'ye YUKARI yuvarlanmaz: saniye taşmaz
    assert SYS_RE.match(system_time_text(time.time()))


def test_csv_and_events_carry_real_time_and_system_time(tmp_path):
    rec = _recorder(tmp_path)
    t = rec._t0 + 2.5
    rec.record("dbc:E.rpm", 1500.0, t)
    rec.record_event("MARKER", "işaret, virgüllü \"metin\"", t)
    rec.stop()
    data = _rows(rec.path)
    assert data[0] == ["time", "signal", "value", "unix_time", "system_time"]
    r = data[1]
    assert abs(float(r[0]) - 2.5) < 0.01                                  # gerçek zaman: oturum başından sn
    assert abs(float(r[3]) - t) < 0.001 and SYS_RE.match(r[4])            # sistem zamanı: epoch ms + okunabilir
    assert r[4] == system_time_text(float(r[3]))                          # ikisi aynı anı gösterir
    ev = _rows(rec.events_path)
    assert ev[0] == ["time", "unix_time", "kind", "text", "system_time"]
    marker = next(x for x in ev if x[2] == "MARKER")
    assert marker[3] == "işaret, virgüllü \"metin\"" and SYS_RE.match(marker[4])   # metin ve tırnak bozulmaz
    meta = sx.load_session(rec.path).meta
    assert meta["time_source"] == "monotonic" and meta["csv_columns"][-1] == "system_time"
    assert isinstance(meta["utc_offset_min"], int) and meta["timezone"]


def test_old_four_column_files_still_load(tmp_path):
    p = tmp_path / "eski.csv"
    p.write_text("time,signal,value,unix_time\n0.0,a,1,100\n1.0,a,2,101\n", encoding="utf-8")
    (tmp_path / "eski.events.csv").write_text("time,unix_time,kind,text\n0.5,100.5,MARKER,x\n", encoding="utf-8")
    sd = sx.load_session(str(p))
    assert list(sd.values["a"]) == [1.0, 2.0] and sd.events == [(0.5, 100.5, "MARKER", "x")] and sd.skipped_rows == 0
    assert sd.integrity()[0][0] == "warn"                                  # meta yok: açıkça uyarılır


# ------------------------------------------------------------------ saat atlaması: gerçek zaman bozulmaz
def test_real_time_column_is_immune_to_system_clock_jump(tmp_path, monkeypatch):
    shift = [0.0]
    real_time = time.time
    monkeypatch.setattr("app.session_recorder.time.time", lambda: real_time() + shift[0])
    rec = _recorder(tmp_path)
    rec.record("dbc:E.rpm", 1.0)
    time.sleep(0.2)
    shift[0] = 3600.0                                    # NTP/elle ayar: saat 1 saat ileri atladı
    assert rec.check_clock() == pytest.approx(3600.0, abs=0.1)
    rec.record("dbc:E.rpm", 2.0)
    assert rec.check_clock() is None                     # tekrar uyarılmaz (yeni referans)
    rec.stop()
    sd = sx.load_session(rec.path)
    tr, tu = list(sd.t_rel["dbc:E.rpm"]), list(sd.t_unix["dbc:E.rpm"])
    assert 0.15 < tr[1] - tr[0] < 1.0                    # gerçek zaman: ~0,2 sn (atlama YOK)
    assert tu[1] - tu[0] == pytest.approx(3600.2, abs=1.0)   # sistem saati: atlama görünür
    saat = [e for e in sd.events if e[2] == "SAAT"]
    assert len(saat) == 1 and "+3600" in saat[0][3]
    assert sd.clock_jumps()[0]["delta_s"] == pytest.approx(3600.0, abs=0.1)
    ax = sd.t_axis("dbc:E.rpm")
    assert 0.15 < ax[1] - ax[0] < 1.0                    # çizim ekseni monotonik: eğri bozulmaz
    assert any("Sistem saati" in t and lv == "warn" for lv, t in sd.integrity())


def test_small_clock_drift_is_not_reported(tmp_path):
    rec = _recorder(tmp_path)
    assert rec.check_clock(rec._t0 + 0.1, rec._t0_mono + 0.1) is None
    rec.stop()


# ------------------------------------------------------------------ fsync
def test_fsync_runs_on_stop_and_on_periodic_sync(tmp_path, monkeypatch):
    calls = []
    real = os.fsync
    monkeypatch.setattr("app.session_recorder.os.fsync", lambda fd: (calls.append(fd), real(fd))[1])
    rec = _recorder(tmp_path)
    rec.record("dbc:E.rpm", 1.0)
    time.sleep(0.3)
    rec._flush(sync=True)
    assert len(calls) >= 2                               # csv + events
    n = len(calls)
    rec.stop()
    assert len(calls) > n                                # kapanışta da diske zorlanır


def test_fsync_failure_is_swallowed(tmp_path, monkeypatch):
    rec = _recorder(tmp_path)
    monkeypatch.setattr("app.session_recorder.os.fsync", lambda fd: (_ for _ in ()).throw(OSError("desteklenmiyor")))
    rec._flush(sync=True)                                # istisna yok
    rec.stop()
    assert rec.error is None


# ------------------------------------------------------------------ boşluk / bütünlük
def _gap_session(tmp_path, with_cause: bool):
    rec = _recorder(tmp_path)
    t0 = rec._t0
    for i in range(10):
        rec.record("dbc:E.rpm", 1000 + i, t0 + i * 0.1)
    if with_cause:
        rec.record_event("BAGLANTI", "CAN trafiği kesildi: 3.2 sn'dir mesaj yok (ECU kapalı olabilir)", t0 + 3.5)
        rec.record_event("BAGLANTI", "CAN trafiği geri geldi (kesinti ≈ 6.0 sn sürdü)", t0 + 7.0)
    for i in range(10):
        rec.record("dbc:E.rpm", 2000 + i, t0 + 7.0 + i * 0.1)
    rec.stop()
    return sx.load_session(rec.path)


def test_ecu_power_loss_gap_is_explained_by_events_and_recording_continues(tmp_path):
    sd = _gap_session(tmp_path, with_cause=True)
    gaps = sd.data_gaps()
    assert len(gaps) == 1 and gaps[0]["duration_s"] == pytest.approx(6.1, abs=0.2)
    assert "CAN trafiği kesildi" in gaps[0]["cause"]
    assert list(sd.values["dbc:E.rpm"])[:1] == [1000.0] and list(sd.values["dbc:E.rpm"])[-1] == 2009.0   # kayıt kesinti sonrası sürdü
    levels = [lv for lv, _ in sd.integrity()]
    assert "warn" in levels and "error" not in levels


def test_unexplained_gap_is_flagged_as_error(tmp_path):
    sd = _gap_session(tmp_path, with_cause=False)
    gaps = sd.data_gaps()
    assert len(gaps) == 1 and gaps[0]["cause"] == ""
    assert ("error", "1 boşluğun nedeni olay günlüğünde YOK (açıklanamayan veri kaybı).") in sd.integrity()


def test_clean_session_integrity_ok_and_slow_ccp_signals_make_no_gap(tmp_path):
    rec = _recorder(tmp_path)
    t0 = rec._t0
    for i in range(5):
        rec.record("dbc:E.rpm", i, t0 + i * 0.1)
    rec.record("a2l:Yavas", 1.0, t0 + 0.0)
    rec.record("a2l:Yavas", 2.0, t0 + 30.0)              # CCP değişince yazılır: uzun sessizlik meşru
    rec.stop()
    sd = sx.load_session(rec.path)
    assert sd.data_gaps() == [] and sd.integrity() == [("ok", "Kayıt bütünlüğü: sorun bulunmadı.")]


def test_integrity_reports_dropped_recovered_and_error(tmp_path):
    sd = _gap_session(tmp_path, with_cause=True)
    sd.meta.update({"dropped": 7, "status": "recording"})
    txt = " | ".join(t for _lv, t in sd.integrity())
    assert "7 öğe" in txt and "beklenmedik" in txt
    sd.meta.update({"status": "error", "error": "disk dolu"})
    assert ("error", "Kayıt hata ile bitti: disk dolu") in sd.integrity()


# ------------------------------------------------------------------ ana pencere: ECU gücü / hat sessizliği olayları
def test_main_window_logs_bus_silence_and_return_and_recording_keeps_running(qapp, tmp_path):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        w.session_recorder.start(str(tmp_path), "ECU güç testi")
        w._track_bus_silence(0.5, now=100.0)                       # trafik var: olay yok
        assert not [e for e in w.event_log.entries if "trafiği" in e.message]
        w._track_bus_silence(5.0, now=100.0)                       # 3 sn eşiği aşıldı
        w._track_bus_silence(9.0, now=104.0)                       # aynı kesinti: ikinci olay YOK
        w._track_bus_silence(0.1, now=110.0)                       # trafik geri geldi
        msgs = [e.message for e in w.event_log.entries if "trafiği" in e.message]
        assert len(msgs) == 2 and "kesildi" in msgs[0] and "ECU kapalı" in msgs[0]
        assert "geri geldi" in msgs[1] and "15.0 sn" in msgs[1]    # kesinti son mesajdan ölçülür (95 → 110)
        assert w.session_recorder.is_active                        # kayıt DURMADI
        path = w.session_recorder.path
        w.session_recorder.stop()
        ev = sx.load_session(path).events
        texts = [t for _tr, _tu, k, t in ev if k == "BAGLANTI"]
        assert any("kesildi" in t for t in texts) and any("geri geldi" in t for t in texts)
    finally:
        w.close()


# ------------------------------------------------------------------ sonradan inceleme: rapor + tarayıcı
def test_report_shows_integrity_gaps_and_both_clocks(tmp_path):
    sd = _gap_session(tmp_path, with_cause=True)
    h = sr.build_report_html(sd)
    assert "Kayıt bütünlüğü" in h and "CAN veri boşlukları (1)" in h
    assert "Gerçek zaman (sn)" in h and "Sistem saati" in h and "gerçek zaman: monotonik" in h
    cells = re.findall(r"<td>(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})</td>", h)
    assert len(cells) >= 2                                     # olay satırlarında okunabilir sistem saati var
    assert "CAN trafiği kesildi" in h


def test_old_recording_report_says_time_is_derived_from_system_clock(tmp_path):
    sd = _gap_session(tmp_path, with_cause=True)
    sd.meta.pop("time_source")
    assert "sistem saatinden türetilmiş (eski kayıt)" in sr.build_report_html(sd)


def test_browser_shows_events_with_both_times_and_integrity(qapp, tmp_path):
    from app.ui.session_browser import SessionBrowser
    sd = _gap_session(tmp_path, with_cause=True)
    from app.ui.session_browser import AnalysisWindow
    v = AnalysisWindow(sd)
    t = v.events_table
    assert t.columnCount() == 4 and t.rowCount() == len(sd.events)
    heads = [t.horizontalHeaderItem(i).text() for i in range(4)]
    assert heads[0].startswith("Gerçek zaman") and heads[1] == "Sistem saati"
    kinds = [t.item(i, 2).text() for i in range(t.rowCount())]
    row = kinds.index("BAGLANTI")
    assert SYS_RE.match(t.item(row, 1).text()) and re.match(r"^-?\d+\.\d{3}$", t.item(row, 0).text())
    assert "gerçek zaman" in v.info.text() and "veri boşluğu" in v.info.text()
    assert SessionBrowser is not None


# ------------------------------------------------------------------ çizim: veri boşluğunda çizgi kopar
def test_break_gaps_inserts_nan_only_for_real_gaps():
    import numpy as np
    from app.trend_model import break_gaps
    t = np.concatenate([np.arange(0, 6, 0.05), np.arange(12, 14, 0.05)])
    v = np.arange(t.size, dtype=float)
    t2, v2 = break_gaps(t, v)
    assert t2.size == t.size + 1 and np.isnan(v2).sum() == 1
    k = int(np.nonzero(np.isnan(v2))[0][0])
    assert 6 < t2[k] < 12 and t[0] == t2[0] and v2[k - 1] == v[k - 1] and v2[k + 1] == v[k]    # veri aynen korunur
    assert not np.isnan(v).any()                                                                 # girdi değişmedi
    # aralıksız veri ve kısa kesinti (<5 sn) dokunulmaz
    t3, v3 = break_gaps(np.arange(0, 10, 0.05), np.zeros(200))
    assert t3.size == 200 and not np.isnan(v3).any()
    t4 = np.concatenate([np.arange(0, 2, 0.05), np.arange(4, 6, 0.05)])
    assert break_gaps(t4, np.zeros(t4.size))[0].size == t4.size
    # yavaş (değişince yazılan) sinyal: büyük ama düzenli aralık sahte kopma YAPMAZ
    ts = np.arange(0, 600, 30.0)
    assert break_gaps(ts, np.zeros(ts.size))[0].size == ts.size


def test_analysis_plot_breaks_line_across_ecu_power_gap(qapp, tmp_path):
    import numpy as np
    from app.ui.session_browser import AnalysisWindow
    sd = _gap_session(tmp_path, with_cause=True)
    w = AnalysisWindow(sd)
    w.show()
    w.trend._tick()
    ser = w.trend._series["dbc:E.rpm"]
    x, y = ser.curve.getData()
    assert np.isnan(y).sum() == 1                       # 6 sn'lik ECU kesintisinde düz çizgi çizilmez
