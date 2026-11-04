"""Koyu tema: sayfa sarmalayıcı, diyalog okunurluğu, A2L sayfası."""
import os

import pytest
from PySide6.QtWidgets import QLabel, QMessageBox, QWidget

DATA = os.path.join(os.path.dirname(__file__), "data")


def luminance(c):
    return 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()


def test_dark_wrapper_keeps_page_aliases_and_navigation(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    scroll = w.stack.widget(w.stack.indexOf(w._page_scrolls[w.a2l_tab]))
    body = scroll.widget()
    assert body.objectName() == "darkBody" and body.inner is w.a2l_tab
    w.setCurrentWidget(w.a2l_tab)
    assert w.nav_bar.tabText(w.nav_bar.currentIndex()) == "A2L"
    assert w.current_page() is w.a2l_tab
    w.close()


def test_message_box_inside_dark_body_is_readable_not_transparent(qapp):
    from app.ui.a2l_tab import A2LTab
    from app.ui.dark_theme import dark_scroll_page
    page = A2LTab()
    body = dark_scroll_page(page)
    body.resize(600, 300)
    body.show()
    box = QMessageBox(page)                        # gövdenin ÇOCUĞU: eskiden şeffaf zemin + açık yazı alırdı
    box.setText("Okunabilir olmalı: A2L yüklenemedi")
    box.setIcon(QMessageBox.Warning)
    box.show()
    qapp.processEvents()
    img = box.grab().toImage()
    bg = img.pixelColor(4, 4)
    assert bg.alpha() == 255 and luminance(bg) < 70          # koyu kart zemini (şeffaf/açık değil)
    lbl = next(l for l in box.findChildren(QLabel) if "Okunabilir" in l.text())
    r = lbl.geometry()
    light = [luminance(img.pixelColor(x, y)) for x in range(r.left(), r.right(), 2)
             for y in range(r.top(), r.bottom(), 2)]
    assert max(light) > 170                                  # açık renkli yazı koyu zeminde seçilebiliyor
    box.close()
    body.close()


def test_a2l_page_summary_tree_filter_and_details(qapp):
    from app.ui.a2l_tab import A2LTab, ROLE_OBJECT
    tab = A2LTab()
    summary = tab.db.load(os.path.join(DATA, "sample.a2l"))
    tab.show_loaded(os.path.join(DATA, "sample.a2l"), summary)
    assert tab.file_chip.text() == "sample.a2l"
    assert "ölçüm" in tab.meas_chip.text() and "ayarlanabilir skaler" in tab.char_chip.text()
    top = [tab.tree.topLevelItem(i).text(0) for i in range(tab.tree.topLevelItemCount())]
    assert top[0].startswith("Measurements (") and top[1].startswith("Characteristics (")
    # ölçüm seçilince ADRES de gösterilir (eskiden "-" idi)
    meas_root = tab.tree.topLevelItem(0)
    item = next(meas_root.child(i) for i in range(meas_root.childCount()) if meas_root.child(i).text(0) == "N_RPM")
    tab._on_item_clicked(item, 0)
    assert tab.detail_address.text() == "0x1000" and "MSB_LAST" in tab.detail_datatype.text()
    # ayarlanabilir skaler seçilince kullanım ipucu
    tab.search_edit.setText("clbc_Fuel_pump_gain")
    chars = tab.tree.topLevelItem(1)
    scalar = chars.child(0)
    leaf = next(scalar.child(i) for i in range(scalar.childCount()) if not scalar.child(i).isHidden())
    assert leaf.text(0) == "clbc_Fuel_pump_gain"
    tab._on_item_clicked(leaf, 0)
    assert "Parametre Listesi" in tab.detail_use.text() and tab.detail_readonly.text().startswith("Evet")
    tab.search_edit.setText("")


def test_small_pages_dark_and_accessors(tmp_path):
    from PySide6.QtWidgets import QApplication
    from app.ui.main_window import MainWindow
    w = MainWindow()
    for page in (w.tanilama_tab, w.session_tab, w.user_tab):
        assert page in w._dark_pages
    s = w.session_tab
    assert s.stop_button.isEnabled() is False and s.state_chip.text() == "Oturum yok"
    assert hasattr(w.tanilama_tab, "diagnostics") and hasattr(w.tanilama_tab, "errors")
    assert w.user_tab.role_combo.count() >= 3 and w.user_tab.profile_list is not None
    w.close()


def test_kalibrasyon_dark_and_aliases():
    from app.ui.main_window import MainWindow
    w = MainWindow()
    assert w.kalibrasyon_tab in w._dark_pages
    k = w.kalibrasyon_tab
    assert k.inner_tabs.count() == 4 and k.watch is not None and k.map_editor is not None
    w.close()


def test_graph_performance_dark_no_captions():
    from app.ui.main_window import MainWindow
    w = MainWindow()
    assert w.graph_tab in w._dark_pages and w.performance_tab in w._dark_pages
    assert "geri okunuşu" not in "".join(b.toolTip() for b in w.performance_tab._flight_boxes.values())
    assert w.graph_tab._tiles[0].crosshair_label.text() == ""
    w.close()
