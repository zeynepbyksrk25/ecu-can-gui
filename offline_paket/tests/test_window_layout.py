"""Kaydet sonrası sayfa kayması: asgari boyut ilk gösterimde doğru hesaplanmalı, sonradan değişmemeli."""
import pytest
from PySide6.QtTest import QTest


@pytest.fixture
def shown(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.resize(1400, 850)
    w.show()
    QTest.qWait(700)                      # showEvent'in iki (anlık + gecikmeli) yenilemesi tamamlansın
    yield w
    w.close()


def test_minimum_size_is_already_settled_after_first_show(shown):
    """Eskiden yapıcıdaki ilk hesap stiller uygulanmadan yapılıyordu; ilk Kaydet'te asgari boyut ~40 px büyüyüp
    pencere/yerleşim kayıyordu. Artık ilk gösterimden sonra yenileme hiçbir şeyi değiştirmemeli."""
    before = (shown.width(), shown.height(), shown.minimumWidth(), shown.minimumHeight())
    shown._refresh_minimum_size()
    QTest.qWait(50)
    assert (shown.width(), shown.height(), shown.minimumWidth(), shown.minimumHeight()) == before


def test_dashboard_save_does_not_resize_the_window(shown):
    from app.dashboard_config import SOURCE_CAN, Binding, DashboardConfig, MotorCommand
    before = (shown.width(), shown.height(), shown.minimumHeight())
    cfg = DashboardConfig()
    cfg.motor_start = MotorCommand(Binding(SOURCE_CAN, "CMD", "start_req"), 1.0)
    shown.dashboard_tab.set_config(cfg)
    shown.dashboard_tab.config_saved.emit(cfg)
    QTest.qWait(200)
    assert (shown.width(), shown.height(), shown.minimumHeight()) == before


def test_maximized_window_is_not_resized_by_the_refresh(shown, monkeypatch):
    calls = []
    monkeypatch.setattr(shown, "isMaximized", lambda: True)
    monkeypatch.setattr(shown, "resize", lambda *a: calls.append(a))
    shown.setMinimumSize(1100, 600)
    shown._refresh_minimum_size()
    assert calls == []
