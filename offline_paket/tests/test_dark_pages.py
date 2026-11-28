"""Koyu tema: sayfa sarmalayıcı, diyalog okunurluğu, A2L sayfası."""
import os

from PySide6.QtWidgets import QLabel, QMessageBox

DATA = os.path.join(os.path.dirname(__file__), "data")


def luminance(c):
    return 0.2126 * c.red() + 0.7152 * c.green() + 0.0722 * c.blue()


def test_dark_wrapper_keeps_page_aliases_and_navigation(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.setCurrentWidget(w.kalibrasyon_tab)                          # araç penceresi açılır (Calibration Tools)
    scroll = w._page_scrolls[w.kalibrasyon_tab]
    body = scroll.widget()
    assert body.objectName() == "darkBody" and body.inner is w.kalibrasyon_tab
    assert w.kalibrasyon_tab.window() is w._tool_windows[w.kalibrasyon_tab]
    # A2L'nin görünür sekmesi yok (Project Manager + Variable list); Calibration Tools yalnız CCP ve Geçmiş
    tabs = w.kalibrasyon_tab.inner_tabs
    assert [tabs.tabText(i) for i in range(tabs.count())] == ["CCP", "Geçmiş"]
    assert not hasattr(w.kalibrasyon_tab, "a2l")
    assert w.a2l_tab.window() is w and not w.a2l_tab.isVisible()        # ilerleme/hata kutuları ana pencereye bağlı
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
    assert bg.alpha() == 255 and luminance(bg) > 200         # açık kart zemini (şeffaf değil)
    lbl = next(l for l in box.findChildren(QLabel) if "Okunabilir" in l.text())
    r = lbl.geometry()
    light = [luminance(img.pixelColor(x, y)) for x in range(r.left(), r.right(), 2)
             for y in range(r.top(), r.bottom(), 2)]
    assert min(light) < 120                                  # koyu yazı açık zeminde seçilebiliyor
    box.close()
    body.close()


def test_a2l_page_summary_tree_filter_and_details(qapp):
    from app.ui.a2l_tab import A2LTab
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
    assert "değer penceresinde" in tab.detail_use.text() and tab.detail_readonly.text().startswith("Evet")
    tab.search_edit.setText("")


def test_small_pages_dark_and_accessors(tmp_path):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    assert w.tanilama_tab in w._dark_pages
    # Profil ayrı araç değil, Ayarlar penceresinde
    assert "Profil" not in w._tool_pages
    assert w.settings_dialog.user_tab is w.user_tab
    assert w.session_tab is w.tanilama_tab.session
    assert "Diagnostics" in w._tool_pages and "Test Oturumu" not in w._tool_pages
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
    assert k.inner_tabs.count() == 2 and not hasattr(k, "map_editor") and not hasattr(k, "watch")
    w.close()


def test_analysis_page_removed_scope_replaces_workspace():
    from app.ui.main_window import MainWindow
    w = MainWindow()
    assert "Analysis" not in w._tool_pages and list(w._tool_pages) == [
        "Test Bench", "CAN Trace", "Calibration Tools", "Control Panel", "Diagnostics"]
    for gone in ("analiz_tab", "workspace_tab", "performance_tab", "graph_tab"):
        assert not hasattr(w, gone)
    assert w.signal_feed.hub is w.modas_tab.hub                    # Scope'ların ortak deposu
    w.close()


def test_control_panel_dark():
    from app.ui.main_window import MainWindow
    w = MainWindow()
    assert w.control_panel_tab in w._dark_pages
    assert "Uygula'ya basınca" not in w.control_panel_tab.effects_title.text()
    w.close()
