"""Tanılama ve Oturum sayfasındaki tek olay günlüğü: süzgeç ve birleşik sayfa."""
from app.eventlog import EventLog


def test_event_log_table_filters_errors(qapp):
    from app.ui.event_log_table import EventLogTable
    log = EventLog()
    log.add("CCP", "Bağlandı", user="u", role="Operatör")
    log.add("HATA", "CAN bus-off", user="u", role="Operatör")
    log.add("OTURUM", "Oturum başladı", user="u", role="Operatör")
    t = EventLogTable()
    t.set_entries(log.entries)
    assert t.table.rowCount() == 3 and t.error_count == 1
    t.set_errors_only(True)
    assert t.table.rowCount() == 1 and t.table.item(0, 3).text() == "CAN bus-off"
    assert t.btn_errors.isChecked() and not t.btn_all.isChecked()
    t.set_errors_only(False)
    assert t.table.rowCount() == 3


def test_log_event_reaches_merged_session_log(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w._log_event("HATA", "deneme hatası")
    s = w.session_tab
    assert s is w.tanilama_tab.session
    assert s.log_table.error_count >= 1
    s.log_table.set_errors_only(True)
    assert any(s.table.item(r, 3).text() == "deneme hatası" for r in range(s.table.rowCount()))
    w.close()
