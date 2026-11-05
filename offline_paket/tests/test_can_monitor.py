import csv
import os
import time

import can
import pytest
from PySide6.QtWidgets import QPushButton

DATA = os.path.join(os.path.dirname(__file__), "data")


def _msg(i, data=b"\x01\x02", t=None, ext=False):
    return can.Message(arbitration_id=i, data=data, is_extended_id=ext, timestamp=t if t is not None else time.time())


# ---------------------------------------------------------------- bağlantı şeridi
def test_no_interface_or_channel_widgets_and_pcan_defaults(qapp, monkeypatch):
    monkeypatch.delenv("OPENECU_CAN_INTERFACE", raising=False)
    from app.ui.can_monitor_tab import CanMonitorTab
    tab = CanMonitorTab()
    c = tab.connection
    assert not hasattr(c, "interface_combo") and not hasattr(c, "channel_edit")
    assert (c.current_interface(), c.current_channel()) == ("pcan", "PCAN_USBBUS1")
    texts = [b.text() for b in tab.findChildren(QPushButton)]
    assert not any("Gelişmiş" in t for t in texts)
    assert not c.adapter_combo.isVisibleTo(tab)


def test_adapter_picker_only_with_multiple_pcan_adapters(qapp, monkeypatch):
    from app.ui import connection_tab as ct
    monkeypatch.delenv("OPENECU_CAN_INTERFACE", raising=False)
    monkeypatch.setattr(ct, "detect_pcan_channels", lambda: ["PCAN_USBBUS1", "PCAN_USBBUS2"])
    c = ct.ConnectionTab()
    c.show()
    assert c.adapter_combo.isVisible() and c.adapter_combo.count() == 2
    c.adapter_combo.setCurrentIndex(1)
    assert c.current_channel() == "PCAN_USBBUS2"
    monkeypatch.setattr(ct, "detect_pcan_channels", lambda: ["PCAN_USBBUS1"])
    c2 = ct.ConnectionTab()
    c2.show()
    assert not c2.adapter_combo.isVisible()


def test_env_override_for_offline_development_and_legacy_profile_migration(qapp, monkeypatch):
    from app.ui import connection_tab as ct
    monkeypatch.delenv("OPENECU_CAN_INTERFACE", raising=False)
    assert ct.normalize_interface("virtual", "test") == ("pcan", "PCAN_USBBUS1")
    assert ct.normalize_interface("udp_multicast", "239.0.0.1") == ("pcan", "PCAN_USBBUS1")
    assert ct.normalize_interface("pcan", "PCAN_USBBUS2") == ("pcan", "PCAN_USBBUS2")
    monkeypatch.setenv("OPENECU_CAN_INTERFACE", "virtual")
    assert ct.default_interface() == "virtual"
    assert ct.normalize_interface("pcan", "x") == ("virtual", "test")


def test_profile_apply_converts_virtual_to_pcan_and_sets_bitrate(qapp, monkeypatch):
    from app.ui import connection_tab as ct
    monkeypatch.delenv("OPENECU_CAN_INTERFACE", raising=False)
    c = ct.ConnectionTab()
    c.apply_profile_values("virtual", "test", 250_000)
    assert (c.current_interface(), c.current_channel(), c.current_bitrate()) == ("pcan", "PCAN_USBBUS1", 250_000)


def test_baudrate_and_auto_connect_persist(qapp, tmp_path):
    from app.ui.connection_tab import ConnectionTab
    path = str(tmp_path / "can.json")
    a = ConnectionTab()
    a.attach_settings(path)
    a.baudrate_combo.setCurrentIndex(a.baudrate_combo.findData(250_000))
    a.auto_connect_check.setChecked(True)
    b = ConnectionTab()
    b.attach_settings(path)
    assert b.current_bitrate() == 250_000 and b.auto_connect_enabled()
    assert b.baudrate_combo.findData(100_000) >= 0 and b.baudrate_combo.findData(800_000) >= 0


def test_profile_defaults_are_pcan():
    from app.profiles import ConfigProfile
    p = ConfigProfile(name="x")
    assert (p.interface, p.channel) == ("pcan", "PCAN_USBBUS1")


# ---------------------------------------------------------------- izleme tablosu
@pytest.fixture
def mon(qapp):
    from app.dbc import DbcDatabase
    from app.ui.monitor_tab import MonitorTab
    m = MonitorTab()
    m.dbc = DbcDatabase()
    m.dbc.load(os.path.join(DATA, "sample.dbc"))
    m.refresh_dbc_messages()
    return m


def test_rx_and_tx_with_same_id_get_separate_rows(mon):
    mon.add_message(_msg(0x100), "RX")
    mon.add_message(_msg(0x100), "TX")
    mon.add_message(_msg(0x100), "RX")
    assert len(mon.model.rows) == 2
    rows = {r.direction: r for r in mon.model.rows}
    assert rows["RX"].count == 2 and rows["TX"].count == 1


def test_period_is_estimated_between_messages(mon):
    t = 1000.0
    for i in range(10):
        mon.add_message(_msg(0x200, t=t + i * 0.1), "RX")
    r = mon.model.rows[0]
    assert r.period_ms == pytest.approx(100.0, rel=0.01)


def test_filters_apply_to_existing_rows(mon):
    for i in (0x100, 0x1A5, 0x400):
        mon.add_message(_msg(i), "RX")
    mon.add_message(_msg(0x400), "TX")
    assert mon.proxy.rowCount() == 4
    mon.direction_combo.setCurrentText("TX")
    assert mon.proxy.rowCount() == 1
    mon.direction_combo.setCurrentText("Tümü")
    mon.filter_edit.setText("1A")
    assert mon.proxy.rowCount() == 1 and mon.proxy.data(mon.proxy.index(0, 1)) == "0x1A5"
    mon.filter_edit.setText("")
    mon.name_filter_combo.setCurrentText("ENG_STATUS")
    assert mon.proxy.rowCount() == 1
    mon.name_filter_combo.setCurrentText("Tümü")
    assert mon.proxy.rowCount() == 4


def test_signals_have_units_and_detail_panel_lists_raw_values(mon):
    data = mon.dbc.encode("ENG_STATUS", {"rpm": 4520, "tt2_c": 38.0, "tt2_fault": 0})[1]
    mon.add_message(_msg(0x100, data), "RX")
    r = mon.model.rows[0]
    text = mon.model.sig_text(r)
    assert "rpm=4520 rpm" in text and "degC" in text
    mon.table.selectRow(0)
    mon._refresh_detail()
    assert mon.detail.rowCount() == 3
    assert [mon.detail.item(0, c).text() for c in range(4)] == ["rpm", "4520", "rpm", "4520"]


def test_hex_decimal_toggle_and_pause_keeps_counting_stats(mon):
    mon.add_message(_msg(0x100, b"\xff\x10"), "RX")
    idx_id, idx_data = mon.model.index(0, 1), mon.model.index(0, 4)
    assert mon.model.data(idx_id) == "0x100" and mon.model.data(idx_data) == "FF 10"
    mon.hex_check.setChecked(False)
    assert mon.model.data(idx_id) == "256" and mon.model.data(idx_data) == "255 16"
    mon.pause_button.setChecked(True)
    mon.add_message(_msg(0x100), "RX")
    assert mon.model.rows[0].count == 1 and mon.stats.total_rx == 2


def test_clear_resets_everything(mon):
    mon.add_message(_msg(0x100), "RX")
    mon.clear()
    assert mon.model.rowCount() == 0 and mon.stats.total_rx == 0


def test_high_rate_updates_are_cheap(mon):
    t0 = time.perf_counter()
    for i in range(6000):
        mon.add_message(_msg(0x100 + i % 60, bytes([i % 256] * 8)), "RX")
    mon._flush()
    assert time.perf_counter() - t0 < 1.5
    assert len(mon.model.rows) == 60


# ---------------------------------------------------------------- gönderim
@pytest.fixture
def tx(qapp):
    from app.ui.transmit_tab import TransmitTab
    t = TransmitTab()
    t.dbc.load(os.path.join(DATA, "sample.dbc"))
    t.started = []
    t.periodic_start_requested.connect(lambda *a: t.started.append(a))
    t.stopped = []
    t.periodic_stop_requested.connect(lambda k: t.stopped.append(k))
    return t


def test_periodic_rows_stay_bound_after_deleting_a_middle_row(tx):
    for _ in range(3):
        tx.add_row()
    keys = [tx._row_key(r) for r in range(3)]
    tx.periodic_table.setCurrentCell(1, 0)
    tx._remove_selected_row()
    assert tx.periodic_table.rowCount() == 2
    tx.periodic_table.cellWidget(1, 0).setChecked(True)          # eskiden 3. satırdı
    assert [s[0] for s in tx.started] == [keys[2]]
    assert tx.periodic_table.cellWidget(0, 6).text() == "Durduruldu"
    assert tx.periodic_table.cellWidget(1, 6).text() == "Çalışıyor"
    tx.periodic_table.cellWidget(1, 0).setChecked(False)
    assert tx.stopped == [keys[2]]


def test_running_dbc_row_is_updated_when_signal_values_change(tx):
    tx.add_row()
    tx.periodic_table.cellWidget(0, 1).setCurrentText("DBC mesajı")
    tx.periodic_table.cellWidget(0, 2).setCurrentText("OVERRIDE")
    key = tx._row_key(0)
    tx._periodic_state[key]["values"] = {"pump_dc": 10.0}
    tx.periodic_table.cellWidget(0, 0).setChecked(True)
    first = tx.started[-1]
    tx._periodic_state[key]["values"] = {"pump_dc": 50.0}
    tx._restart_if_running(0)
    second = tx.started[-1]
    assert second[0] == key and second[2] != first[2]
    assert tx.dbc.get_message("OVERRIDE").decode(second[2])["pump_dc"] == pytest.approx(50.0, abs=0.1)
    assert "güncellendi" in tx.periodic_table.cellWidget(0, 6).text()


def test_manual_dbc_note_lists_signals_that_go_with_defaults(tx):
    from app.ui.transmit_tab import MODE_DBC
    tx.manual_message_combo.addItems(tx.dbc.message_names())     # DBC diyaloğunun yaptığı gibi
    tx.manual_mode_combo.setCurrentText(MODE_DBC)
    tx.manual_message_combo.setCurrentText("OVERRIDE")
    assert "4 sinyal girilmedi" in tx.manual_note.text()
    tx._on_manual_signal_picked(tx.manual_signal_list.item(0))
    assert "3 sinyal girilmedi" in tx.manual_note.text()


def test_dbc_load_button_lives_in_monitor_card_not_in_transmit(qapp):
    from app.ui.can_monitor_tab import CanMonitorTab
    tab = CanMonitorTab()
    assert tab.dbc_button.text().startswith("DBC Yükle")
    assert tab.transmit.tabs.tabText(0) == "Manuel" and tab.transmit.tabs.tabText(1) == "Periyodik"
    tab.transmit.dbc.load(os.path.join(DATA, "sample.dbc"))
    tab.transmit.dbc_loaded.emit()
    assert "sample.dbc" in tab.dbc_chip.text() and "4 mesaj" in tab.dbc_chip.text()


# ---------------------------------------------------------------- log
def test_log_records_tx_and_rx_with_direction_and_message_name(qapp, tmp_path):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    w._on_log_start(str(tmp_path))
    w.monitor_tab.add_message(_msg(0x100, b"\x01" * 8, t=1.0), "RX")
    w.monitor_tab.add_message(_msg(0x400, b"\x02" * 8, t=2.0), "TX")
    w.monitor_tab.add_message(_msg(0x7FF, b"\x03", t=3.0), "RX")
    w.can_logger.stop()
    path = next(tmp_path.glob("can_log_*.csv"))
    rows = list(csv.reader(path.read_text(encoding="utf-8").splitlines()))
    assert rows[0] == ["timestamp_ms", "direction", "can_id_hex", "message", "dlc", "data_hex", "extended"]
    assert [(r[1], r[2], r[3]) for r in rows[1:]] == [("RX", "100", "ENG_STATUS"), ("TX", "400", "AIRCRAFT"), ("RX", "7FF", "")]
    w.close()


def test_log_records_even_while_monitor_is_paused(qapp, tmp_path):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w._on_log_start(str(tmp_path))
    w.monitor_tab.pause_button.setChecked(True)
    w.monitor_tab.add_message(_msg(0x100), "RX")
    w.can_logger.stop()
    path = next(tmp_path.glob("can_log_*.csv"))
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2
    w.close()


def test_live_roundtrip_over_virtual_bus_with_status_strip(qapp):
    """Bağlan → trafik al → izlemede görünür → bağlantıyı kes (donanımsız geliştirme arayüzüyle)."""
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w._on_connect("virtual", "ecu-live-test", 500_000)
    assert w.connection_tab.disconnect_button.isEnabled()
    assert "Bağlı" in w.connection_tab.status_label.text()
    other = can.Bus(interface="virtual", channel="ecu-live-test")
    try:
        other.send(can.Message(arbitration_id=0x123, data=b"\x01\x02", is_extended_id=False))
        deadline = time.time() + 2.0
        while time.time() < deadline and not w.monitor_tab.model.rows:
            qapp.processEvents()
            w._drain_rx_queue()
            time.sleep(0.02)
        assert [r.can_id for r in w.monitor_tab.model.rows] == [0x123]
    finally:
        other.shutdown()
        w._on_disconnect()
    assert w.connection_tab.status_label.text() == "Bağlı değil"
    w.close()
