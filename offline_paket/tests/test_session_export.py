"""Aşama 4: kayıtlı oturumu yükleme, listeleme ve MDF4/ASC/LOG/CSV/MAT dışa aktarma (geri okuma ile doğrulanır)."""
import os
import time

import can
import numpy as np
import pytest

from app import session_export as sx
from app.session_recorder import SessionRecorder


@pytest.fixture
def session(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "Deneme", meta={"user": "z", "mode": "REAL"})
    t0 = rec._t0
    rec.register_signal("dbc:ENG.rpm", "rpm", "PCAN", "monotonic")
    rec.register_signal("a2l:Tt5", "°C", "CCP", "monotonic")
    for i in range(50):
        rec.record("dbc:ENG.rpm", 1000 + i, t0 + i * 0.1)
    for i in range(10):                                   # farklı örnekleme anları
        rec.record("a2l:Tt5", 600 + i, t0 + 0.37 + i * 0.5)
    rec.record_frame(can.Message(arbitration_id=0x100, data=b"\x01\x02", is_extended_id=False, timestamp=t0 + 0.2))
    rec.record_frame(can.Message(arbitration_id=0x1ABCDE, data=b"\xff", is_extended_id=True, timestamp=t0 + 0.4), rx=False)
    rec.add_marker("Motor start", t0 + 1.0)
    rec.stop()
    return sx.load_session(rec.path)


def test_load_session_values_meta_events(session):
    assert session.signals() == ["a2l:Tt5", "dbc:ENG.rpm"]
    t, v = session.arrays("dbc:ENG.rpm")
    assert len(t) == 50 and v[0] == 1000 and t[1] - t[0] == pytest.approx(0.1, abs=1e-3)
    assert session.unit("dbc:ENG.rpm") == "rpm" and session.source("a2l:Tt5") == "CCP"
    assert session.meta["user"] == "z" and any(e[2] == "MARKER" for e in session.events)


def test_mdf4_roundtrip_keeps_names_units_and_own_timestamps(session, tmp_path):
    from asammdf import MDF
    out = str(tmp_path / "o.mf4")
    assert sx.export(session, "mf4", out) == out
    with MDF(out) as m:
        rpm, tt5 = m.get("dbc:ENG.rpm"), m.get("a2l:Tt5")
        assert rpm.unit == "rpm" and tt5.unit == "°C"
        assert len(rpm.samples) == 50 and len(tt5.samples) == 10
        assert tt5.timestamps[1] - tt5.timestamps[0] == pytest.approx(0.5, abs=1e-3)   # kendi zaman tabanı
        assert tt5.timestamps[0] == pytest.approx(0.37, abs=1e-3)
        assert np.allclose(tt5.samples, np.arange(600, 610))
        assert "source=CCP" in (tt5.comment or "")


def test_asc_and_log_are_raw_can_and_candump(session, tmp_path):
    asc = sx.export(session, "asc", str(tmp_path / "o.asc"))
    msgs = list(can.ASCReader(asc))
    assert [m.arbitration_id for m in msgs] == [0x100, 0x1ABCDE]
    log = sx.export(session, "log", str(tmp_path / "o.log"))
    assert open(log, encoding="utf-8").read() == open(asc, encoding="utf-8").read()      # ASC içerikli .log
    cd = sx.export(session, "candump", str(tmp_path / "c.log"))
    got = list(can.CanutilsLogReader(cd))
    assert [m.arbitration_id for m in got] == [0x100, 0x1ABCDE] and got[1].is_extended_id


def test_csv_and_mat_export(session, tmp_path):
    from scipy.io import loadmat
    c = sx.export(session, "csv", str(tmp_path / "o.csv"))
    assert open(c, encoding="utf-8").read().startswith("time,signal,value,unix_time")
    m = loadmat(sx.export(session, "mat", str(tmp_path / "o.mat")))
    assert m["dbc_ENG_rpm"]["values"][0, 0].size == 50 and str(m["dbc_ENG_rpm"]["unit"][0, 0][0]) == "rpm"


def test_asc_export_without_frames_raises(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "bos")
    rec.record("s", 1.0)
    rec.stop()
    sd = sx.load_session(rec.path)
    with pytest.raises(ValueError):
        sx.export(sd, "asc", str(tmp_path / "x.asc"))
    with pytest.raises(ValueError):
        sx.export(sd, "bilinmeyen", str(tmp_path / "x"))


def test_load_tolerates_truncated_corrupt_and_nonfinite_rows(tmp_path):
    p = tmp_path / "k.csv"
    p.write_text("time,signal,value,unix_time\n0.0,a,1,100\n1.0,a,nan,101\nbozuk\n2.0,a,3,102\n3.0,a,4", encoding="utf-8")
    sd = sx.load_session(str(p))
    assert list(sd.values["a"]) == [1.0, 3.0] and sd.skipped_rows == 3
    assert sd.meta == {} and sd.events == []


def test_list_sessions_marks_crashed_as_recovered(tmp_path, session):
    d = os.path.dirname(session.path)
    # çökmüş kayıt benzetimi: durum 'recording' kalmış
    crashed = os.path.join(d, "coktu_20200101_000000")
    open(crashed + ".csv", "w").write("time,signal,value,unix_time\n0,a,1,1\n")
    import json
    json.dump({"status": "recording", "name": "çöktü", "start_unix": time.time() + 5}, open(crashed + ".meta.json", "w"))
    lst = sx.list_sessions(d)
    by = {x["name"]: x for x in lst}
    assert by["çöktü"]["status"] == "recovered" and by["Deneme"]["status"] == "complete" and by["Deneme"]["has_asc"]
    assert lst[0]["name"] == "çöktü"                         # yeniden eskiye
    assert sx.list_sessions(str(tmp_path / "yok")) == []


def test_large_session_loads_with_compact_memory(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "buyuk")
    for i in range(100_000):
        rec.record("s", i * 0.5, rec._t0 + i * 0.001)
    rec.stop()
    t0 = time.perf_counter()
    sd = sx.load_session(rec.path)
    assert len(sd.values["s"]) == 100_000 and time.perf_counter() - t0 < 10
    assert sd.values["s"].itemsize == 8
