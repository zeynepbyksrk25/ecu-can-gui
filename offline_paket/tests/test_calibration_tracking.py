"""Kalibrasyon değişiklik takibi: ok/miktar göstergesi, geçmiş, geri alma ve başlangıca dönüş (Aşama 1)."""
import json


from app.a2l import AxisInfo, CharacteristicInfo
from app.history import CalibrationHistory


def _map():
    xs, ys = [1.0, 2.0, 3.0], [10.0, 20.0]
    return CharacteristicInfo("M", "", "MAP", 0x1000, "%", "UWORD", 0, 100, False, 2,
                              axes=[AxisInfo(3, "", "FIX_AXIS", xs), AxisInfo(2, "rpm", "FIX_AXIS", ys)])


def _doc(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    tab = MapEditorTab()
    doc = tab.open_characteristic(_map())
    doc.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    doc._confirm = lambda *_a: True          # onay diyaloğu testte otomatik "Evet"
    return doc


def test_edited_cell_shows_arrow_and_delta_but_not_applied(qapp):
    doc = _doc(qapp)
    doc.table.item(0, 1).setText("2.5")                      # artış
    doc.table.item(1, 0).setText("1")                        # azalış
    up, down = doc.table.item(0, 1), doc.table.item(1, 0)
    assert not up.icon().isNull() and not down.icon().isNull()
    assert "↑ +0.5" in up.toolTip() and "HENÜZ yazılmadı" in up.toolTip()
    assert "↓ -3" in down.toolTip()
    assert doc.table.item(0, 0).icon().isNull()              # değişmeyen hücrede ok yok
    assert doc._applied == {}                                # yazılmadan uygulanmış sayılmaz


def test_write_result_marks_applied_and_new_base(qapp):
    doc = _doc(qapp)
    doc.table.item(0, 1).setText("9")
    doc.set_write_result(True, "ok")
    assert doc._applied[(0, 1)][:2] == (2, 9.0)
    assert "ECU'ya yazıldı" in doc.table.item(0, 1).toolTip()
    assert not doc.table.item(0, 1).icon().isNull()
    assert not doc.is_modified()
    doc.set_write_result(False, "hata")                      # başarısız yazma uygulanmış göstermez
    assert doc._applied[(0, 1)][:2] == (2, 9.0)


def test_discard_edits_returns_to_ecu_values(qapp):
    doc = _doc(qapp)
    doc.table.item(0, 1).setText("50")
    doc.table.item(1, 2).setText("60")
    assert doc.discard_edits() == 2
    assert doc.current_grid() == [[1, 2, 3], [4, 5, 6]] and not doc.is_modified()
    assert doc.discard_edits() == 0


def test_discard_edits_declined_keeps_edits(qapp):
    doc = _doc(qapp)
    doc.table.item(0, 1).setText("50")
    doc._confirm = lambda *_a: False
    assert doc.discard_edits() == 0
    assert doc.current_grid()[0][1] == 50


def test_revert_to_session_baseline_cell_and_map(qapp):
    doc = _doc(qapp)
    doc.table.item(0, 1).setText("7")
    doc.set_write_result(True, "ok")                         # ECU artık 7; başlangıç (oturum başı) hâlâ 2
    doc.table.item(1, 1).setText("8")
    doc.table.clearSelection()
    doc.table.item(0, 1).setSelected(True)
    assert doc.revert_selection_to_baseline() == 1
    assert doc.current_grid()[0][1] == 2
    assert doc.current_grid()[1][1] == 8                     # seçilmeyen hücreye dokunulmadı
    assert doc.is_modified()                                 # ECU'ya yazılmadı: hâlâ düzenleme
    assert doc.revert_all_to_baseline() == 1                 # kalan: (1,1) 8 -> 5
    assert doc.current_grid() == [[1, 2, 3], [4, 5, 6]]
    assert doc.revert_all_to_baseline() == 0                 # zaten başlangıçta


def test_baseline_unavailable_before_first_read(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    doc = MapEditorTab().open_characteristic(_map())
    doc._confirm = lambda *_a: True
    assert doc.revert_all_to_baseline() == 0
    assert "oturum başı" in doc.baseline_reference_text()


def test_history_delta_status_and_filtering(tmp_path):
    h = CalibrationHistory(file_path=str(tmp_path / "h.json"))
    h.add("u", "Mühendis", "Kp", 1.2, 1.35, "", source="watch")
    h.add("u", "Mühendis", "Ki", 0.8, 0.65, "", write_ok=False, source="watch")
    h.add("u", "Mühendis", "Kp", 1.35, 1.5, "", source="ccp")
    assert abs(h.entries[0].delta - 0.15) < 1e-9
    assert h.entries[1].write_ok is False
    assert [e.new_value for e in h.for_object("Kp")] == [1.35, 1.5]
    assert h.last_applied("Ki") is None                     # başarısız yazma "uygulanmış" sayılmaz
    assert h.last_applied("Kp").new_value == 1.5
    h2 = CalibrationHistory(file_path=str(tmp_path / "h.json"))   # diskten geri okunur
    assert [e.write_ok for e in h2.entries] == [True, False, True]


def test_history_loads_legacy_file_without_new_fields(tmp_path):
    p = tmp_path / "old.json"
    p.write_text(json.dumps([{"timestamp": 1.0, "user": "a", "role": "r", "object_name": "X",
                              "old_value": 1.0, "new_value": 2.0, "unit": "V", "persistent": False}]),
                 encoding="utf-8")
    h = CalibrationHistory(file_path=str(p))
    assert len(h.entries) == 1 and h.entries[0].write_ok is True and h.entries[0].delta == 1.0


def test_history_tab_columns_filter_and_revert_guard(qapp, tmp_path):
    from app.ui.history_tab import HistoryTab
    h = CalibrationHistory()
    h.add("u", "r", "Kp", 1.2, 1.35, "", source="watch")
    h.add("u", "r", "Ki", 0.8, 0.65, "", write_ok=False)
    tab = HistoryTab()
    tab.history = h
    got = []
    tab.revert_requested.connect(got.append)
    tab.refresh()
    assert tab.table.rowCount() == 2
    assert tab.table.item(0, 7).text() == "↑ +0.15"
    assert "BAŞARISIZ" in tab.table.item(1, 8).text()
    tab.table.selectRow(1)
    tab._on_revert()
    assert got == []                                        # başarısız yazma geri alınmaz
    tab.filter_combo.setCurrentIndex(tab.filter_combo.findData("Kp"))
    assert tab.table.rowCount() == 1
    tab.table.selectRow(0)
    tab._on_revert()
    assert got == [0]


def test_watch_tab_delta_column_pending_then_applied(qapp):
    from app.ui.watch_tab import COL_DELTA, WatchEntry, WatchTab
    tab = WatchTab()
    e = WatchEntry("Kp_Governor", "characteristic", 0x100, "FLOAT32_IEEE", unit="", read_only=False)
    tab.add_manual_entry(e)
    tab.set_row_value(0, b"\x00\x00\x00\x00", 1.2)
    assert tab.table.item(0, COL_DELTA).text() == ""
    tab.tracker.edit("Kp_Governor", 1.35)
    tab._render_row(0)
    assert "yazılmadı" in tab.table.item(0, COL_DELTA).text()
    tab.commit_written(0, 1.35, old=1.2)
    assert tab.table.item(0, COL_DELTA).text() == "↑ +0.15"
    assert tab.blink_timer.isActive()
    tab.mark_write_failed(0, "x")
    assert tab.tracker.state("Kp_Governor").last_write_ok is False


def test_watch_revert_selected_to_baseline_confirms_and_requests_write(qapp):
    from app.ui.watch_tab import WatchEntry, WatchTab
    tab = WatchTab()
    for n in ("A", "B", "RO"):
        tab.add_manual_entry(WatchEntry(n, "characteristic", 0x100, "FLOAT32_IEEE", read_only=(n == "RO")))
    for i, v in enumerate((10.0, 20.0, 5.0)):
        tab.set_row_value(i, b"\0\0\0\0", v)                  # başlangıç referansı = ilk okuma
    tab.commit_written(0, 12.5, old=10.0)                     # A: 10 -> 12.5 uygulandı
    got = []
    tab.write_requested.connect(got.append)
    tab._confirm = lambda *_a: False
    assert tab.revert_selected_to_baseline() == 0 and got == []        # onay reddedildi: yazma yok
    tab._confirm = lambda *_a: True
    tab.table.selectAll()
    n = tab.revert_selected_to_baseline()
    assert n == 1 and got == [[0]]                                      # yalnızca değişmiş, yazılabilir satır (A)
    assert tab._entries[0].pending_text == "10"
    tab.set_row_value(1, b"\0\0\0\0", 20.0)
    assert tab.revert_selected_to_baseline() == 0                       # B zaten başlangıçta
