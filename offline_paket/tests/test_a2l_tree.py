"""Ortak A2L ağaç yardımcıları ve onu kullanan üç sekmenin süzgeci."""
import os

DATA = os.path.join(os.path.dirname(__file__), "data")


def _leaf_names(tree, visible_only=True):
    out = []

    def walk(item):
        if item.childCount() == 0:
            if not visible_only or not item.isHidden():
                out.append(item.text(0))
        for i in range(item.childCount()):
            walk(item.child(i))

    for i in range(tree.topLevelItemCount()):
        top = tree.topLevelItem(i)
        if not visible_only or not top.isHidden():
            walk(top)
    return out


def test_filter_tree_nested_groups_and_empty_groups(qapp):
    from PySide6.QtWidgets import QTreeWidgetItem
    from app.ui.a2l_tree import filter_tree, new_tree, payload_item
    tree = new_tree(lambda *_: None)
    root = QTreeWidgetItem(["Characteristics"])
    grp = QTreeWidgetItem(["Scalar"])
    grp.addChild(payload_item("clbc_Fuel_pump_gain", 1))
    grp.addChild(payload_item("clbc_Temp_limit", 2))
    root.addChild(grp)
    empty = QTreeWidgetItem(["Maps (0)"])
    root.addChild(empty)
    tree.addTopLevelItem(root)
    tree.addTopLevelItem(QTreeWidgetItem(["Measurements (0)"]))       # boş üst düzey grup

    filter_tree(tree, "")
    assert not root.isHidden() and not empty.isHidden() and not tree.topLevelItem(1).isHidden()

    filter_tree(tree, "FUEL")                                          # büyük/küçük harf duyarsız
    assert _leaf_names(tree) == ["clbc_Fuel_pump_gain"]
    assert tree.topLevelItem(1).isHidden() and empty.isHidden()

    filter_tree(tree, "yok_boyle_bir_sey")
    assert root.isHidden() and _leaf_names(tree) == []
    filter_tree(tree, "")
    assert len(_leaf_names(tree)) == 4


def test_three_tabs_share_filter_and_keep_payload_shapes(qapp):
    from app.a2l import A2LDatabase
    from app.ui.a2l_tab import A2LTab
    from app.ui.a2l_tree import ROLE_OBJECT
    from app.ui.ccp_tab import CCPTab
    from app.ui.map_editor_tab import MapEditorTab
    a2l = A2LTab()
    summary = a2l.db.load(os.path.join(DATA, "sample.a2l"))
    a2l.show_loaded(os.path.join(DATA, "sample.a2l"), summary)

    ccp = CCPTab()
    ccp.a2l_db = a2l.db
    ccp.refresh_objects()
    mapt = MapEditorTab()
    mapt.a2l_db = a2l.db
    mapt.refresh_objects()

    for tab in (a2l, ccp):
        tab.search_edit.setText("clbc_Fuel_pump_gain")
        assert _leaf_names(tab.tree) == ["clbc_Fuel_pump_gain"] or _leaf_names(tab.tree) == [
            "clbc_Fuel_pump_gain  [SCALAR]"]
        tab.search_edit.setText("")
        assert len(_leaf_names(tab.tree)) >= 8
    # payload biçimi: A2L/CCP ("tür", nesne); Harita Editörü doğrudan nesne
    top = ccp.tree.topLevelItem(0)
    assert top.child(0).data(0, ROLE_OBJECT)[0] == "measurement"
    mapt.search_edit.setText("zzz")
    assert all(mapt.tree.topLevelItem(i).isHidden() for i in range(mapt.tree.topLevelItemCount()))
    mapt.search_edit.setText("")
    assert not any(mapt.tree.topLevelItem(i).isHidden() for i in range(mapt.tree.topLevelItemCount()))
