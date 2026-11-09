"""Acil Durdurma: eşleme yokken sessizce ÇALIŞMAMALI; operatör komutun gitmediğini açıkça görmeli."""
import pytest
from PySide6.QtWidgets import QMessageBox

from app.dashboard_config import SOURCE_CAN, Binding, DashboardConfig, MotorCommand


@pytest.fixture
def win(qapp, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(("critical", a)) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(("warning", a)) or QMessageBox.Yes))
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w._shown = shown
    yield w
    w.close()


def _errors(w):
    return [e.message for e in w.event_log.entries if e.category == "HATA"]


def test_estop_button_stays_clickable_and_warns_when_unmapped(win):
    dt = win.dashboard_tab
    dt.set_config(DashboardConfig())                    # hiçbir eşleme yok
    assert dt.estop_button.isEnabled()                  # gri/tıklanamaz DEĞİL
    assert not dt.estop_warn.isHidden() and "eşlenmemiş" in dt.estop_warn.text()
    assert "TANIMLI DEĞİL" in dt.estop_button.toolTip() or "tanımlı DEĞİL" in dt.estop_button.toolTip()
    # Başlat/Durdur eski davranışta: eşleme yoksa devre dışı
    assert not dt.start_button.isEnabled() and not dt.stop_button.isEnabled()


def test_click_when_unmapped_skips_confirmation_and_reports_failure(win):
    dt = win.dashboard_tab
    dt.set_config(DashboardConfig())
    win._shown.clear()
    dt.estop_button.click()
    kinds = [k for k, a in win._shown]
    assert kinds == ["critical"], "onay sorusu değil, açık hata penceresi çıkmalı"
    assert "GÖNDERİLEMEDİ" in win._shown[0][1][1]
    assert any("ACİL DURDURMA GÖNDERİLEMEDİ" in m for m in _errors(win))


def test_mapped_estop_hides_warning_and_failed_send_is_logged(win):
    dt = win.dashboard_tab
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_CAN, "CMD", "estop_req"), 1.0)
    dt.set_config(cfg)
    assert dt.estop_button.isEnabled() and dt.estop_warn.isHidden()
    assert dt.estop_button.toolTip() == ""
    # CAN bağlı değil: gönderim başarısız -> günlüğe HATA düşer (sessiz değil)
    win._shown.clear()
    assert win._send_motor_command("ACİL DURDURMA", cfg.estop) is False
    assert any("ACİL DURDURMA GÖNDERİLEMEDİ" in m for m in _errors(win))
    assert win._shown, "başarısız gönderimde kullanıcıya neden gösterilmeli"


def test_other_motor_commands_log_unmapped_failure(win):
    win.dashboard_tab.set_config(DashboardConfig())
    assert win._send_motor_command("Motor Start", win.dashboard_tab.config.motor_start) is False
    assert any("Motor Start GÖNDERİLEMEDİ" in m for m in _errors(win))
