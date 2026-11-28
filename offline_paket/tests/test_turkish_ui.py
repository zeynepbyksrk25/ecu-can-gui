"""Arayüz tamamen Türkçe: ana pencere ve tüm araç sayfalarındaki görünen metinlerde bilinen İngilizce etiketler kalmamalı."""
import re

from PySide6.QtWidgets import QAbstractButton, QLabel, QTabBar

ENGLISH = {"Start", "Stop", "Label", "Scope", "Tools", "Windows", "Worksheets", "Variable list", "Log-Windows", "Save", "Delete",
           "Open", "Close", "Remove", "Rename", "Template", "Tile", "Cascade", "Close all", "Information", "Measurement",
           "Recording", "Data", "Show", "Arrange", "Files", "Macro", "Format", "Physical", "Decimal", "Hexadecimal", "Binary",
           "Test Bench", "CAN Trace", "Calibration Tools", "Control Panel", "Diagnostics", "Project Manager", "OFFLINE", "ONLINE",
           "Workbase:", "Project:", "Add label", "New", "Hold", "Clear", "Span:", "Read data from ECU", "Write data to ECU"}


def _texts(root):
    out = []
    for w in root.findChildren(QAbstractButton) + root.findChildren(QLabel):
        t = w.text().strip()
        if t:
            out.append(t)
    for bar in root.findChildren(QTabBar):
        out += [bar.tabText(i).split("  [")[0].strip() for i in range(bar.count())]
    return out


def test_no_english_ui_labels_in_main_window_and_tool_pages(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        w.modas_tab.add_scope([])
        texts = []
        for i in range(w.modas_ribbon.tabs.count()):
            w.modas_ribbon.select_tab(i)
            texts += _texts(w.modas_ribbon)
        texts += _texts(w.modas_tab)
        for page in w._tool_pages.values():
            texts += _texts(page)
        texts += _texts(w.settings_dialog)
        bad = sorted({t for t in texts if t in ENGLISH})
        assert not bad, f"İngilizce etiketler kalmış: {bad}"
        rb = w.modas_ribbon
        assert [rb.tabs.tabText(i) for i in range(rb.tabs.count())] == ["Başlat", "Etiket", "Çalışma Sayfaları", "Araçlar", "Pencereler"]
        assert list(w._tool_pages) == ["Test Tezgâhı", "CAN İzleme", "Kalibrasyon Araçları", "Kontrol Paneli", "Tanılama"]
        assert re.search(r"[İıŞşĞğÇçÖöÜü]", rb.buttons["ecu"].text())              # ECU durum düğmesi Türkçe (ÇEVRİMDIŞI)
    finally:
        w.close()
