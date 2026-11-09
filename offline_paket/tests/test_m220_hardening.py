"""Gerçek kullanım sağlamlaştırması: (1) Ana Sayfa + Kontrol Paneli aynı CAN mesajını birbirinin üstüne
yazmaz, (2) güvenlik komutları (Acil Durdurma/Durdur) kare serisi + iletişim yeniden denemesi,
(3) Kontrol Paneli görünümü kaydedilmemiş değişikliği gösterir ve kaybetmez."""
import os

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QInputDialog, QMessageBox

from app.ccp import protocol as ccp_protocol
from app.dashboard_config import SOURCE_A2L, SOURCE_CAN, Binding, DashboardConfig, MotorCommand

DATA = os.path.join(os.path.dirname(__file__), "data")


@pytest.fixture
def win(qapp, monkeypatch):
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Yes))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: QMessageBox.Ok))
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    w.a2l_tab.db.load(os.path.join(DATA, "sample.a2l"))
    w._on_dashboard_sources_changed()
    yield w
    w.close()


@pytest.fixture
def can_out(win, monkeypatch):
    sent = []
    monkeypatch.setattr(type(win.connection), "is_connected", property(lambda s: True))
    monkeypatch.setattr(win.connection, "send", lambda i, d, e: sent.append((i, bytes(d))))
    return sent


def _wait_until(cond, timeout_ms=5000):
    """Sabit süre yerine koşul sağlanana dek olay döngüsünü işler (yüklü makinede zamanlama oynar)."""
    waited = 0
    while not cond() and waited < timeout_ms:
        QTest.qWait(20)
        waited += 20
    return cond()


def _decode(win, msg, frame):
    return win.transmit_tab.dbc.get_message(msg).decode(frame[1], decode_choices=False)


def _log(win, cat):
    return [e.message for e in win.event_log.entries if e.category == cat]


# ---------------------------------------------------------------- (1) çifte yazma
def test_home_actuator_write_does_not_get_overwritten_by_control_panel_periodic_frames(win, can_out):
    win.tx_scheduler.set_values("OVERRIDE", {"pump_dc": 20.0})                 # Kontrol Paneli: periyodik
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"), 1.0, "Pompa anahtarı")
    v = _decode(win, "OVERRIDE", can_out[-1])
    assert v["pump_dc"] == pytest.approx(20.0, abs=0.1) and v["pump_dc_sw"] == 1   # Ana Sayfa karesi 20'yi 0'lamaz
    win.tx_scheduler._tick("OVERRIDE")                                          # periyodik sonraki tur
    v = _decode(win, "OVERRIDE", can_out[-1])
    assert v["pump_dc"] == pytest.approx(20.0, abs=0.1) and v["pump_dc_sw"] == 1   # anahtar 0'a DÖNMEZ


def test_home_and_panel_share_one_value_table_and_release_keeps_working(win, can_out):
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 45.0, "Pompa değeri")
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"), 1.0, "Pompa anahtarı")
    assert win.tx_scheduler.values_of("OVERRIDE") == {"pump_dc": 45.0, "pump_dc_sw": 1.0}
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"), 0.0, "Pompa anahtarı")   # bırak
    win.tx_scheduler._tick("OVERRIDE")
    assert _decode(win, "OVERRIDE", can_out[-1])["pump_dc_sw"] == 0               # periyodik kare de "bırakılmış"


def test_motor_commands_stay_single_signal_one_shots(win, can_out):
    cfg = DashboardConfig()
    cfg.motor_start = MotorCommand(Binding(SOURCE_CAN, "CMD", "start_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    win._on_motor_start()
    assert len(can_out) == 1 and not win.tx_scheduler.is_running("CMD")           # periyodik başlamaz


# ---------------------------------------------------------------- (2) güvenlik komutu
def test_safety_command_sends_identical_frame_series_without_blocking(win, can_out):
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_CAN, "CMD", "estop_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    win._on_estop()
    assert len(can_out) == 1                                   # ilk kare ANINDA, arayüz beklemedi
    assert _wait_until(lambda: any("5 kare gönderildi" in m for m in _log(win, "MOTOR")))
    assert len(can_out) == 5 and len(set(can_out)) == 1        # 1 + 4 aynı kare
    assert _decode(win, "CMD", can_out[-1])["estop_req"] == 1


def test_normal_motor_command_is_not_repeated(win, can_out):
    cfg = DashboardConfig()
    cfg.motor_start = MotorCommand(Binding(SOURCE_CAN, "CMD", "start_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    win._on_motor_start()
    QTest.qWait(300)                                           # tekrar OLMAMASI beklenir: yalnızca üst sınır beklenebilir
    assert len(can_out) == 1


def test_safety_series_reports_failure_if_link_drops_mid_series(win, monkeypatch):
    calls = []

    def send(i, d, e):
        calls.append(1)
        if len(calls) > 2:
            raise RuntimeError("hat koptu")
    monkeypatch.setattr(type(win.connection), "is_connected", property(lambda s: True))
    monkeypatch.setattr(win.connection, "send", send)
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_CAN, "CMD", "estop_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    win._on_estop()
    assert _wait_until(lambda: any("tekrar karesi gönderilemedi" in m for m in _log(win, "HATA")))
    assert len(calls) == 3
    assert any("tekrar karesi gönderilemedi" in m and "hat koptu" in m for m in _log(win, "HATA"))


def _patch_ccp_write(monkeypatch, win, fail_times):
    from app import control_panel as cpanel
    n = {"calls": 0}

    def fake(client, info, value, enforce_limits=True, verify=False):
        n["calls"] += 1
        if n["calls"] <= fail_times:
            raise ccp_protocol.CCPTimeoutError("ECU cevap vermedi")
    monkeypatch.setattr(cpanel, "ccp_write_value", fake)
    monkeypatch.setattr(type(win), "ccp_client", property(lambda s: object(), lambda s, v: None))
    return n


def test_safety_a2l_write_retries_communication_errors_then_succeeds(win, monkeypatch):
    n = _patch_ccp_write(monkeypatch, win, fail_times=2)
    b = Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw")
    assert win._write_a2l(b, 1.0, "ACİL DURDURMA", safety=True) is True
    assert n["calls"] == 3
    assert sum("yeniden deneniyor" in m for m in _log(win, "HATA")) == 2


def test_safety_a2l_write_gives_up_after_three_attempts_and_reports(win, monkeypatch):
    n = _patch_ccp_write(monkeypatch, win, fail_times=99)
    b = Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw")
    assert win._write_a2l(b, 1.0, "ACİL DURDURMA", safety=True) is False
    assert n["calls"] == 3
    assert any("ACİL DURDURMA yazılamadı" in m or "yazılamadı" in m for m in _log(win, "HATA"))


def test_normal_a2l_write_is_not_retried(win, monkeypatch):
    n = _patch_ccp_write(monkeypatch, win, fail_times=99)
    b = Binding(SOURCE_A2L, a2l_name="clbc_Fuel_pump_dc_perc_sw")
    assert win._write_a2l(b, 1.0, "Pompa", safety=False) is False
    assert n["calls"] == 1


# ---------------------------------------------------------------- (3) görünüm
@pytest.fixture
def panel(win):
    cp = win.control_panel_tab
    cp.refresh_sources(win.transmit_tab.dbc, win.a2l_tab.db)
    # Test oturumu boyunca ortak veri klasörü kullanılır: önceki testin görünüm/sinyalleri sızmasın.
    cp.config.pinned.clear()
    cp.config.views.clear()
    cp.config.current_view = ""
    cp._rebuild_tables()
    cp._reload_views_combo()
    cp._keys = list(cp._index)
    return cp


def _save_as(cp, monkeypatch, name):
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: (name, True)))
    cp._save_view()


def test_view_shows_changed_marker_and_keeps_real_name(panel, monkeypatch):
    cp = panel
    cp.add_signals(cp._keys[:2])
    _save_as(cp, monkeypatch, "A")
    assert cp.view_combo.currentText() == "A" and not cp._view_dirty()
    cp.add_signals([cp._keys[2]])
    assert cp._view_dirty()
    assert cp.view_combo.currentText() == "A (değişti)" and cp.view_combo.currentData() == "A"
    assert len(cp.config.views["A"]) == 2 and len(cp.config.pinned) == 3
    _save_as(cp, monkeypatch, "A")                                              # kaydet: işaret kalkar
    assert not cp._view_dirty() and cp.view_combo.currentText() == "A" and len(cp.config.views["A"]) == 3


def _switch(cp, idx):
    cp.view_combo.setCurrentIndex(idx)
    cp._on_view_selected(idx)


def test_switching_away_from_changed_view_asks_and_can_save_discard_or_cancel(panel, monkeypatch):
    cp = panel
    cp.add_signals(cp._keys[:2])
    _save_as(cp, monkeypatch, "A")
    cp.add_signals([cp._keys[2]])

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Cancel))
    _switch(cp, 0)
    assert cp.config.current_view == "A" and len(cp.config.pinned) == 3          # iptal: hiçbir şey değişmedi
    assert cp.view_combo.currentData() == "A"

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    _switch(cp, 0)                                                              # kaydet ve geç
    assert len(cp.config.views["A"]) == 3 and cp.config.current_view == ""
    _switch(cp, 1)
    assert len(cp.config.pinned) == 3                                           # eklenen sinyal KAYBOLMADI

    cp.add_signals([cp._keys[3]])
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
    _switch(cp, 0)                                                              # kaydetmeden geç
    assert len(cp.config.views["A"]) == 3


def test_deleting_changed_view_uses_real_name(panel, monkeypatch):
    cp = panel
    cp.add_signals(cp._keys[:2])
    _save_as(cp, monkeypatch, "A")
    cp.add_signals([cp._keys[2]])
    cp._delete_view()
    assert "A" not in cp.config.views
