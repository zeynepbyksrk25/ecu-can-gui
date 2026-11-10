import os
import tempfile

import pytest

pytest.importorskip("PySide6")
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def make_tab(qapp, tmp=None):
    from app.ui.workspace_tab import WorkspaceLayoutStore, WorkspaceTab
    d = tmp or tempfile.mkdtemp()
    return WorkspaceTab(store=WorkspaceLayoutStore(os.path.join(d, "lay.json")))


def test_floating_panel_refreshes_when_tab_hidden_and_roundtrips(qapp):
    from app.ui.workspace_tab import _Float
    w = make_tab(qapp)
    w.show()
    p = w._panels[0] if w._panels else w.add_panel("plot")
    calls = []
    orig = p.refresh
    p.refresh = lambda span, frozen: (calls.append(1), orig(span, frozen))[1]
    w._detach(p)
    assert isinstance(w._subs[p], _Float)
    w.hide()                                # başka sekme seçilmiş gibi
    w._tick()
    assert calls, "ayrılmış panel gizli sekmede de güncellenmeli"
    st = w.to_state()
    assert st["panels"][0].get("floating")
    w.apply_state(st)
    assert any(isinstance(x, _Float) for x in w._subs.values())
    p2 = w._panels[0]
    w._dock(p2, w._subs[p2])
    assert "floating" not in w.to_state()["panels"][0]
    w.shutdown()


def test_visible_geometry_is_clamped_on_screen(qapp):
    from app.ui.workspace_tab import WorkspaceTab
    r = WorkspaceTab._visible_geometry([-5000, -5000, 99999, 99999])
    from PySide6.QtGui import QGuiApplication
    a = QGuiApplication.primaryScreen().availableGeometry()
    assert a.contains(r)


def test_shutdown_survives_errors(qapp):
    w = make_tab(qapp)
    w._autosave = lambda force=False: (_ for _ in ()).throw(RuntimeError("disk"))
    w.shutdown()                            # istisna yutulur, çağıran devam eder


def test_floating_window_is_independent_toplevel(qapp):
    from PySide6.QtCore import Qt
    from app.ui.workspace_tab import _Float
    w = make_tab(qapp)
    w.show()
    p = w._panels[0] if w._panels else w.add_panel("plot")
    w._detach(p)
    fl = w._subs[p]
    assert isinstance(fl, _Float)
    assert fl.parent() is None, "ayrılan pencere ana pencereye bağlı olmamalı"
    assert fl.windowFlags() & Qt.Window
    w.shutdown()


def test_old_layout_with_removed_control_panel_loads_without_it(qapp):
    """Çalışma Alanı'ndan giriş (Kontrol) paneli kaldırıldı; eski yerleşimdeki 'control' paneli
    atlanır, kalan paneller yüklenir."""
    w = make_tab(qapp)
    state = {"version": 1, "span": 1, "derived": {}, "panels": [
        {"kind": "plot", "title": "Grafik 1", "geometry": [10, 10, 400, 300], "state": {}},
        {"kind": "control", "title": "Kontrol 1", "geometry": [20, 20, 320, 360], "state": {}},
        {"kind": "table", "title": "Tablo 1", "geometry": [30, 30, 400, 200], "state": {}},
    ]}
    w.apply_state(state)
    kinds = sorted(p.kind for p in w._panels)
    assert kinds == ["plot", "table"]
    assert "control" not in [p.kind for p in w._panels]
    assert not hasattr(w, "send_input")
