import time

from PySide6.QtCore import Qt

from app.session_recorder import SessionRecorder
from app.ui.session_browser import AnalysisWindow, SessionBrowser, event_color
from app import session_export as sx


def _make(tmp_path):
    rec = SessionRecorder()
    rec.start(str(tmp_path), "Oturum A", meta={"mode": "MIL", "user": "z"})
    t0 = rec._t0
    for i in range(100):
        rec.record("dbc:ENG.rpm", 1000 + i, t0 + i * 0.1)
        rec.record("cal:FuelLimit", 90 + (i > 50) * 5, t0 + i * 0.1)
    rec.record_event("KALIBRASYON", "FuelLimit 90 -> 95", t0 + 5.1)
    rec.add_marker("Idle", t0 + 2.0)
    rec.stop()
    return rec


def test_browser_lists_and_opens_analysis_with_cursor_tools(qapp, tmp_path):
    _make(tmp_path)
    b = SessionBrowser(lambda: str(tmp_path))
    b.refresh()
    assert b.table.rowCount() == 1 and b.table.item(0, 0).text() == "Oturum A" and b.table.item(0, 3).text() == "MIL"
    b.table.selectRow(0)
    b.open_selected()
    w = b._windows[0]
    assert isinstance(w, AnalysisWindow)
    tr = w.trend
    assert tr._static and not tr.is_live() and tr.btn_cursor.isChecked()
    assert set(tr._series) == {"cal:FuelLimit", "dbc:ENG.rpm"}
    kinds = [e[1] for e in tr.events]
    assert any(k.startswith("MARKER") for k in kinds) and any(k.startswith("KALIBRASYON") for k in kinds)
    tr._cur_a.setPos(w.sd.meta["start_unix"] + 1.0)
    tr._cur_b.setPos(w.sd.meta["start_unix"] + 3.05)
    tr._update_cursor_readout()
    from app.ui import trend_signal_table as st
    assert tr.signal_table.item_text("dbc:ENG.rpm", st.C_DY) == "+20.5"
    assert tr.signal_table.item_text("dbc:ENG.rpm", st.C_MAX) == "1030"
    w.close()


def test_browser_export_all_formats(qapp, tmp_path):
    _make(tmp_path)
    b = SessionBrowser(lambda: str(tmp_path))
    b.refresh()
    b.table.selectRow(0)
    msgs = []
    b.status.connect(msgs.append)
    for fmt in ("mf4", "csv", "mat"):
        out = tmp_path / f"o.{fmt}"
        assert b.export_selected(fmt, str(out)) == str(out) and out.stat().st_size > 0
    assert any("DOĞRULANMADI" in m for m in msgs)


def test_event_colors():
    assert event_color("KALIBRASYON") and event_color("BAGLANTI_KOPTU") and event_color("BILGI_X") is None
