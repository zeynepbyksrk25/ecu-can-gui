"""Scope (Worksheets osiloskop) sinyal kaynakları: DBC/gösterge/giriş beslemesi, sinyal seçici, matematik sinyalleri, CSV aç/aktar
ve kalıcılık. (Eski Çalışma Alanı sayfasının yerine; hub ve besleme aynı SignalHub/SignalFeed.)"""
import json
import os
import struct
import time

import can
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QMessageBox

from app.dbc import DbcDatabase
from app.signal_feed import SignalFeed
from app.signal_hub import SignalHub

DATA = os.path.join(os.path.dirname(__file__), "data")
RPM = "dbc:ENG_STATUS.rpm"


def _dbc():
    d = DbcDatabase()
    d.load(os.path.join(DATA, "sample.dbc"))
    return d


def _frame(rpm: int):
    return struct.pack("<HHB", rpm, 1250, 0) + b"\0" * 3


# ------------------------------------------------------------------ SignalFeed (Qt'siz)
def test_feed_decodes_only_active_dbc_signals_and_updates_map_when_active_set_changes():
    hub = SignalHub()
    feed = SignalFeed(hub)
    feed.set_dbc(_dbc())
    feed.on_can_frame(256, _frame(1500))
    assert RPM not in hub.active() and hub.get(RPM)[0].size == 0           # etkin değil: çözülmez
    hub.set_active([RPM])                                                   # on_active -> çözümleme tablosu yenilenir
    feed.on_can_frame(256, _frame(1500))
    feed.on_can_frame(256, _frame(1600))
    t, v = hub.get(RPM)
    assert list(v) == [1500.0, 1600.0]
    feed.on_can_frame(999, b"\0" * 8)                                       # tanımsız kimlik: sessizce yok sayılır
    feed.on_can_frame(256, b"\x01")                                         # bozuk (kısa) veri: çökmez
    assert hub.get(RPM)[1].size == 2


def test_feed_groups_list_sources():
    hub = SignalHub()
    feed = SignalFeed(hub, ["RPM", "PLA"])
    feed.set_dbc(_dbc())
    hub.define_derived("kare", {"kind": "scale", "src": RPM, "gain": 2.0, "offset": 0.0})
    titles = dict(feed.groups())
    assert "DBC sinyalleri (CAN)" in titles and RPM in titles["DBC sinyalleri (CAN)"]
    assert titles["Göstergeler"] == ["gauge:RPM", "gauge:PLA"] and "Girişler" not in titles       # giriş kaynağı kalktı
    assert titles["Matematik sinyalleri"] == ["math:kare"] and "İçe aktarılan kayıtlar" not in titles
    assert feed.all_signal_ids(["N_RPM"])[0] == "a2l:N_RPM"


def test_feed_without_dbc_has_no_dbc_group_and_ignores_frames():
    feed = SignalFeed(SignalHub())
    feed.on_can_frame(256, _frame(1))
    assert feed.groups() == []


# ------------------------------------------------------------------ Scope penceresi
@pytest.fixture
def ws(qapp, tmp_path):
    from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace
    w = ModasWorkspace(ModasSheetStore(str(tmp_path / "sheets.json")))
    w.feed = SignalFeed(w.hub)
    w.feed.set_dbc(_dbc())
    w.signal_groups = w.feed.groups
    w.show()
    yield w
    w.shutdown()


def test_scope_accepts_non_a2l_signals_but_only_a2l_labels_are_measured(ws):
    sc = ws.add_scope(["N_RPM"])
    assert sc.add_signals([RPM, "gauge:RPM"]) == 2
    assert sc.signals() == ["a2l:N_RPM", RPM, "gauge:RPM"]
    assert sc.labels() == ["N_RPM"] and ws.scope_labels() == ["N_RPM"]       # ölçüm turu yalnız A2L etiketlerini okur
    ws._on_scope_changed()
    assert RPM in ws.hub.active()
    ws.feed.on_can_frame(256, _frame(2100))
    assert list(ws.hub.get(RPM)[1]) == [2100.0]


def test_picker_lists_groups_excludes_taken_and_filters(qapp):
    from app.ui.modas.signal_picker import SignalPickerDialog
    groups = [("DBC", [RPM, "dbc:ENG_STATUS.tt2_c"]), ("Göstergeler", ["gauge:RPM"])]
    d = SignalPickerDialog(groups, already=[RPM])
    root = d.tree.topLevelItem(0)
    assert root.child(0).text(0).endswith("(grafikte)")
    assert not (root.child(0).flags() & Qt.ItemIsUserCheckable)                       # zaten grafikte: seçilemez
    root.child(1).setCheckState(0, Qt.Checked)
    d.tree.topLevelItem(1).child(0).setCheckState(0, Qt.Checked)
    assert d.selected() == ["dbc:ENG_STATUS.tt2_c", "gauge:RPM"]
    d.search.setText("tt2")
    assert d.tree.topLevelItem(1).isHidden() and not root.child(1).isHidden()
    assert d.selected() == ["dbc:ENG_STATUS.tt2_c"]                           # gizlenenler seçilmiş sayılmaz
    assert SignalPickerDialog([], parent=None).empty.isHidden() is False


def test_pick_signals_adds_selection_to_scope(ws, monkeypatch):
    from app.ui.modas import signal_picker
    monkeypatch.setattr(signal_picker.SignalPickerDialog, "exec", lambda self: QDialog.Accepted)
    monkeypatch.setattr(signal_picker.SignalPickerDialog, "selected", lambda self: [RPM, "dbc:ENG_STATUS.tt2_c"])
    sc = ws.add_scope([])
    assert ws.pick_signals(sc) == 2 and sc.signals() == [RPM, "dbc:ENG_STATUS.tt2_c"]
    assert {RPM, "dbc:ENG_STATUS.tt2_c"} <= ws.hub.active()


# ------------------------------------------------------------------ matematik sinyalleri
def _fake_math_dialog(monkeypatch, name, spec, accept=True):
    from app.ui import math_dialog
    monkeypatch.setattr(math_dialog.MathDialog, "exec", lambda self: QDialog.Accepted if accept else QDialog.Rejected)
    monkeypatch.setattr(math_dialog.MathDialog, "result_spec", lambda self: (name, spec))


def test_math_signal_define_edit_rename_delete(ws, monkeypatch):
    sc, sc2 = ws.add_scope([]), ws.add_scope([])
    sc.add_signals([RPM])
    _fake_math_dialog(monkeypatch, "rpm2", {"kind": "scale", "src": RPM, "gain": 2.0, "offset": 1.0})
    assert ws.edit_math(sc) is True
    assert "math:rpm2" in ws.hub.derived and "math:rpm2" in sc.signals()           # yeni sinyal çağıran Scope'a eklenir
    ws._on_scope_changed()
    ws.feed.on_can_frame(256, _frame(1000))
    assert list(ws.hub.get("math:rpm2")[1]) == [2001.0]
    sc2.add_signals(["math:rpm2"])                                                   # başka Scope da kullanıyor
    _fake_math_dialog(monkeypatch, "rpm3", {"kind": "scale", "src": RPM, "gain": 3.0, "offset": 0.0})
    assert ws.edit_math(sc, "math:rpm2") is True                                    # yeniden adlandırma: her yerde güncellenir
    assert "math:rpm2" not in ws.hub.derived and "math:rpm3" in sc.signals() and "math:rpm3" in sc2.signals()
    ws.delete_math("math:rpm3")
    assert "math:rpm3" not in ws.hub.derived and "math:rpm3" not in sc.signals() + sc2.signals()


def test_math_signal_duplicate_and_cycle_are_rejected(ws, monkeypatch):
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    sc = ws.add_scope([])
    _fake_math_dialog(monkeypatch, "a", {"kind": "scale", "src": RPM, "gain": 1.0, "offset": 0.0})
    assert ws.edit_math(sc) is True
    assert ws.edit_math(sc) is False and "zaten var" in warned[-1]                   # aynı ad
    _fake_math_dialog(monkeypatch, "b", {"kind": "scale", "src": "math:a", "gain": 1.0, "offset": 0.0})
    assert ws.edit_math(sc) is True
    _fake_math_dialog(monkeypatch, "a", {"kind": "scale", "src": "math:b", "gain": 1.0, "offset": 0.0})
    assert ws.edit_math(sc, "math:a") is False and "döngüsel" in warned[-1]          # a -> b -> a döngüsü
    assert ws.hub.derived["math:a"]["src"] == RPM                                    # tanım bozulmadı
    _fake_math_dialog(monkeypatch, "x", {"kind": "scale", "src": RPM}, accept=False)
    assert ws.edit_math(sc) is False and "math:x" not in ws.hub.derived


def test_math_menu_lists_edit_and_delete_entries(ws):
    sc = ws.add_scope([])
    ws.hub.define_derived("m1", {"kind": "scale", "src": RPM, "gain": 1.0, "offset": 0.0})
    sc._fill_math_menu()
    titles = [a.text() for a in sc._math_menu.actions()]
    assert titles == ["Yeni matematik sinyali…", "Düzenle", "Sil"]
    assert [a.text() for a in sc._math_menu.actions()[1].menu().actions()] == ["m1"]


# ------------------------------------------------------------------ CSV
def test_csv_export_and_open_roundtrip(ws, tmp_path, monkeypatch):
    sc = ws.add_scope([])
    sc.add_signals([RPM])
    ws._on_scope_changed()
    for rpm in (1000, 1100, 1200):
        ws.feed.on_can_frame(256, _frame(rpm))
        time.sleep(0.01)
    out = str(tmp_path / "kayit.csv")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out, "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    assert ws.export_csv() == 1 and "dbc:ENG_STATUS.rpm" in open(out, encoding="utf-8").read()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (out, "")))
    sc2 = ws.add_scope([])
    assert ws.open_csv(sc2) == 1
    assert len(sc2.signals()) == 1 and sc2.signals()[0].startswith("csv:kayit:")
    assert list(ws.hub.get(sc2.signals()[0])[1]) == [1000.0, 1100.0, 1200.0]


def test_csv_export_without_data_and_open_errors_are_reported_not_raised(ws, tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: seen.append("info")))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: seen.append("crit")))
    assert ws.export_csv() == 0 and seen == ["info"]                                 # veri yok: uyarı, dosya sorulmaz
    bad = tmp_path / "bos.csv"
    bad.write_text("a\n", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad), "")))
    assert ws.open_csv(ws.add_scope([])) == 0 and seen[-1] == "crit"
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", "")))
    assert ws.open_csv(ws.add_scope([])) == 0                                        # vazgeçildi


# ------------------------------------------------------------------ kalıcılık
def test_math_definitions_and_scope_signals_survive_restart(qapp, tmp_path):
    from app.ui.modas.workspace import ModasSheetStore, ModasWorkspace
    path = str(tmp_path / "sheets.json")
    w = ModasWorkspace(ModasSheetStore(path))
    sc = w.add_scope([])
    sc.add_signals([RPM])
    w.hub.define_derived("rpm2", {"kind": "scale", "src": RPM, "gain": 2.0, "offset": 0.0})
    sc.add_signals(["math:rpm2"])
    w._on_scope_changed()
    w.shutdown()
    saved = json.load(open(path, encoding="utf-8"))
    assert saved["math"]["math:rpm2"]["gain"] == 2.0
    w2 = ModasWorkspace(ModasSheetStore(path))
    assert "math:rpm2" in w2.hub.derived                                              # Scope'tan ÖNCE yüklenir
    scopes = w2.scope_windows()
    assert len(scopes) == 1 and scopes[0].signals() == [RPM, "math:rpm2"]
    assert {RPM, "math:rpm2"} <= w2.hub.active()
    w2.shutdown()


# ------------------------------------------------------------------ MainWindow bütünleşik
def test_main_window_routes_can_frames_gauges_and_inputs_into_scope_hub(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
        w.transmit_tab.dbc_loaded.emit()
        sc = w.modas_tab.add_scope([])
        sc.add_signals([RPM, "gauge:RPM"])
        w.modas_tab._on_scope_changed()
        w.connection.rx_queue.put_nowait(can.Message(arbitration_id=256, data=_frame(1800), is_extended_id=False,
                                                     timestamp=time.time()))
        w._drain_rx_queue()
        assert list(w.modas_tab.hub.get(RPM)[1]) == [1800.0]
        w.dashboard_tab.gauge_sample.emit("RPM", 3300.0)
        assert list(w.modas_tab.hub.get("gauge:RPM")[1]) == [3300.0]
        assert any(RPM in ids for _t, ids in w.modas_tab.signal_groups())
    finally:
        w.close()
