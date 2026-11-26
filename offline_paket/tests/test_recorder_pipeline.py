"""Kayıt altyapısı (Aşama 3): asenkron yazma, duraklat/sürdür, olay/işaret, ham CAN (ASC), üst veri, veri kaybı sayaçları."""
import csv
import json
import os
import time

import can
import pytest

from app.session_recorder import FrameRecorder, SessionRecorder


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))


def test_record_does_not_block_and_stop_drains_queue(tmp_path):
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "hiz")
    t0 = time.perf_counter()
    for i in range(20000):
        rec.record("s", i, rec._t0 + i * 0.001)
    assert time.perf_counter() - t0 < 2.0
    rec.stop()
    assert rec.rows == 20000 and len(_rows(path)) == 20001 and rec.dropped == 0


def test_queue_overflow_is_counted_not_silent(tmp_path):
    rec = SessionRecorder(queue_max=5)
    rec.start(str(tmp_path), "tasma")
    # yazma iş parçacığını yavaşlat: kuyruk kesin dolsun
    orig = rec._write

    def slow(item):
        time.sleep(0.05)
        orig(item)
    rec._write = slow
    accepted = sum(1 for i in range(60) if rec.record("s", i))
    assert rec.dropped == 60 - accepted and rec.dropped > 0
    rec.stop()
    assert rec.meta["dropped"] == rec.dropped
    assert rec.rows <= accepted


def test_pause_resume_and_events(tmp_path):
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "duraklat")
    rec.record("s", 1.0)
    rec.pause()
    assert rec.state == "DURAKLATILDI"
    assert rec.record("s", 2.0) is False and rec.paused_skipped == 1
    rec.add_marker("Motor start")                       # duraklatılmışken de işaret yazılır
    rec.resume()
    assert rec.state == "KAYITTA"
    rec.record("s", 3.0)
    rec.record_event("BAGLANTI_KOPTU", "PCAN bağlantısı koptu")
    rec.stop()
    assert [r[2] for r in _rows(path)[1:]] == ["1", "3"]
    ev = _rows(rec.events_path)
    kinds = [r[2] for r in ev[1:]]
    assert kinds == ["BASLANGIC", "DURAKLATMA", "MARKER", "DEVAM", "BAGLANTI_KOPTU"]
    assert ev[3][3] == "Motor start"
    assert rec.state == "DURDU"


def test_nonfinite_values_never_written(tmp_path):
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "n")
    for v in (float("nan"), float("inf"), float("-inf"), "x", None):
        assert rec.record("s", v) is False
        assert rec.record_change("s", v) is False
    rec.stop()
    assert len(_rows(path)) == 1


def test_meta_sidecar_status_and_signal_table(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "meta", meta={"user": "ali", "dbc": {"file": "a.dbc"}})
    rec.register_signal("dbc:ENG.rpm", "rpm", "PCAN", "monotonic")
    rec.update_meta(ecu="M220")
    with open(rec.meta_path, encoding="utf-8") as f:
        assert json.load(f)["status"] == "recording"      # çökerse bu durum 'recording' kalır (kurtarma)
    rec.record("dbc:ENG.rpm", 5.0)
    rec.stop()
    with open(rec.meta_path, encoding="utf-8") as f:
        m = json.load(f)
    assert m["status"] == "complete" and m["user"] == "ali" and m["ecu"] == "M220" and m["rows"] == 1
    assert m["signals"]["dbc:ENG.rpm"] == {"unit": "rpm", "source": "PCAN", "timebase": "monotonic"}
    assert m["duration_s"] >= 0 and "end_unix" in m


def test_raw_can_frames_written_as_standard_asc_and_readable(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "asc")
    t = rec._t0
    rec.record_frame(can.Message(arbitration_id=0x1A0, data=bytes(range(8)), is_extended_id=False, timestamp=t + 0.10))
    rec.record_frame(can.Message(arbitration_id=0x18FF0001, data=b"\x01\x02", is_extended_id=True, timestamp=t + 0.25),
                     rx=False)
    rec.add_marker("Test", t + 0.3)
    rec.stop()
    assert rec.frames == 2
    path = rec.meta["files"]["asc"]
    full = os.path.join(str(tmp_path), path)
    text = open(full, encoding="utf-8").read()
    assert "base hex  timestamps absolute" in text and "Begin Triggerblock" in text and "End TriggerBlock" in text
    msgs = list(can.ASCReader(full))                        # python-can'in standart ASC okuyucusu geri okur
    assert [m.arbitration_id for m in msgs] == [0x1A0, 0x18FF0001]
    assert msgs[0].data == bytes(range(8)) and msgs[0].is_extended_id is False
    assert msgs[1].is_extended_id is True and msgs[1].is_rx is False and msgs[0].is_rx is True
    assert msgs[1].timestamp - msgs[0].timestamp == pytest.approx(0.15, abs=1e-3)


def test_frame_recorder_forwards_raw_frames_even_without_dbc(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "raw")
    fr = FrameRecorder(rec, lambda: None)
    fr.start()
    for i in range(10):
        fr.submit(can.Message(arbitration_id=0x100 + i, data=b"\x00", is_extended_id=False, timestamp=rec._t0 + i * 0.01))
    fr.stop()
    rec.stop()
    assert rec.frames == 10 and rec.rows == 0


def test_stats_while_recording(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "st")
    rec.record("s", 1.0)
    time.sleep(0.25)
    st = rec.stats()
    assert st["state"] == "KAYITTA" and st["elapsed_s"] > 0.2 and st["bytes"] > 0 and st["dropped"] == 0
    rec.stop()
    e1 = rec.stats()["elapsed_s"]
    time.sleep(0.1)
    assert rec.stats()["elapsed_s"] == e1                    # durduktan sonra süre akmaz


def test_restart_creates_new_session_files(tmp_path):
    rec = SessionRecorder()
    a = rec.start(str(tmp_path), "x")
    b = rec.start(str(tmp_path), "x")
    rec.stop()
    assert a != b and os.path.exists(a) and os.path.exists(b)


def test_main_window_record_controls_meta_markers_and_chip(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    st = w.session_tab
    assert w.rec_chip.text() == "REC yok" and not st.pause_button.isEnabled()
    st.name_edit.setText("MIL dene")
    st.operator_edit.setText("Zeynep")
    st._on_start()
    assert w.rec_chip.text() == "● REC" and w.rec_chip.property("state") == "rec"
    assert st.pause_button.isEnabled() and st.marker_button.isEnabled()
    st.pause_button.click()
    assert w.session_recorder.is_paused and "DURAKLATILDI" in w.rec_chip.text()
    assert st.pause_button.text() == "Sürdür"
    st.pause_button.click()
    assert not w.session_recorder.is_paused
    st.marker_combo.setCurrentText("Idle")
    st.marker_button.click()
    w._log_event("HATA", "iletişim hatası denemesi")
    w._record_cal_sample("Kp", 1.35, "")
    assert "düşen" in st.stats_label.text() or w.session_recorder.stats()["dropped"] == 0
    meta_path = w.session_recorder.meta_path
    path = w.session_recorder.path
    st._on_stop()
    assert w.rec_chip.text() == "REC yok"
    m = json.load(open(meta_path, encoding="utf-8"))
    assert m["operator"] == "Zeynep" and m["status"] == "complete" and m["mode"] == "REAL"
    assert m["connection"]["connected"] is False and "dbc" in m and "a2l" in m
    kinds = [r[2] for r in _rows(m_events(meta_path))[1:]]
    assert "MARKER" in kinds and "HATA" in kinds and "DURAKLATMA" in kinds and "DEVAM" in kinds
    assert ["cal:Kp", "1.35"] == [r[1:3] for r in _rows(path)[1:] if r[1] == "cal:Kp"][0]
    w.close()


def m_events(meta_path):
    return meta_path.replace(".meta.json", ".events.csv")


def test_burst_of_200k_samples_is_written_without_loss(tmp_path):
    """Performans: arayüz zamanlayıcısından bağımsız yoğun akış kayıpsız yazılır (kuyruk 500k, toplu yazma)."""
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "yogun")
    for i in range(200_000):
        rec.record(f"s{i % 8}", i, rec._t0 + i * 0.0005)
    rec.stop()
    assert rec.dropped == 0 and rec.rows == 200_000 and len(_rows(path)) == 200_001


def test_dbc_units_and_source_registered_in_meta(tmp_path):
    from app.dbc import DbcDatabase
    dbc = DbcDatabase()
    dbc.load(os.path.join(os.path.dirname(__file__), "data", "sample.dbc"))
    rec = SessionRecorder()
    rec.start(str(tmp_path), "birim")
    fr = FrameRecorder(rec, lambda: dbc)
    fr.start()
    cid, data, ext = dbc.encode("ENG_STATUS", {"rpm": 100.0, "tt2_c": 30.0, "tt2_fault": 0})
    fr.submit(can.Message(arbitration_id=cid, data=data, is_extended_id=ext, timestamp=rec._t0 + 0.1))
    fr.stop()
    rec.stop()
    sig = json.load(open(rec.meta_path, encoding="utf-8"))["signals"]
    assert sig["dbc:ENG_STATUS.rpm"] == {"unit": "rpm", "source": "CAN", "timebase": "acquisition_wall_clock"}
    assert sig["dbc:ENG_STATUS.tt2_c"]["unit"] == "degC"
