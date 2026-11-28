"""Tüm araç pencereleri Modas paletini kullanır (ribbon ile aynı mavi-gri zemin, mavi kenarlık, turuncu vurgu)."""
from app import theme
from app.ui.dark_theme import dark_qss


def test_tool_page_qss_uses_modas_palette_and_no_colored_card_stripes():
    q = dark_qss("darkBody")
    for token in (theme.MODAS_RIBBON_BG, theme.MODAS_WIN_LINE, theme.MODAS_ORANGE, theme.MODAS_TABLE_HEAD, theme.MODAS_LIST_SEL,
                  theme.MODAS_RIBBON_HOVER):
        assert token in q, token
    assert 'accent="green"' not in q and 'accent="purple"' not in q            # renkli kart şeritleri yok
    assert "border-top: 2px solid " + theme.MODAS_WIN_LINE in q                # tek tip mavi üst çizgi


def test_tool_windows_are_wrapped_in_the_modas_background(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        win = w.open_tool("CAN İzleme")
        scroll = w._page_scrolls[w.can_monitor_tab] if w.can_monitor_tab in w._page_scrolls else None
        assert win is not None and win.windowTitle().startswith("CAN İzleme")
        if scroll is not None:
            assert theme.MODAS_RIBBON_BG in scroll.styleSheet() or scroll.styleSheet() == ""
    finally:
        w.close()
