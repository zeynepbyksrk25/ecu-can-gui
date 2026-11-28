"""Tek rol: Mühendis. Operatör/Yönetici, rol seçimi ve yetki engelleri yoktur."""
import app.user_roles as ur


def test_only_one_role_constant_and_no_permission_helpers():
    assert ur.ROL_ADI == "Mühendis"
    assert not [n for n in dir(ur) if n.startswith("can_")] and not hasattr(ur, "Role")


def test_user_tab_has_only_a_user_name_and_emits_user_applied(qapp):
    from app.ui.user_tab import UserTab
    t = UserTab()
    assert not hasattr(t, "role_combo") and not hasattr(t, "role_applied")
    got = []
    t.user_applied.connect(got.append)
    t.user_edit.setText("Zeynep")
    t._on_apply_user()
    assert got == ["Zeynep"] and "Mühendis" in t.current_label.text()
    t.user_edit.setText("")
    t._on_apply_user()
    assert got[-1] == "bilinmeyen"


def test_main_window_shows_user_and_logs_with_the_single_role(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        assert not hasattr(w, "current_role") and not hasattr(w, "header_role_label")
        w.user_tab.user_edit.setText("Zeynep")
        w.user_tab._on_apply_user()
        assert w.current_user == "Zeynep" and "Zeynep" in w.header_user_label.text() and "Mühendis" in w.header_user_label.text()
        w._log_event("AYAR", "deneme")
        assert w.event_log.entries[-1].role == "Mühendis" and w.event_log.entries[-1].user == "Zeynep"
        # yetki engeli yok: ECU bağlı değilken bile yazma yolu "yetki yok" demez, yalnızca bağlantı nedenini söyler
        from app.ui.modas.windows import ValueWindow
        assert not hasattr(ValueWindow, "set_role")
    finally:
        w.close()
