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


# ------------------------------------------------------------------ harita ısı haritası
def test_heat_color_gradient_endpoints_and_degenerate_range():
    from app.ui.modas.windows import heat_color
    lo, mid, hi = heat_color(0, 0, 10), heat_color(5, 0, 10), heat_color(10, 0, 10)
    assert (lo.red(), lo.green(), lo.blue()) == (0xCF, 0xE3, 0xFA) and (hi.red(), hi.green(), hi.blue()) == (0xF6, 0xB8, 0xA0)
    assert (mid.red(), mid.green(), mid.blue()) == (0xFF, 0xF6, 0xC8)
    assert heat_color(7, 3, 3) == heat_color(5, 0, 10)                      # lo == hi: orta renk
    assert heat_color(-5, 0, 10) == lo and heat_color(99, 0, 10) == hi        # aralık dışı kırpılır


def test_table_heatmap_colors_cells_by_value_but_pending_stays_yellow_and_data_is_unchanged(qapp):
    from PySide6.QtGui import QColor
    from app import theme
    from tests.test_modas import make_map
    from app.ui.modas.windows import TableWindow
    w = TableWindow(make_map(rows=2, cols=3))
    w.set_grid_from_ecu([[10, 20, 30], [40, 50, 60]])
    plain = [w.table.item(0, 0).background().color().name(), w.table.item(1, 2).background().color().name()]
    assert plain[0] == plain[1] == QColor(theme.MODAS_CAL_BG).name()
    w.set_heatmap(True)
    low, high = w.table.item(0, 0).background().color(), w.table.item(1, 2).background().color()
    assert low.blue() > low.red() and high.red() > high.blue()                 # düşük: mavimsi, yüksek: turuncumsu
    assert w.current_grid() == [[10, 20, 30], [40, 50, 60]] and not w.is_modified()      # veri değişmedi
    w.table.item(0, 1).setText("25")                                           # bekleyen düzenleme: sarı kalır
    assert w.table.item(0, 1).background().color().name() == QColor(theme.PENDING_BG).name()
    assert w.state()["heat"] is True
    w.set_heatmap(False)
    assert w.table.item(1, 2).background().color().name() == QColor(theme.MODAS_CAL_BG).name() and w.state()["heat"] is False


def test_heatmap_choice_survives_reload(qapp, tmp_path):
    from app.a2l import A2LDatabase
    from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace
    from tests.test_modas import make_map
    path = str(tmp_path / "s.json")
    db = A2LDatabase()
    db.load(os.path.join(DATA, "sample.a2l"))
    w = ModasWorkspace(ModasSheetStore(path))
    w.set_summary(db.summary)
    tw = w.add_label(make_map("HARITA1", rows=2, cols=3))
    tw.set_heatmap(True)
    w.shutdown()
    w2 = ModasWorkspace(ModasSheetStore(path))
    w2.set_summary(db.summary)
    w2._by_name["HARITA1"] = make_map("HARITA1", rows=2, cols=3)                  # harita A2L'de yok: etiket bulunduğunda kurulur
    w2._materialize(w2.current_sheet())
    assert [t.heatmap for t in w2.table_windows()] == [True]
    w2.shutdown()


# ------------------------------------------------------------------ gösterge penceresi
def _ws_with_a2l(tmp_path, name="s.json"):
    from app.a2l import A2LDatabase
    from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace
    db = A2LDatabase()
    db.load(os.path.join(DATA, "sample.a2l"))
    w = ModasWorkspace(ModasSheetStore(str(tmp_path / name)))
    w.set_summary(db.summary)
    return w, db


def test_gauge_window_uses_a2l_range_and_never_invents_one(qapp, tmp_path):
    from types import SimpleNamespace as NS
    from app.ui.modas.gauge_window import GaugeWindow
    fixed = GaugeWindow(NS(name="N_RPM", unit="rpm", minimum=0, maximum=7000))
    assert fixed.fixed_range and fixed.gauge._max == 7000
    fixed.set_value(3500)
    assert fixed.value == 3500
    fixed.set_value("x")                                                   # sayı değil: boş
    assert fixed.value is None
    fixed.set_value(float("nan"))
    assert fixed.value is None
    auto = GaugeWindow(NS(name="Y", unit="bar", minimum=None, maximum=None))   # A2L'de sınır yok: uydurma yok
    assert not auto.fixed_range
    auto.set_value(5.0)
    auto.set_value(12.0)
    assert auto.gauge._min == 0.0 and auto.gauge._max == 12.0 and "sınır yok" in auto.toolTip()
    assert fixed.state()["kind"] == "gauge" and fixed.state()["name"] == "N_RPM"


def test_add_gauge_dedups_rejects_tables_and_persists(qapp, tmp_path):
    from tests.test_modas import make_map
    w, db = _ws_with_a2l(tmp_path)
    g = w.add_gauge("Tt2_raw")
    assert g is not None and w.add_gauge("Tt2_raw") is g and len(w.gauge_windows()) == 1      # aynı etiket tek pencere
    assert w.add_gauge("YOK") is None and w.add_gauge(make_map("M1")) is None                # bilinmeyen / tablo reddedilir
    w.shutdown()
    w2, _ = _ws_with_a2l(tmp_path)
    assert [x.obj.name for x in w2.gauge_windows()] == ["Tt2_raw"]                               # yeniden açılışta geri gelir
    w2.shutdown()


def test_gauge_pending_until_a2l_arrives_and_main_window_measurement_round_feeds_it(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        rb = w.modas_ribbon
        assert "add_gauge" in rb.buttons and rb.buttons["add_gauge"].text() == "Gösterge"
        w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
        w.modas_tab.set_summary(w.a2l_tab.db.summary)
        g = w.modas_tab.add_gauge("Tt2_raw")
        w._modas_gauge_sample(g)                                           # CCP yok: değer boş kalır, çökmez
        assert g.value is None
    finally:
        w.close()


# ------------------------------------------------------------------ çalışma tabanı başına düzen
def test_switch_store_inherits_layout_when_target_is_new_and_loads_when_it_exists(qapp, tmp_path):
    from app.ui.modas.workspace import ModasSheetStore
    w, _db = _ws_with_a2l(tmp_path, "genel.json")
    try:
        w.add_gauge("Tt2_raw")
        w.add_scope([])
        a = ModasSheetStore(str(tmp_path / "taban_a.json"))
        assert w.switch_store(a) == "inherited"                          # yeni dosya: mevcut düzen devredilir
        assert len(w.gauge_windows()) == 1 and len(w.scope_windows()) == 1
        assert a.load() is not None                                      # yeni dosyaya yazıldı
        w.add_gauge("clbc_Fuel_pump_gain")                               # A'ya özel düzen: 2 gösterge
        b = ModasSheetStore(str(tmp_path / "taban_b.json"))
        w.switch_store(b)
        for g in list(w.gauge_windows()):
            g.close()                                                    # B'nin düzeni: gösterge yok
        assert w.switch_store(ModasSheetStore(str(tmp_path / "taban_a.json"))) == "loaded"   # A geri gelir
        assert sorted(g.obj.name for g in w.gauge_windows()) == ["Tt2_raw", "clbc_Fuel_pump_gain"]
        assert len(w.scope_windows()) == 1
        assert w.switch_store(ModasSheetStore(str(tmp_path / "taban_a.json"))) == "same"
        assert w.switch_store(ModasSheetStore(str(tmp_path / "taban_b.json"))) == "loaded"
        assert w.gauge_windows() == []                                   # B: A'nın pencereleri sızmadı
        assert [s.name for s in w._sheets] and w.tabs.count() == len(w._sheets)
    finally:
        w.shutdown()


def test_opening_a_workbase_switches_to_its_own_layout_file(qapp, tmp_path):
    from app.ui.main_window import MainWindow
    from app.modas_projects import Workbase
    w = MainWindow()
    try:
        pr = w.project_store.create_project("DuzenProje")
        wb1 = w.project_store.save_workbase(pr.name, Workbase(name="T1"))
        wb2 = w.project_store.save_workbase(pr.name, Workbase(name="T2"))
        w.modas_tab.add_scope([])
        w._modas_open_workbase(pr, wb1)
        assert os.path.isfile(os.path.join(wb1.path, "calisma_sayfalari.json"))
        assert len(w.modas_tab.scope_windows()) == 1                     # ilk açılış: mevcut düzen devredildi
        for s in list(w.modas_tab.scope_windows()):
            s.close()
        w.modas_tab.add_scope([]); w.modas_tab.add_scope([])
        w._modas_open_workbase(pr, wb2)                                  # T2: yeni dosya, mevcut düzen (2 osiloskop) devralınır
        assert len(w.modas_tab.scope_windows()) == 2
        w.modas_tab.scope_windows()[0].close()                           # T2'de düzen değişir: 1 osiloskop
        w._modas_open_workbase(pr, wb1)                                  # T1'e dönüş: T1'in son düzeni (2 osiloskop)
        assert len(w.modas_tab.scope_windows()) == 2
        w._modas_open_workbase(pr, wb2)                                  # T2'ye dönüş: T2'nin kendi düzeni (1 osiloskop)
        assert len(w.modas_tab.scope_windows()) == 1
    finally:
        w.close()
