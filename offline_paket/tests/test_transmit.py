import pytest

from app.bitpack import BitFieldError, pack_fields

DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 MSG1: 4 ECU
 SG_ Temp : 0|8@1+ (1,-40) [-40|215] "C" ECU
 SG_ Free : 8|8@1+ (1,0) [0|0] "" ECU
 SG_ Cnt : 16|8@1+ (1,0) [0|255] "" ECU
BO_ 512 MSG2: 2 ECU
 SG_ A : 0|16@1- (0.5,0) [0|0] "" ECU
BA_DEF_ SG_ "GenSigStartValue" FLOAT -1000 1000;
BA_DEF_DEF_ "GenSigStartValue" 0;
"""


@pytest.fixture
def dbc(tmp_path):
    from app.dbc import DbcDatabase
    p = tmp_path / "t.dbc"
    p.write_text(DBC)
    d = DbcDatabase()
    d.load(str(p))
    return d


# ---- DBC ----------------------------------------------------------------
@pytest.mark.parametrize("vals", [{"Free": 300}, {"Temp": 999}, {"Cnt": -1}])
def test_dbc_encode_errors_are_valueerror(dbc, vals):
    with pytest.raises(ValueError):
        dbc.encode("MSG1", vals)


def test_dbc_unknown_signal_rejected(dbc):
    with pytest.raises(ValueError, match="olmayan sinyal"):
        dbc.encode("MSG1", {"Nope": 1})


def test_unspecified_signals_do_not_default_to_minimum(dbc):
    # eskiden Temp varsayılanı minimum (-40 °C) idi; şimdi 0 °C (aralığa kırpılmış)
    _id, data, _ext = dbc.encode("MSG1", {})
    msg = dbc.get_message("MSG1")
    dec = msg.decode(data)
    assert dec["Temp"] == 0 and dec["Free"] == 0 and dec["Cnt"] == 0


def test_signal_limits_unbounded_uses_bit_width(dbc):
    from app.dbc import signal_limits
    msg = dbc.get_message("MSG1")
    free = next(s for s in msg.signals if s.name == "Free")
    assert signal_limits(free) == (0, 255)
    a = next(s for s in dbc.get_message("MSG2").signals if s.name == "A")
    assert signal_limits(a) == (-16384.0, 16383.5)


# ---- bitpack ------------------------------------------------------------
def test_bitpack_overlap_and_dlc():
    f = lambda n, s, l, v: {"name": n, "start": s, "length": l, "value": v}
    with pytest.raises(BitFieldError, match="çakış"):
        pack_fields([f("a", 0, 8, 1), f("b", 4, 8, 1)])
    assert pack_fields([f("a", 0, 8, 1)], 2) == b"\x01\x00"
    with pytest.raises(BitFieldError):
        pack_fields([f("a", 8, 8, 1)], 1)             # DLC 1'e sığmaz
    with pytest.raises(BitFieldError):
        pack_fields([f("a", 0, 8, 1.5)])
    with pytest.raises(BitFieldError):
        pack_fields([], 9)


def test_scheduler_validation():
    import can
    from app.scheduler import PeriodicManager
    bus = can.Bus(interface="virtual", channel="sch")
    try:
        pm = PeriodicManager(bus)
        for args in [(0x100, b"\x00", False, 0), (0x100, b"\x00", False, 10**6),
                     (0x100, bytes(9), False, 10), (0x800, b"\x00", False, 10)]:
            with pytest.raises(ValueError):
                pm.start("r", *args)
        pm.start("r", 0x100, b"\x01", False, 50)
        assert pm.is_running("r")
        pm.stop_all()
    finally:
        bus.shutdown()


# ---- UI: periyodik satırlar -----------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_deleting_row_keeps_widgets_bound_to_correct_row(qapp):
    from PySide6.QtWidgets import QMessageBox
    from app.ui.transmit_tab import TransmitTab
    t = TransmitTab()
    started, stopped = [], []
    t.periodic_start_requested.connect(lambda k, i, d, e, p: started.append((k, i)))
    t.periodic_stop_requested.connect(stopped.append)
    for n in range(3):
        t.add_row()
        t.periodic_table.cellWidget(n, 2).setText(f"{0x100 + n:X}")
    keys = [t._row_key(r) for r in range(3)]
    t.periodic_table.setCurrentCell(0, 0)
    t._remove_selected_row()
    assert t.periodic_table.rowCount() == 2
    # eski satır 1 şimdi 0. satırda; onay kutusu KENDİ satırını başlatmalı
    t.periodic_table.cellWidget(0, 0).setChecked(True)
    assert started == [(keys[1], 0x101)]
    t.periodic_table.cellWidget(1, 0).setChecked(True)
    assert started[-1] == (keys[2], 0x102)
    t.periodic_table.cellWidget(0, 0).setChecked(False)
    assert stopped == [keys[1]]


def test_failed_start_unchecks_row_and_dlc_applied(qapp):
    from app.ui.transmit_tab import TransmitTab
    t = TransmitTab()
    t.add_row()
    t.periodic_table.cellWidget(0, 2).setText("123")
    # MainWindow reddederse (rol/bağlantı) satır "çalışıyor" görünmemeli
    t.periodic_start_requested.connect(lambda k, *a: t.mark_start_failed(k))
    t.periodic_table.cellWidget(0, 0).setChecked(True)
    assert not t.periodic_table.cellWidget(0, 0).isChecked()
    assert t.periodic_table.cellWidget(0, 6).text() == "Durduruldu"
    # DLC
    got = []
    t.periodic_start_requested.disconnect()
    t.periodic_start_requested.connect(lambda k, i, d, e, p: got.append(d))
    t.periodic_table.cellWidget(0, 4).findChild(type(t.manual_dlc_spin), "dlc_spin").setValue(2)
    t.periodic_table.cellWidget(0, 0).setChecked(True)
    assert got and len(got[0]) == 2


def test_operator_cannot_transmit(qapp, tmp_path, monkeypatch):
    import app.paths as paths
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    monkeypatch.setattr(paths, "_cached", None)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.Ok)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    sent = []
    w.connection.send = lambda *a, **k: sent.append(a)
    w._on_manual_send(0x100, b"\x01", False)
    assert sent == []                                  # Operatör: engellendi
    from app.user_roles import Role
    w._on_role_applied("test", Role.ENGINEER.value)
    w._on_manual_send(0x100, b"\x01", False)
    assert len(sent) == 1
    assert any(e.category == "GÖNDERİM" for e in w.event_log.entries)
    w.close()


# ---- logger / monitor / wheel -------------------------------------------------
def test_logger_start_twice_unique_files_and_error(tmp_path):
    from app.logger import CanLogger
    lg = CanLogger()
    p1 = lg.start(str(tmp_path))
    p2 = lg.start(str(tmp_path))                 # aynı saniye: üzerine yazmamalı
    assert p1 != p2
    for i in range(450):
        lg.write(1.0 + i, 0x100, 1, b"\x01", False)
    assert len(open(p2).read().splitlines()) > 400   # periyodik flush: diskte
    lg.stop()
    with pytest.raises(OSError):
        lg.start("   ")


def test_logger_write_error_stops_without_exception(tmp_path):
    from app.logger import CanLogger
    lg = CanLogger()
    lg.start(str(tmp_path))
    lg._file.close()                              # sürücü kapandı gibi
    lg._writer = type("W", (), {"writerow": lambda self, r: (_ for _ in ()).throw(OSError("disk dolu"))})()
    lg.write(1.0, 0x100, 1, b"\x01", False)
    assert lg.error == "disk dolu" and not lg.is_active


def test_monitor_separates_extended_and_resets_name_filter(qapp, dbc):
    import can
    from app.ui.monitor_tab import MonitorTab
    m = MonitorTab()
    m.dbc = dbc
    m._name_filter = "ESKI"
    m.refresh_dbc_messages()
    assert m._name_filter is None
    for ext in (False, True):
        m.add_message(can.Message(arbitration_id=0x123, data=b"\x00", is_extended_id=ext, timestamp=1.0))
    assert m.table.rowCount() == 2


def test_wheel_ignored_without_focus(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QDoubleSpinBox
    from app.ui.noscroll import no_wheel
    sp = no_wheel(QDoubleSpinBox())
    sp.setRange(0, 100)
    sp.setValue(10)
    ev = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120), Qt.NoButton,
                     Qt.NoModifier, Qt.NoScrollPhase, False)
    qapp.sendEvent(sp, ev)
    assert sp.value() == 10
