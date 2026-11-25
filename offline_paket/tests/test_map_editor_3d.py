"""Harita Editörü: MATLAB Lookup Table Editor düzeni (Spreadsheet + Plot-Mesh 3B + Plot-Contour)."""
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtCore import QEvent

from app.a2l import AxisInfo, CharacteristicInfo


def _map():
    xs, ys = [1.0, 2.0, 3.0], [10.0, 20.0]
    return CharacteristicInfo("M", "", "MAP", 0x1000, "%", "UWORD", 0, 100, False, 2,
                              axes=[AxisInfo(3, "", "FIX_AXIS", xs), AxisInfo(2, "rpm", "FIX_AXIS", ys)])


def _curve():
    return CharacteristicInfo("C", "", "CURVE", 0x2000, "V", "UWORD", 0, 100, False, 1,
                              axes=[AxisInfo(4, "s", "FIX_AXIS", [0, 1, 2, 3])])


def _mouse(kind, x, y, button=Qt.LeftButton):
    return QMouseEvent(kind, QPointF(x, y), QPointF(x, y), button, button, Qt.NoModifier)


def test_layout_has_spreadsheet_mesh_contour_and_data_source(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    tab = MapEditorTab()
    doc = tab.open_characteristic(_map())
    doc.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    assert doc.mesh_panel is not None and doc.contour_panel is not None
    assert not doc.heatmap_checkbox.isChecked()
    assert doc.source_table.rowCount() == 3                      # Z + eksen X + eksen Y
    assert doc.mesh.z == [[1, 2, 3], [4, 5, 6]] and doc.mesh.xs == [1.0, 2.0, 3.0] and doc.mesh.ys == [10.0, 20.0]
    assert doc.mesh.labels == ("X", "Y (rpm)", "Z (%)")
    doc.hide_plot_button.setChecked(True)
    assert not doc.plot_splitter.isVisibleTo(doc)


def test_selecting_cell_marks_mesh_vertex_and_mesh_pick_selects_cell(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    doc = MapEditorTab().open_characteristic(_map())
    doc.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    doc.table.setCurrentCell(1, 2)
    doc.table.item(1, 2).setSelected(True)
    assert (1, 2) in doc.mesh.selected
    doc.mesh.cellPicked.emit(0, 1, False)
    assert doc._selected_cells() == [(0, 1)] and doc.mesh.selected == {(0, 1)}


def test_mesh_vertex_drag_edits_table_with_single_undo_step(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    doc = MapEditorTab().open_characteristic(_map())
    doc.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    n = len(doc._history)
    for v in (5.5, 6.5, 7.25):                                   # sürükleme: canlı güncelleme, geçmişe girmez
        doc.mesh.cellDragged.emit(1, 2, v)
        assert doc.current_grid()[1][2] == v
    assert len(doc._history) == n
    doc.mesh.dragFinished.emit()
    assert len(doc._history) == n + 1 and doc.is_modified()
    doc.undo()
    assert doc.current_grid()[1][2] == 6.0


def test_real_mouse_drag_on_vertex_raises_value_and_empty_drag_rotates(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    tab = MapEditorTab()
    tab.resize(1200, 800)
    doc = tab.open_characteristic(_map())
    doc.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    tab.show()
    qapp.processEvents()
    m = doc.mesh
    tf, _ = m._transform()
    sx, sy, _d, r, c, val = next(v for v in m._vertices(tf) if (v[3], v[4]) == (1, 2))
    m.mousePressEvent(_mouse(QEvent.MouseButtonPress, sx, sy))
    m.mouseMoveEvent(_mouse(QEvent.MouseMove, sx, sy - 40))
    m.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, sx, sy - 40))
    assert doc.current_grid()[1][2] > 6.0                        # yukarı sürükle -> değer artar
    assert doc._selected_cells() == [(1, 2)]
    az = m.az
    m.mousePressEvent(_mouse(QEvent.MouseButtonPress, 3, 3))      # boş alan: döndürme
    m.mouseMoveEvent(_mouse(QEvent.MouseMove, 33, 3))
    m.mouseReleaseEvent(_mouse(QEvent.MouseButtonRelease, 33, 3))
    assert m.az != az


def test_curve_and_partial_grid_render_without_errors(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    tab = MapEditorTab()
    tab.resize(900, 700)
    cur = tab.open_characteristic(_curve())
    mp = tab.open_characteristic(_map())                         # henüz ECU'dan okunmadı: tüm hücreler "-"
    tab.show()
    cur.set_grid_from_ecu([[1, 3, 2, 4]])
    qapp.processEvents()
    assert cur.mesh.z == [[1, 3, 2, 4]]
    assert tab.tabs.count() == 2 and mp.mesh.z == [[None] * 3] * 2
    mp.mesh.grab()
    cur.mesh.grab()
    mp.table.item(0, 0).setText("7")
    mp.mesh.grab()


def test_matlab_style_headers_expression_and_plain_cells(qapp):
    from app.ui.map_editor_tab import MapEditorTab
    doc = MapEditorTab().open_characteristic(_map())
    doc.set_grid_from_ecu([[1, 2, 3], [4, 5, 6]])
    assert not doc.heatmap_checkbox.isChecked()
    assert doc.table.horizontalHeader().sizeHint().height() > doc.table.verticalHeader().defaultSectionSize()
    doc.table.horizontalHeader().grab()
    doc.table.verticalHeader().grab()
    doc.table.setCurrentCell(0, 0)
    for rc in ((0, 0), (1, 1)):
        doc.table.item(*rc).setSelected(True)
    doc.expr_edit.setText("x*10+1")
    assert doc.apply_expression() == (2, 0)
    assert doc.current_grid() == [[11, 2, 3], [4, 51, 6]]
    doc.expr_edit.setText("__import__('os')")
    assert doc.apply_expression() == (0, 0) and doc.current_grid()[0][0] == 11
