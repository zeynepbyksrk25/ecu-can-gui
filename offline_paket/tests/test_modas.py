"""Modas Sport tarzı arayüz: Ribbon, çalışma alanı (worksheet / MDI / Variable list), WP/RP ve uçtan uca (CCP simülatörü)."""
import itertools
import os
import struct
import time

import can
import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from app.a2l import A2LDatabase, AxisInfo, CharacteristicInfo
from app.ccp import worker as cw
from app.ccp.simulator import CCPSlaveSimulator
from app.ccp.worker import ONLINE
from app.ui.modas import pages
from app.ui.modas.variable_list import VariableListPanel, classify, passes_filter
from app.ui.modas.windows import TableWindow, ValueWindow, format_phys, format_reading
from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace
from app.modas_projects import Workbase
from PySide6.QtWidgets import QAbstractItemView

DATA = os.path.join(os.path.dirname(__file__), "data")
_ch = itertools.count()


@pytest.fixture(scope="module")
def summary():
    return A2LDatabase().load(os.path.join(DATA, "sample.a2l"))


def make_map(name="MAP1", rows=2, cols=3, addr=0x2000):
    return CharacteristicInfo(
        name=name, description="deneme haritası", kind="MAP", address=addr, unit="ms", datatype="UWORD",
        minimum=0, maximum=60000, read_only=False, num_axes=2, byte_order="MSB_FIRST", char_type="MAP",
        axes=[AxisInfo(cols, "V", "FIX_AXIS", [10, 20, 30][:cols]), AxisInfo(rows, "rpm", "FIX_AXIS", [1000, 2000][:rows])],
        index_mode="ROW_DIR")


# ------------------------------------------------------------------ saf mantık
def test_format_phys_is_compact_and_safe():
    assert format_phys(12000.0) == "12000" and format_phys(0.5) == "0.5" and format_phys(0) == "0"
    assert format_phys(None) == "" and format_phys(float("inf")) == "inf"
    assert format_phys(1e-7) == "1e-07"


def test_page_model_diff_copy_and_restore():
    m = pages.PageModel()
    assert m.active == pages.WP and not m.has_reference()
    assert m.copy_wp_to_rp({"a": 1.0, "t": [[1.0, 2.0]], "n": None}) == 2
    assert m.diff_count({"a": 1.0, "t": [[1.0, 2.0]]}) == 0
    wp = {"a": 1.5, "t": [[1.0, 9.0]], "other": 3.0}                     # 'other' RP'de yok: fark sayılmaz
    assert m.diff_names(wp) == ["a", "t"] and m.diff_count(wp) == 2
    assert m.restore_plan(wp) == {"a": 1.0, "t": [[1.0, 2.0]]}
    assert m.adopt_missing(wp) == 1 and m.reference["other"] == 3.0 and m.reference["a"] == 1.0
    assert m.toggle() == pages.RP and m.toggle() == pages.WP
    m.clear()
    assert not m.has_reference()


def test_page_model_tolerates_float_noise():
    m = pages.PageModel()
    m.copy_wp_to_rp({"a": 0.1 + 0.2})
    assert m.diff_count({"a": 0.3}) == 0


def test_variable_list_classification_and_filters(summary, qapp):
    kinds = [classify(o) for o in list(summary.measurements) + list(summary.characteristics)]
    assert kinds.count("meas") == len(summary.measurements) and kinds.count("value") == 2
    assert classify(make_map()) == "map"
    assert passes_filter("meas", "") and passes_filter("map", "char") and not passes_filter("meas", "char")
    assert passes_filter("value", "value") and not passes_filter("value", "curve")

    panel = VariableListPanel()
    panel.set_summary(summary)
    total = len(panel.visible_names())
    assert total == len(summary.measurements) + len(summary.characteristics)
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData("meas"))
    assert len(panel.visible_names()) == len(summary.measurements)
    panel.filter_combo.setCurrentIndex(panel.filter_combo.findData("value"))
    assert sorted(panel.visible_names()) == ["clbc_Fuel_pump_gain", "clbc_Temp_limit"]
    panel.filter_combo.setCurrentIndex(0)
    panel.search.setText("TEMP")
    assert all("temp" in n.lower() or "temp" in (panel.object_at(i).description or "").lower()
               for i, n in enumerate([o.name for o in panel._objects]) if n in panel.visible_names())
    added = []
    panel.add_requested.connect(added.append)
    panel._add_row(0)
    assert added and added[0] is panel.object_at(0)


def test_variable_list_drag_mime_carries_label_names(summary, qapp):
    from app.ui.modas.variable_list import MIME
    panel = VariableListPanel()
    panel.set_summary(summary)
    panel.table.selectRow(0)
    mime = panel.table.mimeData(panel.table.selectedItems())
    assert bytes(mime.data(MIME)).decode() == panel.table.item(0, 0).text()


# ------------------------------------------------------------------ pencereler
def test_value_window_calibration_is_white_editable_and_measurement_is_grey_readonly(summary, qapp):
    cal = next(c for c in summary.characteristics if c.name == "clbc_Temp_limit")
    meas = summary.measurements[0]
    wc, wm = ValueWindow(cal), ValueWindow(meas)
    assert wc.is_calibration and not wc.edit.isReadOnly() and wc.edit.property("kind") == "cal"
    assert not wm.is_calibration and wm.edit.isReadOnly() and wm.edit.property("kind") == "meas"
    wc.set_allowed(False)
    assert wc.edit.isReadOnly()                                    # rol izni yoksa salt okunur
    wc.set_allowed(True)
    assert not wc.edit.isReadOnly()


def _reading(phys, raw_bytes=b"\x00\x0a"):
    from app.ccp.codec import Reading
    return Reading(raw_bytes, phys, phys)


def test_value_window_pending_enter_escape_and_live_updates(summary, qapp):
    cal = next(c for c in summary.characteristics if c.name == "clbc_Temp_limit")
    w = ValueWindow(cal)
    got = []
    w.write_requested.connect(lambda win, text: got.append(text))
    w.set_reading(_reading(10.0))
    assert w.edit.text() == "10"
    w.edit.selectAll()
    QTest.keyClicks(w.edit, "25")                                   # yazmaya başlayınca bekleyen (sarı)
    assert w.has_pending and w.edit.property("pending") is True
    w.set_reading(_reading(11.0))                                   # canlı değer yazılan metni ezmez
    assert w.edit.text().endswith("25")
    QTest.keyClick(w.edit, Qt.Key_Escape)                           # Esc vazgeçer, canlı değer döner
    assert not w.has_pending and w.edit.text() == "11"
    w.edit.setText("30")
    w.edit.setModified(True)
    w._on_text_edited("30")
    QTest.keyClick(w.edit, Qt.Key_Return)
    assert got == ["30"]
    w.set_write_result(False, "hata")
    assert not w.has_pending and w.edit.property("bad") is True
    w.set_write_result(True, "ok")
    assert w.edit.property("bad") is False


def test_value_window_m_n_nudge_and_formats(summary, qapp):
    cal = next(c for c in summary.characteristics if c.name == "clbc_Temp_limit")
    w = ValueWindow(cal)
    got = []
    w.write_requested.connect(lambda win, text: got.append(text))
    little = (cal.byte_order or "").upper() in ("MSB_LAST", "LITTLE_ENDIAN")
    w.set_reading(_reading(10.0, b"\x0a\x00" if little else b"\x00\x0a"))     # ham bayt A2L bayt sırasına uyar
    QTest.keyClick(w.edit, Qt.Key_M)
    QTest.keyClick(w.edit, Qt.Key_N)
    assert got == ["11", "9"]
    w.set_format("hex")
    assert w.edit.text() == "0x000A" and w.edit.isReadOnly()        # biçim ≠ physical: yazma kapalı
    w.set_format("bin")
    assert w.edit.text() == "0000000000001010"
    w.set_format("dec")
    assert w.edit.text() == "10"
    w.set_format("phys")
    assert not w.edit.isReadOnly()
    assert format_reading(_reading(10.0), "hex", "MSB_LAST") == "0x0A00"


def test_value_window_rp_view_shows_reference_readonly_and_restores(summary, qapp):
    cal = next(c for c in summary.characteristics if c.name == "clbc_Temp_limit")
    w = ValueWindow(cal)
    w.set_reading(_reading(10.0))
    w.set_reference_view(7.5, rp=True)
    assert w.edit.text() == "7.5" and w.edit.isReadOnly()
    w.set_reading(_reading(12.0))                                   # RP gösteriminde canlı değer arka planda akar
    assert w.edit.text() == "7.5" and w.wp_value() == 12.0
    w.set_reference_view(None, rp=False)
    assert w.edit.text() == "12" and not w.edit.isReadOnly()


def test_table_window_headers_ops_and_write_signal(qapp):
    w = TableWindow(make_map())
    assert (w.rows, w.cols) == (2, 3)
    assert [w.table.horizontalHeaderItem(c).text() for c in range(3)] == ["10", "20", "30"]
    assert [w.table.verticalHeaderItem(r).text() for r in range(2)] == ["1000", "2000"]
    assert not w.is_writable()                                      # henüz ECU'dan okunmadı: boş hücreler
    w.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    assert w.is_writable() and not w.is_modified()
    writes = []
    w.write_requested.connect(writes.append)
    w.table.item(0, 0).setText("9")                                 # hücre onayı → RAM yazma isteği
    assert writes == [w] and w.is_modified() and w.current_grid()[0][0] == 9
    w.table.clearSelection()
    w.table.item(1, 0).setSelected(True)
    w.table.item(1, 1).setSelected(True)
    assert w.apply_to_selection("mul", 2.0) == 2
    assert w.current_grid()[1][:2] == [8, 10]
    assert w.apply_to_selection("div", 0.0) == 0                    # sıfıra bölme atlanır
    w.set_write_result(True, "ok")
    assert not w.is_modified()


def test_table_window_ctrl_r_restores_selection_and_corner_label(qapp):
    from PySide6.QtWidgets import QAbstractButton
    w = TableWindow(make_map())
    assert w.table.findChild(QAbstractButton).text() == "Y\\X"        # Modas: sol üst köşe 'Y\X'
    w.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    w.table.item(0, 0).setText("9")
    w.table.item(1, 2).setText("8")
    w.table.clearSelection()
    w.table.item(0, 0).setSelected(True)                            # yalnız (0,0) seçili
    assert w.restore_selection() == 1                               # PDF §8: Ctrl+R
    assert w.current_grid() == [[1, 2, 3], [4, 5, 8]]               # seçili olmayan değişiklik korunur


def test_table_window_blocks_unverified_layouts_and_rp_view(qapp):
    bad = make_map()
    bad.axes[0].attribute = "STD_AXIS"
    w = TableWindow(bad)
    w.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    assert not w.writable_layout and not w.is_writable() and not w.is_cell_editable()
    ok = TableWindow(make_map())
    ok.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    ok.set_reference_view([[0, 0, 0], [0, 0, 0]], rp=True)
    assert ok.table.item(0, 0).text() == "0" and not ok.is_cell_editable()
    assert ok.current_grid() == [[1, 2, 3], [4, 5, 6]]              # yazılacak olan her zaman WP
    ok.set_grid_from_ecu([[7, 7, 7], [7, 7, 7]])                    # RP gösteriminde yeni WP arka planda saklanır
    assert ok.table.item(0, 0).text() == "0" and ok.wp_grid()[0][0] == 7
    ok.set_reference_view(None, rp=False)
    assert ok.table.item(0, 0).text() == "7" and ok.is_cell_editable()


# ------------------------------------------------------------------ çalışma alanı
def test_workspace_sheets_add_close_persist_and_late_a2l(summary, qapp, tmp_path):
    path = str(tmp_path / "ws.json")
    ws = ModasWorkspace(ModasSheetStore(path))
    assert ws.sheet_names() == ["Sayfa1"]
    ws.set_summary(summary)
    cal = ws.add_label("clbc_Temp_limit")
    meas = ws.add_label("N_RPM")
    assert isinstance(cal, ValueWindow) and cal.is_calibration and not meas.is_calibration
    assert ws.add_label("N_RPM") is meas and len(ws.windows()) == 2     # çift eklenmez, öne gelir
    assert ws.add_label("yok_boyle_bir_label") is None
    ws.new_sheet("Engine Setup")
    assert ws.sheet_names() == ["Sayfa1", "Engine Setup"] and ws.current_sheet().name == "Engine Setup"
    ws.add_label("FP_bar")
    assert ws.rename_sheet(1, "Calib") and not ws.rename_sheet(1, "Sayfa1")   # ad çakışması reddedilir
    cal.edit.setText("x")
    ws.save()

    # A2L'siz yeniden açılış: pencereler kaybolmaz, bekler; A2L gelince kurulur
    ws2 = ModasWorkspace(ModasSheetStore(path))
    assert ws2.sheet_names() == ["Sayfa1", "Calib"] and ws2.windows() == []
    ws2.set_summary(summary)
    assert sorted(w.label for w in ws2.windows()) == ["FP_bar", "N_RPM", "clbc_Temp_limit"]
    assert ws2.current_sheet().name == "Calib"
    ws2.save()
    ws2.set_summary(None)                                           # A2L boşalınca etiketler korunur (bekleyen)
    assert ws2.windows() == [] and len(ws2.to_state()["sheets"][0]["windows"]) == 2
    assert not ws2.delete_sheet(5)
    assert ws2.delete_sheet(1) and ws2.sheet_names() == ["Sayfa1"] and not ws2.delete_sheet(0)


def test_workspace_drop_adds_labels_and_format_applies_to_selection(summary, qapp, tmp_path):
    ws = ModasWorkspace(ModasSheetStore(str(tmp_path / "ws.json")))
    ws.set_summary(summary)
    ws._on_dropped(["N_RPM", "clbc_Temp_limit"], QPoint(40, 40))
    assert {w.label for w in ws.windows()} == {"N_RPM", "clbc_Temp_limit"}
    ws.current_sheet().mdi.setActiveSubWindow(ws.find_window("N_RPM"))
    assert ws.set_format("hex") == 1 and ws.find_window("N_RPM").fmt == "hex"
    assert ws.find_window("clbc_Temp_limit").fmt == "phys"
    assert ws.set_format("phys") == 1
    ws.remove_selected()
    assert ws.find_window("N_RPM") is None


def test_workspace_wp_snapshot_and_page_views(summary, qapp, tmp_path):
    ws = ModasWorkspace(ModasSheetStore(str(tmp_path / "ws.json")))
    ws.set_summary(summary)
    cal = ws.add_label("clbc_Temp_limit")
    meas = ws.add_label("N_RPM")
    cal.set_reading(_reading(10.0))
    meas.set_reading(_reading(1500.0))
    assert ws.wp_snapshot() == {"clbc_Temp_limit": 10.0}              # yalnızca kalibrasyon etiketleri RP'ye girer
    ws.set_reference({"clbc_Temp_limit": 4.0})
    ws.set_page(pages.RP)
    assert cal.edit.text() == "4" and cal.edit.isReadOnly() and ws.page == pages.RP
    ws.set_page(pages.WP)
    assert cal.edit.text() == "10"


def test_workspace_measurement_timer_and_offline_guard(summary, qapp, tmp_path):
    ws = ModasWorkspace(ModasSheetStore(str(tmp_path / "ws.json")))
    states = []
    ws.measuring_changed.connect(states.append)
    assert not ws.is_measuring and ws.toggle_measurement() is True and ws.is_measuring
    ws.set_online(False)                                              # bağlantı kopunca ölçüm durur
    assert not ws.is_measuring and states == [True, False]


# ------------------------------------------------------------------ MainWindow + simülatör
@pytest.fixture
def live(qapp, monkeypatch):
    from app.ui.main_window import MainWindow
    monkeypatch.setattr(cw, "SHORT_TIMEOUT_S", 0.08)
    monkeypatch.setattr(cw, "LOST_PROBE_S", 0.15)
    monkeypatch.setattr(cw, "BACKOFF", (0.05, 0.1, 0.2))
    w = MainWindow()
    w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
    w._on_dashboard_sources_changed()
    w.a2l_tab.a2l_loaded.emit()
    channel = f"modas-{next(_ch)}"
    w._on_connect("virtual", channel, 500_000)
    bus = can.Bus(interface="virtual", channel=channel)
    ecu = CCPSlaveSimulator(bus, 0x6F9, 0x6F8)
    ecu.strict_session = True
    ecu.start()
    summary = w.a2l_tab.db.summary
    obj = next(c for c in summary.characteristics if c.name == "clbc_Fuel_pump_gain")
    ecu.write_memory_bytes(obj.address, struct.pack("<f", 12.5))

    def pump():
        qapp.processEvents()
        w._on_ccp_events()

    yield w, ecu, obj, pump
    w._on_disconnect()
    ecu.stop()
    bus.shutdown()
    w.close()


def wait_for(cond, pump, timeout=6.0):
    end = time.time() + timeout
    while time.time() < end:
        pump()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_chrome_is_a_ribbon_with_modas_tabs_and_estop_always_visible(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.show()
    qapp.processEvents()
    rb = w.modas_ribbon
    assert [rb.tabs.tabText(i) for i in range(rb.tabs.count())] == ["Başlat", "Etiket", "Çalışma Sayfaları", "Araçlar", "Pencereler"]
    assert w.centralWidget().layout().itemAt(2).widget() is w.modas_tab    # tek ana pencere: sayfa yığını yok
    dt = w.dashboard_tab
    for tg in (dt.start_toggle, dt.stop_toggle, dt.estop_toggle):
        assert rb.motor_group.isAncestorOf(tg)
    for i in range(rb.tabs.count()):                                    # hiçbir sekmede Acil Durdurma gizlenmez
        rb.select_tab(i)
        qapp.processEvents()
        assert dt.estop_toggle.isVisible()
    assert rb.buttons["ecu"].text() == "ÇEVRİMDIŞI"
    for key in ("measure", "read_ecu", "write_ecu", "copy_rp_wp"):
        assert not rb.buttons[key].isEnabled()                         # çevrimdışıyken Modas gibi pasif
    w.close()


def test_tools_tab_opens_tool_windows_and_keeps_old_pages_reachable(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    assert [l for _i, l, _p in w._nav_pages] == ["Çalışma Sayfaları", "Test Tezgâhı", "CAN İzleme", "Kalibrasyon Araçları",
                                                  "Kontrol Paneli", "Tanılama"]
    rb = w.modas_ribbon
    rb.buttons["page_3"].click()
    win = w._tool_windows[w.kalibrasyon_tab]
    assert win.isVisible() and w.kalibrasyon_tab.window() is win and win is not w
    w._open_connection_page()
    assert w._tool_windows[w.can_monitor_tab].isVisible()
    win.close()                                                        # kapatma gizler, sayfa arka planda canlı kalır
    assert not win.isVisible() and w.kalibrasyon_tab.window() is win
    w.close()


def test_function_key_shortcuts_exist(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    keys = {sc.key().toString() for sc in w._modas_shortcuts}
    assert {"F2", "F3", "F5", "F7", "F8", "F9", "Ctrl+F9", "F10", "F12", "Ctrl+P", "Ctrl+D", "Ctrl+H", "Ctrl+B",
            "Ctrl+F", "Ctrl+I"} <= keys
    w.modas_ribbon.toggle_key_tips()
    assert "[B]" in w.modas_ribbon.tabs.tabText(0) and w.modas_ribbon.key_tips_visible
    w.modas_ribbon.toggle_key_tips()
    assert w.modas_ribbon.tabs.tabText(0) == "Başlat"
    w._modas_toggle_vars()
    assert w.modas_tab.var_panel.isHidden() and not w.modas_ribbon.buttons["toggle_vars"].isChecked()
    w._modas_toggle_vars()
    assert not w.modas_tab.var_panel.isHidden()
    w.close()


def test_a2l_fills_variable_list_and_project_fields(live):
    w, ecu, obj, pump = live
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    assert w.modas_tab.var_panel.visible_names()
    rb = w.modas_ribbon
    assert wait_for(lambda: rb.buttons["ecu"].text() == "ÇEVRİMİÇİ", pump)
    assert rb.fields["a2l"].text() == "sample.a2l" and rb.fields["project"].text() not in ("", "—")
    assert rb.buttons["measure"].isEnabled() and rb.buttons["read_ecu"].isEnabled()


def test_end_to_end_values_write_wp_rp_diff_and_copy(live):
    w, ecu, obj, pump = live
    tab, rb = w.modas_tab, w.modas_ribbon
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    win = tab.add_label(obj)
    assert isinstance(win, ValueWindow) and win.is_calibration
    # ölçüm kapalıyken de ilk okuma gelir; Start ile değer akar
    rb.buttons["measure"].click()
    assert tab.is_measuring and rb.buttons["measure"].text() == "Durdur"
    assert wait_for(lambda: win.edit.text() == "12.5", pump)
    assert rb.diff_label.text() == "Fark: 0"
    # ECU tarafında değişen değer ekrana kendiliğinden yansır
    ecu.write_memory_bytes(obj.address, struct.pack("<f", 20.0))
    assert wait_for(lambda: win.edit.text() == "20", pump)
    # değer kutusuna yaz + Enter → RAM'e yazılır, ECU'dan doğrulanır
    win.edit.selectAll()
    QTest.keyClicks(win.edit, "33.5")
    QTest.keyClick(win.edit, Qt.Key_Return)
    assert struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(33.5)
    assert wait_for(lambda: win.edit.text() == "33.5" and not win.has_pending, pump)
    # RP, ilk okunan değerdi (12.5): Diff 1 ve WP/RP düğmeleri uyarı rengi
    assert wait_for(lambda: rb.diff_label.text() == "Fark: 1", pump)
    assert rb.buttons["wp"].property("alert") is True
    # F8: RP görünümü referansı gösterir ve salt okunurdur
    w._modas_toggle_page()
    assert tab.page == pages.RP and rb.buttons["rp"].isChecked() and win.edit.isReadOnly()
    assert win.edit.text() == "12.5"
    w._modas_toggle_page()
    assert win.edit.text() == "33.5" and not win.edit.isReadOnly()
    # COPY WP → RP: referans güncellenir, fark kalmaz
    rb.buttons["copy_wp_rp"].click()
    assert rb.diff_label.text() == "Fark: 0" and w.page_model.reference[obj.name] == pytest.approx(33.5)
    # değeri tekrar değiştir, sonra RP → WP ile geri al (onay kutusu otomatik "Evet")
    win.edit.selectAll()
    QTest.keyClicks(win.edit, "5")
    QTest.keyClick(win.edit, Qt.Key_Return)
    assert wait_for(lambda: rb.diff_label.text() == "Fark: 1", pump)
    from PySide6.QtWidgets import QMessageBox
    import app.ui.mainwin.modas as mm
    mm.QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
    rb.buttons["copy_rp_wp"].click()
    assert struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(33.5)
    assert wait_for(lambda: rb.diff_label.text() == "Fark: 0", pump)
    rb.buttons["measure"].click()
    assert not tab.is_measuring
    log_text = "\n".join(tab.log_panel.texts())
    assert "KALIBRASYON" in log_text and "clbc_Fuel_pump_gain" in log_text      # F3 Log penceresi olayları gösterir


def test_table_label_reads_and_writes_through_the_safe_map_path(live):
    w, ecu, obj, pump = live
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    ch = make_map(addr=0x3000)
    ecu.write_memory_bytes(ch.address, b"".join(struct.pack(">H", v) for v in (1, 2, 3, 4, 5, 6)))
    tw = w.modas_tab.add_label(ch)
    assert isinstance(tw, TableWindow)
    assert wait_for(lambda: tw.current_grid() == [[1, 2, 3], [4, 5, 6]], pump)
    tw.table.item(0, 1).setText("99")                                   # hücre onayı → yedek + yaz + geri oku
    assert wait_for(lambda: struct.unpack(">H", ecu.read_memory_bytes(ch.address + 2, 2))[0] == 99, pump)
    assert not tw.is_modified()
    assert w.page_model.reference[ch.name] == [[1, 2, 3], [4, 5, 6]]    # RP, ilk okunan tablo
    assert w.modas_ribbon.diff_label.text() == "Fark: 1"
    assert any("Tablo yazıldı" in t for t in w.modas_tab.log_panel.texts())


def test_record_button_follows_the_session_and_project_manager_lists_info(live):
    w, ecu, obj, pump = live
    rb = w.modas_ribbon
    rb.buttons["record"].click()
    assert not w.session_tab.start_button.isEnabled() and rb.buttons["record"].text() == "Durdur"
    rb.buttons["record"].click()
    assert w.session_tab.start_button.isEnabled() and rb.buttons["record"].text() == "Başlat"
    assert w.project_manager.store is w.project_store


def test_tool_windows_do_not_inflate_the_main_window(qapp):
    """Araç pencereleri (Test Bench ~1400×800 …) ayrı pencerelerdedir; ana Worksheets penceresinin asgari boyutunu büyütmez."""
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1500, 800)
    w.show()
    QTest.qWait(500)
    home = (w.minimumWidth(), w.minimumHeight())
    assert home[1] <= 700, "Worksheets açılış asgari yüksekliği şişmiş"
    w.setCurrentWidget(w.dashboard_tab)
    QTest.qWait(500)
    assert (w.minimumWidth(), w.minimumHeight()) == home
    w.close()


def test_variable_list_uses_distinct_kind_icons(qapp):
    from app.ui.modas.kind_icons import kind_icon
    keys = {k: kind_icon(k).pixmap(16, 16).toImage().bits().tobytes() for k in ("value", "meas", "curve", "map", "text")}
    assert len(set(keys.values())) == 5                            # her tür farklı çizilir
    assert not kind_icon("value").isNull() and not kind_icon("bilinmeyen").isNull()   # bilinmeyen tür ölçüm simgesine düşer


def test_project_manager_creates_and_opens_a_workbase(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from app.modas_projects import ProjectStore, Workbase
    from app.ui.modas.project_manager import ProjectManagerDialog, WorkbaseDialog
    st = ProjectStore(str(tmp_path / "root"))
    st.create_project("Motor1")
    dlg = ProjectManagerDialog(st)
    assert dlg.selected_project().name == "Motor1" and not dlg.btn_open.isEnabled()
    a2l = tmp_path / "x.a2l"
    a2l.write_text("a")
    # "New" penceresi: geçersiz değer penceresi AÇIK bırakır ve nedenini yazar; düzeltilince kaydeder
    wd = WorkbaseDialog(Workbase(name=""))
    wd.name.setText("a/b")
    wd.a2l[1].setText(str(a2l))
    wb = wd.value()
    from app.modas_projects import ProjectError
    try:
        st.save_workbase("Motor1", wb)
        raise AssertionError("geçersiz ad kabul edildi")
    except ProjectError:
        pass
    wd.name.setText("WB_A")
    st.save_workbase("Motor1", wd.value())
    dlg.refresh(select_project="Motor1", select_workbase="WB_A")
    assert dlg.btn_open.isEnabled() and dlg.workbase_info[1]["A2L file"].text() == str(a2l)
    got = []
    dlg.workbase_opened.connect(lambda p, b: got.append((p.name, b.name)))
    dlg._open_workbase()
    assert got == [("Motor1", "WB_A")] and dlg.result() == QDialog.Accepted


def test_opening_a_workbase_sets_ribbon_fields_and_loads_a2l(live, tmp_path):
    w, ecu, obj, pump = live
    st = w.project_store
    pr = st.create_project("ProjeX")
    a2l = os.path.join(DATA, "sample.a2l")
    wb = st.save_workbase("ProjeX", Workbase(name="Tezgah1", a2l=a2l, baudrate=500000))
    w._modas_open_workbase(pr, wb)                                  # zaten bağlı (live): yeniden bağlanmaz
    rb = w.modas_ribbon
    assert rb.fields["project"].text() == "ProjeX" and rb.fields["workbase"].text() == "Tezgah1"
    assert rb.fields["a2l"].text() == "sample.a2l"


# ------------------------------------------------------------------ Aşama 2: tablo biçimi, Diff listesi, veri seti
def test_table_window_number_formats_are_display_only(qapp):
    w = TableWindow(make_map())
    w.set_grid_from_ecu([[1, 2, 3], [255, 4096, 65535]])
    writes = []
    w.write_requested.connect(writes.append)
    w.table.item(0, 0).setText("9")                                   # bekleyen düzenleme (Physical)
    writes.clear()
    w.set_format("hex")
    assert w.table.item(1, 0).text() == "0x00FF" and w.table.item(1, 2).text() == "0xFFFF"
    assert w.table.item(0, 0).text() == "0x0009"                      # bekleyen değer biçim değişiminde korunur
    assert not w.is_cell_editable() and w.table.editTriggers() == QAbstractItemView.NoEditTriggers
    assert w.current_grid() == [[9, 2, 3], [255, 4096, 65535]] and w.is_modified()
    w.table.item(0, 1).setText("zzz")                                 # ham biçimde metin değişse bile veri/yazma etkilenmez
    assert writes == [] and w.current_grid()[0][1] == 2
    w.set_format("bin")
    assert w.table.item(1, 0).text() == "0000000011111111"
    w.set_format("dec")
    assert w.table.item(1, 1).text() == "4096"
    w.set_format("phys")
    assert [w.table.item(1, c).text() for c in range(3)] == ["255", "4096", "65535"] and w.table.item(0, 0).text() == "9"
    assert w.is_cell_editable() and w.state()["fmt"] == "phys"
    w.table.item(0, 2).setText("7")                                   # Physical'a dönünce yazma yolu yeniden çalışır
    assert writes == [w] and w.current_grid()[0][2] == 7


def test_format_shortcuts_reach_tables_and_info_uses_the_active_table(qapp, monkeypatch):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    tab = w.modas_tab
    tw = tab.add_label(make_map())
    tw.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    sheet = tab.current_sheet()
    sheet.mdi.setActiveSubWindow(tw)

    def fire(seq):
        sc = next(s for s in w._modas_shortcuts if s.key().toString() == seq)
        sc.activated.emit()

    fire("Ctrl+H")
    assert tw.fmt == "hex" and tw.table.item(0, 0).text() == "0x0001"
    fire("Ctrl+B")
    assert tw.fmt == "bin"
    fire("Ctrl+D")
    assert tw.fmt == "dec"
    fire("Ctrl+F")                                                    # döngü: dec → hex
    assert tw.fmt == "hex"
    fire("Ctrl+P")
    assert tw.fmt == "phys" and tw.table.item(0, 0).text() == "1"
    shown = []
    monkeypatch.setattr(tab, "show_info", lambda obj: shown.append(obj))
    fire("Ctrl+I")
    assert shown and shown[0] is tw.characteristic
    tw.table.selectAll()                                              # Ctrl+A (QTableWidget yerleşik)
    assert len(tw.table.selectedIndexes()) == 6
    w.close()


def test_diff_list_dialog_enables_revert_only_with_selection_and_rights(qapp):
    from app.ui.modas.dataset_dialogs import DiffListDialog
    d = DiffListDialog([("A", 1.0, 2.0), ("T", [[1, 2]], [[1, 3]])], can_write=True)
    assert d.table.rowCount() == 2 and d.table.item(1, 1).text() == "1×2 tablo" and not d.btn_revert.isEnabled()
    d.table.selectRow(1)
    assert d.btn_revert.isEnabled() and d.selected_names() == ["T"]
    ro = DiffListDialog([("A", 1.0, 2.0)], can_write=False, deny_reason="Yetki yok")
    ro.table.selectRow(0)
    assert not ro.btn_revert.isEnabled()


def test_dataset_choice_dialog_blocks_write_without_rights_and_close_means_later(qapp):
    from app.modas_dataset import DiffEntry
    from app.ui.modas.dataset_dialogs import LATER, DatasetChoiceDialog
    diffs = [DiffEntry("A", 1.0, 2.0)]
    d = DatasetChoiceDialog(diffs, can_write=False, deny_reason="Yetki yok")
    assert not d.btn_write.isEnabled() and d.btn_read.isEnabled() and d.table.rowCount() == 1
    d.reject()
    assert d.choice == LATER
    assert DatasetChoiceDialog(diffs, can_write=True).btn_write.isEnabled()


def test_diff_list_reverts_only_the_selected_labels(live, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    import app.ui.mainwin.modas as mm
    from app.ui.modas.dataset_dialogs import DiffListDialog
    w, ecu, obj, pump = live
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    win = w.modas_tab.add_label(obj)
    assert wait_for(lambda: win.edit.text() == "12.5", pump)
    w.modas_ribbon.buttons["measure"].click()
    win.edit.selectAll()
    QTest.keyClicks(win.edit, "40")
    QTest.keyClick(win.edit, Qt.Key_Return)
    assert wait_for(lambda: w.modas_ribbon.diff_label.text() == "Fark: 1", pump)
    monkeypatch.setattr(mm.QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(DiffListDialog, "exec", lambda self: (self.table.selectAll(), DiffListDialog.Accepted)[1])
    w.modas_ribbon.diff_label.clicked.emit()                          # Diff etiketi tıklanınca liste açılır
    assert struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(12.5)
    assert wait_for(lambda: w.modas_ribbon.diff_label.text() == "Fark: 0", pump)


class _Dataset:
    """Veri seti testleri için: açık workbase + ECU'da 12.5, kayıtlı PC veri setinde 99."""

    def __init__(self, w, ecu, obj, pump, monkeypatch):
        from app.modas_dataset import DatasetStore
        import app.ui.mainwin.modas as mm
        self.w, self.ecu, self.obj, self.pump = w, ecu, obj, pump
        self.mm = mm
        pr = w.project_store.create_project(f"P{next(_ch)}")
        wb = w.project_store.save_workbase(pr.name, Workbase(name="WB"))
        self.workbase = (pr, wb)
        w._modas_workbase = self.workbase
        self.store = DatasetStore(wb.path)
        self.calls = []
        self.choice = None

        def fake_exec(dlg):
            self.calls.append(len(dlg.diffs))
            dlg.choice = self.choice
            return 1
        monkeypatch.setattr(mm.DatasetChoiceDialog, "exec", fake_exec)
        assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
        self.win = w.modas_tab.add_label(obj)
        assert wait_for(lambda: self.win.edit.text() == "12.5", pump)

    def ecu_value(self):
        return struct.unpack("<f", self.ecu.read_memory_bytes(self.obj.address, 4))[0]

    def check(self):
        self.w._modas_check_dataset()
        self.pump()


def test_dataset_write_pc_to_ecu_uses_the_safe_write_path(live, monkeypatch):
    from app.ui.modas.dataset_dialogs import WRITE_PC
    w, ecu, obj, pump = live
    d = _Dataset(w, ecu, obj, pump, monkeypatch)
    d.store.save({obj.name: 99.0})
    d.choice = WRITE_PC
    d.check()
    assert d.calls == [1] and d.ecu_value() == pytest.approx(99.0)
    assert not w._dataset_diffs and not w.modas_ribbon._dataset_alert  # PC = ECU: veri seti uyarısı kalktı
    assert any(e.object_name == obj.name and e.new_value == pytest.approx(99.0) for e in w.calibration_history.entries)
    assert d.store.load() == {obj.name: 99.0}                          # PC veri seti değişmedi


def test_dataset_read_ecu_adopts_ecu_values_and_updates_the_saved_dataset(live, monkeypatch):
    from app.ui.modas.dataset_dialogs import READ_ECU
    w, ecu, obj, pump = live
    d = _Dataset(w, ecu, obj, pump, monkeypatch)
    d.store.save({obj.name: 99.0})
    d.choice = READ_ECU
    d.check()
    assert d.ecu_value() == pytest.approx(12.5)                        # ECU'ya dokunulmadı
    assert d.store.load() == {obj.name: pytest.approx(12.5)}
    assert w.page_model.reference[obj.name] == pytest.approx(12.5) and not w._dataset_diffs
    assert w.modas_ribbon.buttons["wp"].property("alert") is False


def test_dataset_decide_later_keeps_alert_and_explicit_read_resolves_it(live, monkeypatch):
    from app.ui.modas.dataset_dialogs import LATER
    w, ecu, obj, pump = live
    d = _Dataset(w, ecu, obj, pump, monkeypatch)
    d.store.save({obj.name: 99.0})
    d.choice = LATER
    d.check()
    assert d.ecu_value() == pytest.approx(12.5) and d.store.load() == {obj.name: 99.0}
    assert w._dataset_diffs and w.modas_ribbon.buttons["wp"].property("alert") is True
    w.modas_ribbon.buttons["read_ecu"].click()                         # açık 'Read data from ECU' = ECU'yu kabul et
    pump()
    assert not w._dataset_diffs and d.store.load() == {obj.name: pytest.approx(12.5)}
    assert w.modas_ribbon.buttons["wp"].property("alert") is False


def test_dataset_check_is_silent_without_workbase_or_saved_dataset_and_triggers_on_online(live, monkeypatch):
    from app.ui.modas.dataset_dialogs import LATER
    w, ecu, obj, pump = live
    d = _Dataset(w, ecu, obj, pump, monkeypatch)
    d.choice = LATER
    d.check()                                                          # kayıtlı veri seti yok: sorulmaz, ECU ilk veri seti olur
    assert d.calls == [] and d.store.load() == {obj.name: pytest.approx(12.5)}
    d.check()                                                          # aynı veri seti: sorulmaz
    assert d.calls == []
    w._modas_workbase = None
    d.store.save({obj.name: 99.0})
    d.check()                                                          # workbase yok: hiçbir şey yapılmaz
    assert d.calls == []
    # ONLINE geçişi kontrolü bir kez tetikler
    w._modas_workbase = d.workbase
    d.store.save({obj.name: 99.0})
    w._dataset_checked = False
    w._modas_sync_status(force=True)
    assert wait_for(lambda: d.calls == [1], pump)
    w._modas_sync_status(force=True)
    pump()
    assert d.calls == [1]                                              # aynı bağlantıda ikinci kez sorulmaz


def test_f12_saves_the_dataset_of_the_open_workbase(live, monkeypatch):
    w, ecu, obj, pump = live
    d = _Dataset(w, ecu, obj, pump, monkeypatch)
    assert d.store.load() is None
    w._modas_save()
    assert d.store.load() == {obj.name: pytest.approx(12.5)}


def test_dataset_write_pc_writes_tables_through_the_backup_and_verify_path(live, monkeypatch):
    from app.modas_dataset import DatasetStore
    from app.ui.modas.dataset_dialogs import WRITE_PC
    import app.ui.mainwin.modas as mm
    w, ecu, obj, pump = live
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    ch = make_map(addr=0x3000)
    ecu.write_memory_bytes(ch.address, b"".join(struct.pack(">H", v) for v in (1, 2, 3, 4, 5, 6)))
    tw = w.modas_tab.add_label(ch)
    assert wait_for(lambda: tw.current_grid() == [[1, 2, 3], [4, 5, 6]], pump)
    pr = w.project_store.create_project(f"T{next(_ch)}")
    wb = w.project_store.save_workbase(pr.name, Workbase(name="WB"))
    w._modas_workbase = (pr, wb)
    DatasetStore(wb.path).save({ch.name: [[1, 2, 3], [4, 5, 60]]})
    monkeypatch.setattr(mm.DatasetChoiceDialog, "exec", lambda dlg: (setattr(dlg, "choice", WRITE_PC), 1)[1])
    w._modas_check_dataset()
    assert wait_for(lambda: struct.unpack(">H", ecu.read_memory_bytes(ch.address + 10, 2))[0] == 60, pump)
    assert not w._dataset_diffs and not tw.is_modified()
    assert any("Tablo yazıldı" in t for t in w.modas_tab.log_panel.texts())


# ------------------------------------------------------------------ Aşama 3: osiloskop (scope)
def test_scope_window_collects_labels_by_drop_and_feeds_the_hub(qapp):
    from PySide6.QtCore import QMimeData
    from app.signal_hub import SignalHub
    from app.ui.modas.scope import ScopeWindow
    from app.ui.modas.variable_list import MIME
    hub = SignalHub()
    sw = ScopeWindow("Osiloskop 1", hub)
    assert sw.signals() == [] and not sw.hint.isHidden() or sw.hint.isVisibleTo(sw.widget())
    mime = QMimeData()
    mime.setData(MIME, "N_RPM\nT_OIL\nN_RPM".encode("utf-8"))          # tekrar eden etiket bir kez eklenir
    assert sw.add_labels(["N_RPM", "T_OIL", "N_RPM"]) == 2
    assert sw.signals() == ["a2l:N_RPM", "a2l:T_OIL"] and not sw.hint.isVisibleTo(sw.widget())
    hub.set_active(sw.signals())
    for i in range(5):
        hub.push("a2l:N_RPM", 1000 + i)
    sw.panel.refresh(30.0, False)
    assert hub.has_data("a2l:N_RPM") and not hub.has_data("a2l:T_OIL")
    st = sw.state()
    assert st["kind"] == "scope" and st["panel"]["signals"] == ["a2l:N_RPM", "a2l:T_OIL"]
    sw2 = ScopeWindow("Osiloskop 1", hub, state={**st, "span": 60.0})
    assert sw2.signals() == ["a2l:N_RPM", "a2l:T_OIL"] and sw2.span_combo.currentText() == "1 min"
    sw.clear_signals()
    assert sw.signals() == []
    sw.close()
    sw2.close()


def test_workspace_scopes_persist_without_an_a2l_and_limit_the_hub_to_used_signals(qapp, tmp_path):
    path = str(tmp_path / "ws.json")
    ws = ModasWorkspace(ModasSheetStore(path))
    sc = ws.add_scope(["N_RPM"])
    assert sc.label == "Osiloskop 1" and ws.add_scope().label == "Osiloskop 2"
    assert ws.scope_labels() == ["N_RPM"] and ws.hub.active() == {"a2l:N_RPM"}
    ws.push_sample("N_RPM", 3000)
    ws.push_sample("OTHER", 1)                                         # kullanılmayan etiket depolanmaz
    assert ws.hub.has_data("a2l:N_RPM") and not ws.hub.has_data("a2l:OTHER")
    assert ws.save()
    ws.close_all()
    ws2 = ModasWorkspace(ModasSheetStore(path))                       # A2L yok: osiloskoplar yine de geri gelir
    assert sorted(w.label for w in ws2.scope_windows()) == ["Osiloskop 1", "Osiloskop 2"]
    assert ws2.scope_labels() == ["N_RPM"] and ws2.hub.active() == {"a2l:N_RPM"}
    ws2.scope_windows()[0].close()
    ws2.scope_windows()[0].close()
    assert ws2.hub.active() == set()


def test_scope_records_only_while_measuring_and_reads_labels_that_are_not_open_windows(live):
    w, ecu, obj, pump = live
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    sc = w.modas_tab.add_scope([obj.name])                              # etiket worksheet'te değer penceresi olarak AÇIK DEĞİL
    assert w.modas_tab.value_windows() == []
    w._modas_tick()
    assert wait_for(lambda: w.modas_tab.hub.has_data(f"a2l:{obj.name}"), lambda: (pump(), w._modas_tick()))
    t, v = w.modas_tab.hub.get(f"a2l:{obj.name}")
    assert float(v[-1]) == pytest.approx(12.5)
    n = len(v)
    ecu.write_memory_bytes(obj.address, struct.pack("<f", 20.0))
    assert wait_for(lambda: float(w.modas_tab.hub.get(f"a2l:{obj.name}")[1][-1]) == pytest.approx(20.0),
                    lambda: (pump(), w._modas_tick()))
    assert len(w.modas_tab.hub.get(f"a2l:{obj.name}")[1]) > n
    w.modas_ribbon.buttons["add_scope"].click()                         # ribbon düğmesi yeni osiloskop açar
    assert len(w.modas_tab.scope_windows()) == 2
    sc.close()


# ------------------------------------------------------------------ Aşama 3c: worksheet şablonları
def test_template_menu_builds_a_new_worksheet_without_writing_or_measuring(live, monkeypatch, tmp_path):
    w, ecu, obj, pump = live
    tab = w.modas_tab
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    n_sheets = len(tab.sheets)
    menu = w.modas_ribbon.buttons["sheet_template"].menu()
    menu.aboutToShow.emit()
    texts = [a.text() for a in menu.actions() if a.text()]
    assert texts[:2] == ["İzleme", "Kalibrasyon"]
    before = ecu.read_memory_bytes(obj.address, 4)
    next(a for a in menu.actions() if a.text() == "Kalibrasyon").trigger()
    assert len(tab.sheets) == n_sheets + 1 and tab.current_sheet().name == "Kalibrasyon"
    labels = [x.label for x in tab.value_windows()]
    assert obj.name in labels                                             # A2L'deki ayarlanabilir değer pencereye geldi
    assert not tab.is_measuring and ecu.read_memory_bytes(obj.address, 4) == before   # yazma / ölçüm yok
    next(a for a in menu.actions() if a.text() == "İzleme").trigger()
    assert tab.current_sheet().name == "İzleme" and len(tab.scope_windows(all_sheets=False)) == 1
    next(a for a in menu.actions() if a.text() == "İzleme").trigger()   # tekrar: ad çakışmaz
    assert tab.current_sheet().name == "İzleme 2"


def test_user_template_saves_current_worksheet_and_reapplies_it(live, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    w, ecu, obj, pump = live
    tab = w.modas_tab
    tab.add_scope([obj.name])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Benim Test", True)))
    w._modas_save_template()
    assert w.template_store.names() == ["Benim Test"]
    menu = w.modas_ribbon.buttons["sheet_template"].menu()
    menu.aboutToShow.emit()
    next(a for a in menu.actions() if a.text() == "Benim Test").trigger()
    cur = tab.current_sheet()
    assert cur.name == "Benim Test"
    assert tab.scope_windows(all_sheets=False)[0].labels() == [obj.name]
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Kalibrasyon", True)))
    monkeypatch.setattr("app.ui.mainwin.modas.QMessageBox.warning", staticmethod(lambda *a, **k: None))
    w._modas_save_template()                                              # hazır şablon adı ezilemez
    assert w.template_store.names() == ["Benim Test"]


# ------------------------------------------------------------------ Aşama 3d: tek tuşla kayıt
def test_record_prefills_name_and_operator_and_f4_marks_only_while_recording(live, monkeypatch):
    w, ecu, obj, pump = live
    rb, st = w.modas_ribbon, w.session_tab
    w.current_user = "Zeynep"
    pr = w.project_store.create_project(f"Rec{next(_ch)}")
    wb = w.project_store.save_workbase(pr.name, Workbase(name="Tezgah"))
    w._modas_workbase = (pr, wb)
    assert not rb.buttons["mark"].isEnabled() and not rb.buttons["open_record"].isEnabled()
    w._modas_add_marker()                                              # kayıt yokken işaret eklenmez
    assert not [e for e in w.event_log.entries if e.category == "ISARET"]
    rb.buttons["record"].click()                                       # tek tuş: ad ve operatör otomatik
    assert st.name_edit.text().startswith(f"{pr.name}_Tezgah_") and st.operator_edit.text() == "Zeynep"
    assert rb.buttons["mark"].isEnabled() and not st.start_button.isEnabled()
    w._modas_add_marker()
    w._modas_add_marker()
    marks = [e.message for e in w.event_log.entries if e.category == "ISARET"]
    assert marks == ["Test işareti #1", "Test işareti #2"]
    rb.buttons["record"].click()
    assert st.start_button.isEnabled() and not rb.buttons["mark"].isEnabled()
    path = w._last_record_csv
    assert path and os.path.isfile(path) and os.path.basename(path).startswith(st.name_edit.text()[:10])
    assert rb.buttons["open_record"].isEnabled()
    assert any("Kayıt kaydedildi" in t for t in w.modas_tab.log_panel.texts())
    opened = []
    monkeypatch.setattr("app.ui.mainwin.modas.QDesktopServices.openUrl", staticmethod(lambda url: opened.append(url.toLocalFile())))
    rb.buttons["open_record"].click()
    assert opened == [os.path.dirname(path)]


def test_record_keeps_a_name_the_user_already_typed(live):
    w, ecu, obj, pump = live
    st = w.session_tab
    st.name_edit.setText("Soğutma testi #3")
    st.operator_edit.setText("Ayşe")
    w.modas_ribbon.buttons["record"].click()
    assert st.name_edit.text() == "Soğutma testi #3" and st.operator_edit.text() == "Ayşe"
    w.modas_ribbon.buttons["record"].click()


# ------------------------------------------------------------------ Aşama 4: dosya yöneticileri + macro
def _write_via_window(w, win, text, pump):
    win.edit.selectAll()
    QTest.keyClicks(win.edit, text)
    QTest.keyClick(win.edit, Qt.Key_Return)
    pump()


def _fuel(live_tuple):
    w, ecu, obj, pump = live_tuple
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    win = w.modas_tab.add_label(obj)
    assert wait_for(lambda: win.edit.text() == "12.5", pump)
    return win


def test_data_file_save_compare_and_write_selected(live, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    import app.ui.mainwin.modas_tools as mt
    from app.modas_datafiles import load_values
    w, ecu, obj, pump = live
    win = _fuel(live)
    path = str(tmp_path / "wp.json")
    assert w._modas_save_wp_file(path) and load_values(path) == {obj.name: pytest.approx(12.5)}
    w.modas_ribbon.buttons["measure"].click()                                   # canlı WP okuması akar
    _write_via_window(w, win, "40", pump)                                       # WP artık dosyadan farklı
    assert wait_for(lambda: struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(40.0), pump)
    assert wait_for(lambda: w.modas_tab.wp_snapshot().get(obj.name) == pytest.approx(40.0), pump)   # WP okuması güncellendi
    monkeypatch.setattr(mt.DiffListDialog, "exec", lambda d: (d.table.selectAll(), mt.DiffListDialog.Accepted)[1])
    monkeypatch.setattr("app.ui.mainwin.modas.QMessageBox.question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    ok, msg = w._modas_compare_file(path)
    assert ok and struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(12.5)   # dosya → ECU


def test_data_file_compare_reports_identical_unreadable_and_unauthorized(live, monkeypatch, tmp_path):
    import app.ui.mainwin.modas_tools as mt
    w, ecu, obj, pump = live
    _fuel(live)
    path = str(tmp_path / "wp.json")
    w._modas_save_wp_file(path)
    ok, msg = w._modas_compare_file(path)
    assert ok and "aynı" in msg                                                  # fark yok
    warned = []
    monkeypatch.setattr(mt.QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    bad = tmp_path / "bad.json"
    bad.write_text("{bozuk", encoding="utf-8")
    ok, msg = w._modas_compare_file(str(bad))
    assert not ok and warned



def test_parameter_file_manager_saves_applies_and_deletes(live, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    from app.ui.modas.tools_dialogs import ParameterFilesDialog
    w, ecu, obj, pump = live
    _fuel(live)
    pr = w.project_store.create_project(f"Par{next(_ch)}")
    wb = w.project_store.save_workbase(pr.name, Workbase(name="WB"))
    w._modas_workbase = (pr, wb)
    folder = w._modas_params_folder()
    assert folder.folder.startswith(pr.path) and folder.list() == []
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Baz değer", True)))
    ok, msg = w._modas_param_save()
    assert ok and [n for n, _p, _t in folder.list()] == ["Baz değer"]
    dlg = ParameterFilesDialog(folder, w._modas_param_save, w._modas_compare_file_result, w._modas_param_delete)
    assert dlg.list.count() == 1 and not dlg.btn_apply.isEnabled()
    dlg.list.setCurrentRow(0)
    assert dlg.btn_apply.isEnabled() and dlg.btn_delete.isEnabled()
    monkeypatch.setattr("app.ui.mainwin.modas_tools.QMessageBox.question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    dlg._save()                                                                   # aynı ad: üzerine yazma sorulur (Evet)
    assert dlg.list.count() == 1 and "Kaydedildi" in dlg.status.text()
    monkeypatch.setattr("app.ui.mainwin.modas_tools.QMessageBox.question", staticmethod(lambda *a, **k: QMessageBox.No))
    dlg._save()
    assert "Kaydedilmedi" in dlg.status.text()
    dlg._delete()                                                                 # Hayır: silinmez
    assert dlg.list.count() == 1
    monkeypatch.setattr("app.ui.mainwin.modas_tools.QMessageBox.question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    dlg._delete()
    assert dlg.list.count() == 0 and folder.list() == []


def test_macro_records_successful_writes_and_replays_them_through_the_safe_path(live, monkeypatch):
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    w, ecu, obj, pump = live
    win = _fuel(live)
    monkeypatch.setattr("app.ui.mainwin.modas.QMessageBox.question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr("app.ui.mainwin.modas_tools.QMessageBox.question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    assert w._modas_macro_toggle()[0] and w.macro_recorder.active
    _write_via_window(w, win, "30", pump)
    assert wait_for(lambda: w.macro_recorder.steps[-1:] == [{"kind": "value", "label": obj.name, "value": 30.0}], pump)
    _write_via_window(w, win, "40", pump)
    assert wait_for(lambda: len(w.macro_recorder.steps) == 1 and w.macro_recorder.steps[0]["value"] == 40.0, pump)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Yakıt 40", True)))
    ok, msg = w._modas_macro_toggle()
    assert ok and not w.macro_recorder.active and w._modas_macro_store().names() == ["Yakıt 40"]
    _write_via_window(w, win, "5", pump)
    assert wait_for(lambda: struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(5.0), pump)
    ok, msg = w._modas_macro_play("Yakıt 40")
    assert ok and struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(40.0)
    assert not w.macro_recorder.active and w.macro_recorder.steps == [{"kind": "value", "label": obj.name, "value": 40.0}]


def test_macro_play_checks_preconditions_before_writing_anything(live, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    w, ecu, obj, pump = live
    _fuel(live)
    store = w._modas_macro_store()
    store.save("M", [{"kind": "value", "label": obj.name, "value": 77.0},
                     {"kind": "table", "label": "YOK_TABLO", "value": [[1, 2]]}])
    asked = []
    monkeypatch.setattr("app.ui.mainwin.modas_tools.QMessageBox.question",
                        staticmethod(lambda *a, **k: asked.append(1) or QMessageBox.Yes))
    ok, msg = w._modas_macro_play("M")                                            # açık olmayan etiket: hiçbir şey yazılmaz
    assert not ok and "YOK_TABLO" in msg and not asked
    assert struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(12.5)
    store.save("Tek", [{"kind": "value", "label": obj.name, "value": 77.0}])
    monkeypatch.setattr("app.ui.mainwin.modas_tools.QMessageBox.question", staticmethod(lambda *a, **k: QMessageBox.No))
    ok, msg = w._modas_macro_play("Tek")                                          # onay Hayır: yazılmaz
    assert not ok and struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == pytest.approx(12.5)
    w._modas_macro_toggle()
    ok, msg = w._modas_macro_play("Tek")                                          # kayıt sürerken oynatılmaz
    assert not ok and "Kayıt" in msg
    w.macro_recorder.stop()
    assert w._modas_macro_toggle()[0] is True and w._modas_macro_toggle()[0] is False   # boş kayıt: macro oluşmaz
    assert w._modas_macro_store().names() == ["M", "Tek"]
    w._modas_workbase = None


def test_macro_dialog_lists_steps_and_toggles_record_button(live, monkeypatch):
    from app.ui.modas.tools_dialogs import MacroDialog
    w, ecu, obj, pump = live
    store = w._modas_macro_store()
    store.save("D", [{"kind": "value", "label": "A", "value": 1.0}, {"kind": "table", "label": "T", "value": [[1, 2]]}])
    dlg = MacroDialog(store, w.macro_recorder, w._modas_macro_toggle, w._modas_macro_play, w._modas_macro_delete)
    dlg.list.setCurrentRow(0)
    assert [dlg.steps.item(i).text() for i in range(dlg.steps.count())] == ["1. A = 1", "2. T = 1×2 tablo"]
    assert dlg.btn_play.isEnabled() and dlg.btn_record.text() == "● Kaydet"
    dlg._record()
    assert w.macro_recorder.active and dlg.btn_record.text().startswith("■") and not dlg.btn_play.isEnabled()
    w.macro_recorder.stop()
    dlg.close()


def test_tools_tab_has_file_and_macro_buttons(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    b = w.modas_ribbon.buttons
    assert {"data_file", "param_files", "macros"} <= set(b)
    texts = [a.text() for a in b["data_file"].menu().actions()]
    assert texts == ["WP'yi dosyaya kaydet…", "Dosyayı WP ile karşılaştır…"]
    w.close()


def _cal_window(summary):
    cal = next(c for c in summary.characteristics if c.name == "clbc_Temp_limit")
    w = ValueWindow(cal)
    w.show()
    w.set_reading(_reading(10.0))
    return w


def test_value_window_applied_change_shows_single_red_arrow_icon_and_delta(summary, qapp):
    from app.change_tracker import ChangeTracker
    w = _cal_window(summary)
    ct = ChangeTracker()
    ct.observe(w.obj.name, 10.0, w.obj.unit or "")
    ct.applied(w.obj.name, 10.0, 12.5, w.obj.unit or "", now=50.0)
    state, arrow, delta, mode = ct.change_view(w.obj.name, now=60.0)
    w.set_change(arrow, delta, ct.summary(w.obj.name), mode, now=60.0)
    assert w.change_state == "applied"
    assert w.change_icon.isVisible() and w.change_icon.property("arrow") == "↑"
    assert w.change_text.text() == "+2.5 rpm"                                # çift ok / çift birim YOK
    assert w.unit_label.text() == (w.obj.unit or "")                         # birim etiketi yalnızca birim
    assert "↑" not in w.change_text.text() and "↑" not in w.unit_label.text()
    ct.applied(w.obj.name, 12.5, 8.0, w.obj.unit or "", now=70.0)
    state, arrow, delta, mode = ct.change_view(w.obj.name, now=80.0)
    w.set_change(arrow, delta, "", mode, now=80.0)
    assert w.change_icon.property("arrow") == "↓" and w.change_text.text().startswith("-")


def test_value_window_arrow_blinks_only_right_after_write(summary, qapp):
    w = _cal_window(summary)
    w.set_change("↑", "+1", "", "blink", now=0.0)          # faz 0: görünür
    assert w.change_icon.isVisible()
    w.set_change("↑", "+1", "", "blink", now=0.25)         # faz 1: sönük
    assert not w.change_icon.isVisible()
    w.set_change("↑", "+1", "", "steady", now=0.25)        # blink bitti: sabit
    assert w.change_icon.isVisible()


def test_value_window_pending_typed_value_is_distinct_hollow_arrow(summary, qapp):
    w = _cal_window(summary)
    w.set_change("↓", "-3", "", "steady", now=0.0)          # önceki uygulanmış değişim
    w.edit.setText("14")
    w._on_text_edited("14")                                  # kullanıcı yazdı, Enter yok
    assert w.change_state == "pending"
    assert w.change_icon.property("arrow") == "↑"            # yön ECU'daki (10) değere göre
    assert "yazılmadı" in w.change_text.text() and "+4" in w.change_text.text()
    w.discard_pending()                                      # Esc: bekleyen biter, uygulanmış gösterim geri gelir
    assert w.change_state == "applied" and w.change_icon.property("arrow") == "↓"


def test_value_window_failed_write_shows_warning_not_arrow(summary, qapp):
    w = _cal_window(summary)
    w.set_change("", "", "Son yazma BAŞARISIZ", "", failed=True)
    assert w.change_state == "failed"
    assert not w.change_icon.isVisible() and "uygulanmadı" in w.change_text.text()


def test_arrow_icons_distinguish_applied_and_pending(qapp):
    from app.ui.change_icons import arrow_icon
    filled, hollow = arrow_icon(True, 16).pixmap(16, 16).toImage(), arrow_icon(True, 16, hollow=True).pixmap(16, 16).toImage()
    assert filled != hollow                                  # dolu ≠ içi boş
    assert arrow_icon(True, 16).pixmap(16, 16).toImage() != arrow_icon(False, 16).pixmap(16, 16).toImage()
    c = filled.pixelColor(8, 10)                              # gövde ortası dolu kırmızı
    assert c.red() > 150 and c.green() < 80 and c.alpha() > 200


def _map_window():
    w = TableWindow(make_map(rows=2, cols=3))
    w.show()
    w.set_grid_from_ecu([[10, 20, 30], [40, 50, 60]])
    return w


def test_table_window_pending_cells_show_hollow_arrow_by_direction_and_summary(qapp):
    w = _map_window()
    assert w.cell_change(0, 0) == ("", "", "") and not w.change_summary.isVisible()
    w.table.item(0, 1).setText("25")        # artış
    w.table.item(1, 2).setText("45")        # azalış
    assert w.cell_change(0, 1) == ("pending", "↑", "+5")
    assert w.cell_change(1, 2) == ("pending", "↓", "-15")
    assert not w.table.item(0, 1).icon().isNull() and not w.table.item(1, 2).icon().isNull()
    assert w.table.item(0, 0).icon().isNull()                              # değişmeyen hücre işaretsiz
    assert "Yazılmadı" in w.change_summary.text() and "2 hücre" in w.change_summary.text()
    assert "↑1" in w.change_summary.text() and "↓1" in w.change_summary.text()
    assert "yazılmadı" in w.table.item(0, 1).toolTip() and "eski 20" in w.table.item(0, 1).toolTip()


def test_table_window_applied_cells_keep_red_arrow_after_successful_write(qapp):
    w = _map_window()
    w.table.item(0, 1).setText("25")
    w.table.item(1, 0).setText("30")
    w.set_write_result(True, "yazıldı")
    assert w.cell_change(0, 1) == ("applied", "↑", "+5") and w.cell_change(1, 0) == ("applied", "↓", "-10")
    assert "ECU'ya yazıldı" in w.change_summary.text() and "Yazılmadı" not in w.change_summary.text()
    w.set_grid_from_ecu([[10, 25, 30], [30, 50, 60]])                       # doğrulama okuması işareti silmez
    assert w.cell_change(0, 1)[0] == "applied"
    w.table.item(0, 1).setText("100")                                       # yeniden düzenleme: bekleyen öncelikli
    assert w.cell_change(0, 1) == ("pending", "↑", "+75")
    assert "eski 25" in w.table.item(0, 1).toolTip()


def test_table_window_failed_write_leaves_cells_pending_without_applied_arrows(qapp):
    w = _map_window()
    w.table.item(0, 0).setText("11")
    w.set_write_result(False, "ECU reddetti")
    assert w.cell_change(0, 0)[0] == "pending"                              # hâlâ yazılmadı
    assert not any(state == "applied" for state in (w.cell_change(r, c)[0] for r in range(2) for c in range(3)))


def test_table_window_revert_to_original_clears_marks(qapp):
    w = _map_window()
    w.table.item(1, 1).setText("99")
    assert w.cell_change(1, 1)[0] == "pending"
    w.table.item(1, 1).setText("50")                                        # eski değere dönüldü
    assert w.cell_change(1, 1) == ("", "", "") and not w.change_summary.isVisible()


def test_table_window_baseline_deviation_summary(qapp):
    w = _map_window()                                                       # ilk ECU okuması = başlangıç referansı
    assert w.baseline_deviation() is None and not w.change_summary.isVisible()
    w.table.item(0, 0).setText("15")                                        # +5
    w.table.item(1, 2).setText("30")                                        # -30
    dev = w.baseline_deviation()
    assert dev["cells"] == 2 and dev["max_cell"] == (1, 2) and dev["max_abs"] == 30.0 and dev["mean"] == -12.5
    txt = w.change_summary.text()
    assert "Başlangıca göre" in txt and "oturum başı ECU değeri" in txt and "2 hücre sapmış" in txt
    w.set_write_result(True, "ok")
    w.set_grid_from_ecu([[15, 20, 30], [40, 50, 30]])                       # yeni okuma referansı DEĞİŞTİRMEZ
    assert w.baseline_deviation()["cells"] == 2
    w.table.item(0, 0).setText("10")
    w.table.item(1, 2).setText("60")                                        # başlangıç değerlerine dönüldü
    assert w.baseline_deviation() is None


def test_table_window_history_requested_from_summary_link_and_value_window_arrow(summary, qapp):
    w = _map_window()
    got = []
    w.history_requested.connect(got.append)
    w.table.item(0, 1).setText("25")
    w.set_write_result(True, "ok")
    assert "Geçmişte göster" in w.change_summary.text()
    w.change_summary.linkActivated.emit("history")
    assert got == [w.characteristic.name]
    v = _cal_window(summary)
    got2 = []
    v.history_requested.connect(got2.append)
    v.set_change("↑", "+1", "", "steady")
    from PySide6.QtCore import QPoint, Qt as _Qt
    from PySide6.QtTest import QTest
    QTest.mouseClick(v.change_icon, _Qt.LeftButton, pos=QPoint(5, 5))
    QTest.mouseClick(v.change_text, _Qt.LeftButton, pos=QPoint(3, 3))
    assert got2 == [v.obj.name, v.obj.name]


def test_gauge_window_follows_the_ecu_value_in_the_measurement_round(live):
    w, ecu, obj, pump = live
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    g = w.modas_tab.add_gauge(obj.name)
    assert wait_for(lambda: (w._modas_gauge_sample(g) or g.value) == pytest.approx(12.5), pump)
    ecu.write_memory_bytes(obj.address, struct.pack("<f", 20.0))
    assert wait_for(lambda: (w._modas_gauge_sample(g) or g.value) == pytest.approx(20.0), pump)
    w.modas_ribbon.buttons["measure"].click()                              # ölçüm turu göstergeyi de besler
    ecu.write_memory_bytes(obj.address, struct.pack("<f", 33.0))
    assert wait_for(lambda: g.value == pytest.approx(33.0), pump)


def test_undo_stack_semantics():
    from app.undo_stack import UndoStack
    s = UndoStack(limit=2)
    s.push("value", "a", None, 1.0)                                    # eski değer bilinmiyor: kaydedilmez
    s.push("value", "a", 1.0, 1.0)                                     # değişiklik yok: kaydedilmez
    assert not s.can_undo()
    for i in range(3):
        s.push("value", "a", float(i), float(i + 1))
    assert s.peek_undo().old == 2.0 and len(s._undo) == 2             # sınır 2: en eski atıldı
    s.commit_undo()
    assert s.can_redo() and s.peek_redo().new == 3.0 and s.peek_undo().old == 1.0
    s.push("value", "b", 5.0, 6.0)                                     # yeni yazım yinele yığınını temizler
    assert not s.can_redo()


def test_undo_redo_value_and_table_write_through_safe_path(live):
    w, ecu, obj, pump = live
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump)
    win = w.modas_tab.add_label(obj)
    w.modas_ribbon.buttons["measure"].click()
    assert wait_for(lambda: win.edit.text() == "12.5", pump)
    win.edit.selectAll()
    QTest.keyClicks(win.edit, "40")
    QTest.keyClick(win.edit, Qt.Key_Return)
    assert wait_for(lambda: win.edit.text() == "40" and not win.has_pending, pump)
    assert w.undo_stack.can_undo()
    rd = lambda: struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0]      # noqa: E731
    w._modas_undo_redo(False)                                                         # Ctrl+Z
    assert rd() == pytest.approx(12.5) and w.undo_stack.can_redo() and not w.undo_stack.can_undo()
    assert wait_for(lambda: win.edit.text() == "12.5", pump)
    w._modas_undo_redo(True)                                                          # Ctrl+Y
    assert rd() == pytest.approx(40.0) and w.undo_stack.can_undo()
    # tablo
    ch = make_map(addr=0x3000)
    ecu.write_memory_bytes(ch.address, b"".join(struct.pack(">H", v) for v in (1, 2, 3, 4, 5, 6)))
    tw = w.modas_tab.add_label(ch)
    assert wait_for(lambda: tw.current_grid() == [[1, 2, 3], [4, 5, 6]], pump)
    tw.table.item(0, 1).setText("99")
    assert wait_for(lambda: struct.unpack(">H", ecu.read_memory_bytes(ch.address + 2, 2))[0] == 99, pump)
    n = len(w.undo_stack._undo)
    w._modas_undo_redo(False)
    assert struct.unpack(">H", ecu.read_memory_bytes(ch.address + 2, 2))[0] == 2
    assert len(w.undo_stack._undo) == n - 1 and w.undo_stack.can_redo()
    w._modas_undo_redo(True)
    assert struct.unpack(">H", ecu.read_memory_bytes(ch.address + 2, 2))[0] == 99


def test_undo_without_history_or_window_does_nothing(live):
    w, ecu, obj, pump = live
    w._modas_undo_redo(False)
    assert "yok" in w.statusBar().currentMessage()
    w.undo_stack.push("value", "kapalı_etiket", 1.0, 2.0)
    w._modas_undo_redo(False)
    assert "pencere açık değil" in w.statusBar().currentMessage() and w.undo_stack.can_undo()
