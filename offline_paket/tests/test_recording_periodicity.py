"""Oturum kaydı: her veri KENDİ geliş zamanında ve kendi periyoduyla yazılır (arayüz zamanlayıcısından bağımsız).
CAN: mesajın her gelişinde, tüm sinyaller, karenin zamanıyla. CCP: okumada değer değiştiyse, okuma zamanıyla."""
import csv
import os
import time

import can
import pytest

from app.dbc import DbcDatabase
from app.session_recorder import FrameRecorder, SessionRecorder

DATA = os.path.join(os.path.dirname(__file__), "data")


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.reader(f))[1:]


@pytest.fixture
def dbc():
    d = DbcDatabase()
    d.load(os.path.join(DATA, "sample.dbc"))
    return d


def _frame(dbc, name, t, **values):
    cid, data, ext = dbc.encode(name, values)
    return can.Message(arbitration_id=cid, data=data, is_extended_id=ext, timestamp=t)


def test_each_message_is_recorded_at_its_own_period_and_arrival_time(tmp_path, dbc):
    """Hızlı mesaj (10 sn arayla) ve yavaş mesaj (100 sn arayla): her biri geliş anlarında, ne eksik ne fazla."""
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "periyot")
    fr = FrameRecorder(rec, lambda: dbc)
    fr.start()
    t0 = rec._t0 + 1000.0
    fast = [t0 + 10.0 * i for i in range(6)]                    # ENG_STATUS: 10 sn'de bir
    slow = [t0 + 100.0 * i for i in range(3)]                   # AIRCRAFT: 100 sn'de bir
    for t in sorted(set(fast + slow)):
        if t in fast:
            fr.submit(_frame(dbc, "ENG_STATUS", t, rpm=1000.0 + t - t0, tt2_c=20.0, tt2_fault=0))
        if t in slow:
            fr.submit(_frame(dbc, "AIRCRAFT", t, altitude=1.0 + (t - t0) / 100.0, mach=0.3, p_amb=1.0))
    fr.stop()                                                   # kuyruktaki her şey yazılır
    rec.stop()
    rows = _rows(path)
    rpm = [float(r[3]) for r in rows if r[1] == "dbc:ENG_STATUS.rpm"]
    alt = [float(r[3]) for r in rows if r[1] == "dbc:AIRCRAFT.altitude"]
    assert rpm == pytest.approx(fast, abs=0.001), "hızlı mesajın her gelişi, geliş zamanıyla yazılmalı"
    assert alt == pytest.approx(slow, abs=0.001), "yavaş mesaj 100 sn'de bir yazılmalı (ara satır YOK)"
    assert fr.dropped == 0 and fr.frames == len(fast) + len(slow)
    # mesajdaki tüm sinyaller yazılır (ekranda hiçbir yerde kullanılmasalar da); aynı değer tekrar gelse de her geliş bir satır
    assert {r[1] for r in rows} >= {"dbc:ENG_STATUS.tt2_c", "dbc:ENG_STATUS.tt2_fault", "dbc:AIRCRAFT.mach",
                                    "dbc:AIRCRAFT.p_amb"}
    assert sum(1 for r in rows if r[1] == "dbc:ENG_STATUS.tt2_c") == len(fast)


def test_frames_with_the_same_value_at_high_rate_are_all_kept(tmp_path, dbc):
    rec = SessionRecorder()
    path = rec.start(str(tmp_path), "hizli")
    fr = FrameRecorder(rec, lambda: dbc)
    fr.start()
    t0 = rec._t0 + 5.0
    for i in range(200):                                         # 10 ms'de bir, değer hiç değişmiyor
        fr.submit(_frame(dbc, "ENG_STATUS", t0 + 0.010 * i, rpm=3000.0, tt2_c=25.0, tt2_fault=0))
    fr.stop()
    rec.stop()
    rows = [r for r in _rows(path) if r[1] == "dbc:ENG_STATUS.rpm"]
    assert len(rows) == 200
    gaps = [float(b[3]) - float(a[3]) for a, b in zip(rows, rows[1:])]
    assert all(g == pytest.approx(0.010, abs=0.0006) for g in gaps)      # ms çözünürlüğüyle 10 ms aralık korunur


def test_unknown_frames_and_missing_dbc_are_ignored_and_queue_overflow_is_counted(tmp_path, dbc, monkeypatch):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "x")
    fr = FrameRecorder(rec, lambda: None)                         # DBC yok: yazılacak bir şey yok, hata da yok
    fr.start()
    fr.submit(can.Message(arbitration_id=0x7FF, data=b"\x00", is_extended_id=False, timestamp=time.time()))
    fr.stop()
    assert rec.rows == 0
    import app.session_recorder as sr
    monkeypatch.setattr(sr, "FRAME_QUEUE_MAX", 2)
    small = FrameRecorder(rec, lambda: dbc)                       # iş parçacığı başlamadan kuyruk dolar
    for i in range(5):
        small.submit(_frame(dbc, "ENG_STATUS", time.time() + i, rpm=1.0, tt2_c=1.0, tt2_fault=0))
    assert small.dropped == 3                                     # sessiz kayıp yok: düşenler sayılır
    rec.stop()


# ---------------------------------------------------------------- uçtan uca: gerçek CAN hattı
def test_can_frames_on_a_virtual_bus_reach_the_recording_without_any_ui_timer(qapp, tmp_path, monkeypatch):
    """Gerçek alım iş parçacığı + frame_tap yolu: ana pencerenin zamanlayıcıları ÇALIŞMADAN (olay döngüsü dönmeden) kayıt oluşur."""
    import app.paths as paths
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
        w._on_connect("virtual", "rec-periyot", 500_000)
        sender = can.Bus(interface="virtual", channel="rec-periyot")
        w.session_tab._on_start()
        dbc = w.transmit_tab.dbc
        for i in range(12):                                        # hızlı mesaj
            cid, data, _ = dbc.encode("ENG_STATUS", {"rpm": 100.0 + i, "tt2_c": 30.0, "tt2_fault": 0})
            sender.send(can.Message(arbitration_id=cid, data=data, is_extended_id=False))
            if i % 4 == 0:                                         # yavaş mesaj: dörtte bir sıklıkta
                cid, data, _ = dbc.encode("AIRCRAFT", {"altitude": 2.0, "mach": 0.4, "p_amb": 1.0})
                sender.send(can.Message(arbitration_id=cid, data=data, is_extended_id=False))
            time.sleep(0.02)
        time.sleep(0.3)                                            # alım iş parçacığı + kayıt iş parçacığı yetişsin
        csv_path = w.session_recorder.path
        w.session_tab._on_stop()
        rows = _rows(csv_path)
        assert sum(1 for r in rows if r[1] == "dbc:ENG_STATUS.rpm") == 12
        assert sum(1 for r in rows if r[1] == "dbc:AIRCRAFT.altitude") == 3
        times = [float(r[3]) for r in rows if r[1] == "dbc:ENG_STATUS.rpm"]
        assert times == sorted(times) and times[-1] - times[0] >= 0.15      # gerçek geliş anları (örnekleme değil)
        sender.shutdown()
    finally:
        w._on_disconnect()
        w.close()
