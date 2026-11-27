"""Kalibrasyon değişiklik takibi: ok/miktar göstergesi, geçmiş, geri alma ve başlangıca dönüş (Aşama 1)."""
import json


from app.history import CalibrationHistory
from tests import test_dashboard_e2e as e2e

win = e2e.win          # MainWindow + CCP simülatörü düzeneği (Worksheets yazım testleri için)
ccp = e2e.ccp


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


# ---- Worksheets (Modas) yazımları ortak değişiklik takibine, geçmişe ve kayda bağlıdır -----------------------------
def _fuel(win):
    win.modas_tab.set_summary(win.a2l_tab.db.summary)
    obj = next(c for c in win.a2l_tab.db.summary.characteristics if c.name == "clbc_Fuel_pump_gain")
    return obj, win.modas_tab.add_label(obj.name)


def test_worksheet_write_feeds_tracker_history_and_arrow(win, ccp):
    from app.user_roles import Role
    win.current_role = Role.ENGINEER
    win._modas_sync_permissions()
    obj, w = _fuel(win)
    win._modas_write_value(w, "21")
    st = win.change_tracker.state(obj.name)
    assert st.last_write_ok is True and st.last_new == 21.0 and st.baseline is not None
    entry = win.calibration_history.entries[-1]
    assert entry.object_name == obj.name and entry.write_ok and entry.source == "worksheets"
    assert w.change_state == "applied" and w.change_icon.property("arrow") in ("↑", "↓")   # yön ok simgesiyle
    assert w.change_text.text() and "↑" not in w.change_text.text() and "↓" not in w.change_text.text()   # çift ok yok
    assert w.unit_label.text() == (obj.unit or "")
    assert "Son değişim" in w.edit.toolTip()


def test_worksheet_failed_write_is_recorded_as_failed_in_history_and_tracker(win, ccp, monkeypatch):
    from app.user_roles import Role
    win.current_role = Role.ENGINEER
    win._modas_sync_permissions()
    obj, w = _fuel(win)
    win._modas_read_window(w)

    def boom(*a, **k):
        raise RuntimeError("ECU yazmayı reddetti")
    monkeypatch.setattr(win.ccp_client, "write_memory", boom)
    win._modas_write_value(w, "30")
    entry = win.calibration_history.entries[-1]
    assert entry.object_name == obj.name and entry.write_ok is False and entry.source == "worksheets"
    assert win.change_tracker.state(obj.name).last_write_ok is False
    assert w.change_state == "failed" and not w.change_icon.isVisible()      # başarısız yazma ok göstermez
