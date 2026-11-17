"""Kalibrasyon > Parametre Listesi: sürekli canlı okuma + Enter ile anında yazma + doğrulama."""
import itertools
import os
import struct
import time

import can
import pytest
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QAbstractItemDelegate, QLineEdit, QPushButton

from app.ccp import worker as cw
from app.ccp.simulator import CCPSlaveSimulator
from app.ccp.worker import ONLINE
from app.ui import watch_tab as wt
from app.user_roles import Role

DATA = os.path.join(os.path.dirname(__file__), "data")
_ch = itertools.count()


def make_entry(name="x", addr=0x1000):
    return wt.WatchEntry(name=name, kind="manual", address=addr, datatype="UWORD", unit="rpm",
                         read_only=False, byte_order="MSB_FIRST")


@pytest.fixture
def tab(qapp):
    t = wt.WatchTab()
    t.add_manual_entry(make_entry())
    return t


def test_no_manual_read_or_poll_buttons_and_reading_is_automatic(tab):
    texts = [b.text() for b in tab.findChildren(QPushButton)]
    assert "Şimdi Oku" not in texts and not any("Sürekli oku" in t for t in texts)
    assert not hasattr(tab, "read_button") and not hasattr(tab, "poll_checkbox")
    assert not tab.is_polling()
    tab.set_connected(True)
    assert tab.is_polling()
    reads = []
    tab.read_requested.connect(lambda: reads.append(1))
    tab._on_poll_tick()
    assert reads == [1]
    tab.set_connected(False)
    assert not tab.is_polling()


def test_enter_writes_immediately_without_extra_buttons(tab):
    texts = [b.text() for b in tab.findChildren(QPushButton)]
    assert not any("RAM'e Yaz" in t for t in texts)
    got = []
    tab.write_requested.connect(lambda rows: got.append(rows))
    item = tab.table.item(0, wt.COL_VALUE)
    item.setText("2500")                       # hücre düzenleme onayı (Enter) = itemChanged
    assert got == [[0]] and tab.pending_text(0) == "2500"


def test_invalid_number_is_not_sent(tab):
    got = []
    tab.write_requested.connect(lambda rows: got.append(rows))
    tab.table.item(0, wt.COL_VALUE).setText("abc")
    assert got == [] and "geçersiz" in tab.status_label.text()


def test_losing_focus_cancels_editing_instead_of_writing(tab):
    delegate = tab.table.itemDelegateForColumn(wt.COL_VALUE)
    editor = QLineEdit(tab)
    hints = []
    delegate.closeEditor.connect(lambda ed, hint: hints.append(hint))
    handled = delegate.eventFilter(editor, QEvent(QEvent.FocusOut))
    assert handled is True and hints == [QAbstractItemDelegate.RevertModelCache]


def test_live_updates_do_not_overwrite_the_cell_being_edited(tab):
    tab.set_connected(True)
    tab.set_row_value(0, b"\x00\x0a", 10)
    item = tab.table.item(0, wt.COL_VALUE)
    assert item.text() == "10"
    tab.table.setCurrentCell(0, wt.COL_VALUE)
    tab.table.editItem(item)
    assert tab._is_editing(0)
    tab.set_row_value(0, b"\x00\x14", 20)      # canlı değer değişti, kullanıcı yazıyor
    assert item.text() == "10"
    tab.table.closePersistentEditor(item)


def test_write_is_verified_by_reading_back(tab):
    tab.set_connected(True)
    tab._entries[0].pending_text = "2500"
    tab.commit_written(0, 2500)
    assert tab._entries[0].verify_raw == (2500).to_bytes(2, "big")
    tab.set_row_value(0, (2500).to_bytes(2, "big"), 2500)
    assert "doğrulandı" in tab.status_label.text()
    assert tab._entries[0].flash_until > time.monotonic()
    assert tab._entries[0].verify_raw is None


def test_mismatch_after_deadline_is_reported(tab):
    tab.set_connected(True)
    tab.commit_written(0, 2500)
    tab._entries[0].verify_deadline = time.monotonic() - 0.1
    tab.set_row_value(0, (1000).to_bytes(2, "big"), 1000)       # ECU eski değere döndü
    assert "yazıldı ama ECU" in tab.status_label.text()


def test_live_state_label_follows_session_state(tab):
    tab.set_live_state("lost", "ECU YOK — CCP yeniden bağlanıyor")
    assert "ECU YOK" in tab.live_label.text()
    tab.set_live_state("online", "CCP çevrimiçi")
    assert "çevrimiçi" in tab.live_label.text()


# ---------------------------------------------------------------- uçtan uca (simülatör)
@pytest.fixture
def live_window(qapp, monkeypatch):
    from app.ui.main_window import MainWindow
    monkeypatch.setattr(cw, "SHORT_TIMEOUT_S", 0.08)
    monkeypatch.setattr(cw, "LOST_PROBE_S", 0.15)
    monkeypatch.setattr(cw, "BACKOFF", (0.05, 0.1, 0.2))
    w = MainWindow()
    w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
    w._on_dashboard_sources_changed()
    w.a2l_tab.a2l_loaded.emit()
    channel = f"watch-live-{next(_ch)}"
    w._on_connect("virtual", channel, 500_000)
    bus = can.Bus(interface="virtual", channel=channel)
    ecu = CCPSlaveSimulator(bus, 0x6F9, 0x6F8)
    ecu.strict_session = True
    ecu.start()
    summary = w.a2l_tab.db.summary
    obj = next(m for m in summary.measurements if m.name == "clbc_Fuel_pump_dc_perc")
    ecu.write_memory_bytes(obj.address, struct.pack("<f", 12.5))
    w.watch_tab.add_a2l_objects([("measurement", obj)])
    w.watch_tab._entries[0].read_only = False            # ayarlanabilir parametre gibi davran
    w.watch_tab._render_row(0)
    w.current_role = Role.ENGINEER

    def pump():
        qapp.processEvents()
        w._on_ccp_events()
    yield w, ecu, obj, pump
    w._on_disconnect()
    ecu.stop()
    bus.shutdown()
    w.close()


def wait_for(cond, timeout=6.0, pump=None):
    end = time.time() + timeout
    while time.time() < end:
        if pump:
            pump()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def test_values_stream_without_any_button_and_enter_writes_and_verifies(live_window):
    w, ecu, obj, pump = live_window
    tab = w.watch_tab
    assert wait_for(lambda: w.ccp_session.state == ONLINE, pump=pump)
    # 1) hiçbir düğmeye basmadan canlı değer akıyor
    assert wait_for(lambda: tab.table.item(0, wt.COL_VALUE).text() == "12.5", pump=pump)
    # 2) ECU tarafında değer değişince ekran kendiliğinden güncelleniyor
    ecu.write_memory_bytes(obj.address, struct.pack("<f", 13.25))
    assert wait_for(lambda: tab.table.item(0, wt.COL_VALUE).text() == "13.25", pump=pump)
    # 3) değer hücresine yazıp Enter = anında yazılır ve ECU'dan doğrulanır
    tab.table.item(0, wt.COL_VALUE).setText("40")
    assert struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == 40.0
    assert wait_for(lambda: "doğrulandı" in tab.status_label.text(), pump=pump)
    assert tab.table.item(0, wt.COL_VALUE).text() == "40"


def test_operator_cannot_write_and_cell_returns_to_live_value(live_window):
    w, ecu, obj, pump = live_window
    tab = w.watch_tab
    assert wait_for(lambda: tab.table.item(0, wt.COL_VALUE).text() == "12.5", pump=pump)
    w.current_role = Role.OPERATOR
    tab.table.item(0, wt.COL_VALUE).setText("99")
    assert "Yetki yok" in tab.status_label.text()
    assert tab.pending_text(0) is None
    assert wait_for(lambda: tab.table.item(0, wt.COL_VALUE).text() == "12.5", pump=pump)
    assert struct.unpack("<f", ecu.read_memory_bytes(obj.address, 4))[0] == 12.5


def test_watch_rows_show_ecu_yok_quickly_and_recover_after_power_cycle(live_window):
    w, ecu, obj, pump = live_window
    tab = w.watch_tab
    assert wait_for(lambda: tab.table.item(0, wt.COL_VALUE).text() == "12.5", pump=pump)
    ecu.power_off()
    assert wait_for(lambda: "ECU YOK" in tab.live_label.text(), pump=pump)
    t0 = time.perf_counter()
    w._on_watch_read()
    assert time.perf_counter() - t0 < 0.05
    assert tab._entries[0].error is not None
    ecu.power_on()
    assert wait_for(lambda: tab._entries[0].error is None and
                    tab.table.item(0, wt.COL_VALUE).text() == "12.5", pump=pump)
    assert "çevrimiçi" in tab.live_label.text()


# ---------------------------------------------------------------- değer girişi (ölçüm + rol)
def _a2l_tab_with_objects(qapp):
    from app.a2l import A2LDatabase
    db = A2LDatabase()
    summary = db.load(os.path.join(DATA, "sample.a2l"))
    t = wt.WatchTab()
    t.a2l_db = db
    meas = next(m for m in summary.measurements if m.name == "clbc_Fuel_pump_dc_perc")
    char = next(c for c in summary.characteristics if c.name == "clbc_Fuel_pump_gain")
    t.add_a2l_objects([("measurement", meas), ("characteristic", char)])
    return t


def test_a2l_measurement_rows_accept_typed_values_like_calibration_parameters(qapp):
    """Eskiden A2L'den eklenen ölçümler zorla salt-okunurdu: hiçbirine değer girilemiyordu."""
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    t = _a2l_tab_with_objects(qapp)
    t.resize(1200, 400)
    t.show()
    got = []
    t.write_requested.connect(lambda rows: got.append(list(rows)))
    for row in (0, 1):                                              # 0: ölçüm, 1: karakteristik
        item = t.table.item(row, wt.COL_VALUE)
        assert item.flags() & Qt.ItemIsEditable, f"satır {row} düzenlenemiyor"
        idx = t.table.model().index(row, wt.COL_VALUE)
        t.table.setCurrentIndex(idx)
        t.table.edit(idx)
        editor = t.table.viewport().focusWidget()
        QTest.keyClicks(editor, "42.5")
        QTest.keyClick(editor, Qt.Key_Return)
        QTest.qWait(50)                                              # düzenleyici kapansın, sonra sıradaki satır
    assert got == [[0], [1]]                                        # gerçek klavye girişi iki satırı da yazdırdı
    assert t.pending_text(0) == "42.5" and t.pending_text(1) == "42.5"
    assert "ölçüm değişkeni" in t.table.item(0, wt.COL_NAME).toolTip()


def test_measurement_rows_stay_writable_after_the_list_is_saved_and_reloaded(qapp, tmp_path):
    from PySide6.QtCore import Qt
    t = _a2l_tab_with_objects(qapp)
    t.set_storage_path(str(tmp_path / "w.json"))
    t._save()
    t2 = wt.WatchTab()
    t2.a2l_db = t.a2l_db
    t2.set_storage_path(str(tmp_path / "w.json"))
    t2.refresh_objects()
    assert t2.table.item(0, wt.COL_VALUE).flags() & Qt.ItemIsEditable


def test_operator_role_locks_value_cells_and_says_why(qapp):
    from PySide6.QtCore import Qt
    t = _a2l_tab_with_objects(qapp)
    t.set_write_allowed(False)
    assert not t.role_hint.isHidden() and "Mühendis" in t.role_hint.text()
    assert not t.table.item(1, wt.COL_VALUE).flags() & Qt.ItemIsEditable
    t.set_write_allowed(True)
    assert t.role_hint.isHidden() and t.table.item(1, wt.COL_VALUE).flags() & Qt.ItemIsEditable


def test_main_window_follows_role_for_the_watch_list(live_window):
    from PySide6.QtCore import Qt
    w, _ecu, _obj, _pump = live_window
    w._on_role_applied("test", Role.OPERATOR.value)
    assert not w.watch_tab.table.item(0, wt.COL_VALUE).flags() & Qt.ItemIsEditable
    w._on_role_applied("test", Role.ENGINEER.value)
    assert w.watch_tab.table.item(0, wt.COL_VALUE).flags() & Qt.ItemIsEditable
