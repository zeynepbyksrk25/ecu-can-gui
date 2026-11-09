"""Eyleyiciler kartı: satır yüksekliği sınırlı, KOMUT başlığı kontrollerle hizalı."""
from PySide6.QtWidgets import QApplication


def _shown(qapp, h):
    from app.ui.dashboard_tab import DashboardTab
    t = DashboardTab()
    t.resize(1500, h)
    t.show()
    for _ in range(5):
        qapp.processEvents()
    return t


def test_actuator_rows_are_capped_and_head_is_aligned(qapp):
    for h in (900, 1400):
        t = _shown(qapp, h)
        rows = [e["lock"].parentWidget().parentWidget() for e in t._act_rows.values()]
        assert rows and all(r.height() <= 52 for r in rows)
        first = next(iter(t._act_rows.values()))
        cell = first["control"].parentWidget()
        head_right = t.act_head_cmd.mapTo(t, t.act_head_cmd.rect().topRight()).x()
        cell_right = cell.mapTo(t, cell.rect().topRight()).x()
        assert abs(head_right - cell_right) <= 1
        t.close()
