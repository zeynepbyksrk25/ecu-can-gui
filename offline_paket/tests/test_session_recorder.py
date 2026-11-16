import csv

from app.session_recorder import SessionRecorder
from app.signal_hub import SignalHub


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_records_and_survives_without_stop_flush(tmp_path):
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "Soğutma testi #3")
    assert "Soğutma_testi_3" in path
    rec.record("a2l:Rpm", 1234.5, t_unix=rec._t0 + 1.0)
    rec.record("a2l:Rpm", "bozuk")          # sayısal olmayan yok sayılır
    rec.record("a2l:Rpm", float("nan"))
    rec.stop()
    rows = _rows(path)
    assert rows[0] == ["time", "signal", "value", "unix_time"]
    assert rows[1][:3] == ["1.0000", "a2l:Rpm", "1234.5"]
    assert len(rows) == 2
    rec.record("a2l:Rpm", 1.0)               # kapalıyken yazılmaz
    assert len(_rows(path)) == 2


def test_dedup_and_unique_file(tmp_path):
    rec = SessionRecorder()
    p1 = rec.start(str(tmp_path), "x")
    t = rec._t0
    rec.record("s", 1.0, t_unix=t + 1.000)
    rec.record("s", 1.0, t_unix=t + 1.010)   # aynı değer, ikinci kaynaktan: tekrar yazılmaz
    rec.record("s", 2.0, t_unix=t + 1.020)
    rec.stop()
    assert len(_rows(p1)) == 3
    assert rec.rows == 2


def test_hub_tap_records_even_inactive_signals(tmp_path):
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "t")
    hub = SignalHub()
    hub.tap = rec.record
    hub.push("gauge:RPM", 100)               # hiçbir panelde etkin değil
    hub.push("math:x", 5)                    # türetilmiş: yazılmaz
    rec.stop()
    rows = _rows(path)
    assert [r[1] for r in rows[1:]] == ["gauge:RPM"]


def test_recorded_csv_can_be_imported_back(tmp_path):
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "t")
    rec.record("a2l:T", 10.0, t_unix=rec._t0 + 0.5)
    rec.record("a2l:T", 12.0, t_unix=rec._t0 + 1.5)
    rec.stop()
    hub = SignalHub()
    added = hub.import_csv(path, "oturum")
    assert added == ["csv:oturum:a2l:T"]
    t, v = hub.get(added[0])
    assert list(v) == [10.0, 12.0]


def test_write_error_stops_recording(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "t")

    class Bad:
        def writerow(self, *_a):
            raise OSError("disk dolu")
    rec._writer = Bad()
    rec.record("s", 1.0)
    assert rec.error == "disk dolu" and not rec.is_active


def test_main_window_session_writes_csv(qapp, tmp_path, monkeypatch):
    import pytest
    pytest.importorskip("PySide6")
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    st = w.session_tab
    st.name_edit.setText("Deneme")
    st._on_start()
    assert w.session_recorder.is_active
    w.workspace_tab.push("gauge:RPM", 4321.0)
    path = w.session_recorder.path
    st._on_stop()
    assert not w.session_recorder.is_active
    rows = _rows(path)
    assert rows[1][1:3] == ["gauge:RPM", "4321"]
    assert "Deneme" in path and "oturum_kayitlari" in path
    w.close()
