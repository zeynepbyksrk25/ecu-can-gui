"""Durum çubuğu alanları ve bekleyen değişiklik şeridi."""
import os

import pytest

from app.ui.mainwin.status import format_elapsed

DATA = os.path.join(os.path.dirname(__file__), "data")


def test_format_elapsed():
    assert format_elapsed(0) == "00:00:00" and format_elapsed(75.9) == "00:01:15" and format_elapsed(3661) == "01:01:01"


@pytest.fixture
def win(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
    w.modas_tab.set_summary(w.a2l_tab.db.summary)
    yield w
    w.close()


def test_status_bar_fields_show_ecu_measurement_recording_bus_workbase_and_pending(win):
    win._refresh_status_widgets()
    t = {k: v.text() for k, v in win.status_labels.items()}
    assert "ÇEVRİMDIŞI" in t["ecu"] and "KAPALI" in t["measure"] and t["rec"] == "Kayıt yok"
    assert t["bus"] == "Bus yükü: —" and t["workbase"] == "Çalışma tabanı: —" and ">0<" in t["pending"]
    win.modas_tab.start_measurement()                      # ölçüm açık gösterilir
    win._refresh_status_widgets()
    assert "AÇIK" in win.status_labels["measure"].text()
    win.modas_tab.stop_measurement()


def test_recording_shows_elapsed_time_in_status_bar(win, tmp_path):
    win.session_recorder.start(str(tmp_path), "durum")
    try:
        win._refresh_status_widgets()
        assert "KAYIT 00:00:0" in win.status_labels["rec"].text()
        win.session_recorder.pause()
        win._refresh_status_widgets()
        assert "DURAKLATILDI" in win.status_labels["rec"].text()
    finally:
        win.session_recorder.stop()


def test_pending_bar_appears_for_unwritten_edits_and_revert_discards_without_writing(win):
    win.show()
    obj = win.modas_tab.object_by_name("clbc_Fuel_pump_gain")
    vw = win.modas_tab.add_label(obj)
    win._refresh_status_widgets()
    assert not win.pending_bar.isVisible() and win.pending_counts() == (0, 0)
    from tests.test_modas import _reading
    vw.set_reading(_reading(10.0))
    vw.set_allowed(True)                                    # çevrimdışıyken kutu salt okunur; yazmaya açık varsay
    vw.edit.setText("42")
    vw._on_text_edited("42")                                # kullanıcı yazdı, Enter yok: bekleyen
    from app.ui.modas.windows import TableWindow
    from tests.test_modas import make_map
    tw = TableWindow(make_map(rows=2, cols=3))
    win.modas_tab.table_windows = lambda: [tw]
    tw.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    tw.table.item(0, 0).setText("9")
    assert win.pending_counts() == (1, 1)
    win._refresh_status_widgets()
    assert win.pending_bar.isVisible() and "1 değer" in win.pending_text.text() and "1 tablo" in win.pending_text.text()
    assert ">2<" in win.status_labels["pending"].text()
    assert not win.pending_write_button.isEnabled()          # ECU çevrimdışı: yazma kapalı, neden gösterilir
    win.pending_revert_button.click()
    assert win.pending_counts() == (0, 0) and not win.pending_bar.isVisible()
    assert tw.current_grid() == [[1, 2, 3], [4, 5, 6]]       # tablo ECU değerine döndü
    assert vw.edit.text() == "10"                            # değer kutusu ECU değerine döndü


def test_new_windows_are_placed_in_free_space_without_overlapping(qapp, tmp_path):
    from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace
    from app.a2l import A2LDatabase
    db = A2LDatabase()
    db.load(os.path.join(DATA, "sample.a2l"))
    w = ModasWorkspace(ModasSheetStore(str(tmp_path / "s.json")))
    w.set_summary(db.summary)
    w.resize(1500, 900)
    w.show()
    qapp.processEvents()
    try:
        scopes = [w.add_label(n) for n in ("clbc_Fuel_pump_gain", "Tt2_raw", "clbc_Fuel_pump_dc_perc")]
        rects = [s.geometry() for s in scopes]
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                assert not a.intersects(b), (a, b)                  # üst üste binmez
        area = w.current_sheet().mdi.viewport().rect()
        assert all(area.contains(r) for r in rects)                 # alanın dışına taşmaz
        assert rects[0].topLeft().x() <= 30 and rects[0].topLeft().y() <= 30   # ilk pencere sol üstte
    finally:
        w.shutdown()


def test_placement_falls_back_to_cascade_when_the_area_is_full(qapp, tmp_path):
    from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace
    w = ModasWorkspace(ModasSheetStore(str(tmp_path / "s.json")))
    w.resize(700, 500)
    w.show()
    qapp.processEvents()
    try:
        wins = [w.add_scope([]) for _ in range(4)]                  # 640x420 pencereler 700x500'e sığmaz: kademeli
        assert len({(x.pos().x(), x.pos().y()) for x in wins}) >= 3
    finally:
        w.shutdown()
