"""Test kayıtlarının Excel (.xlsx) olarak bilgisayara kaydı: yazıcı, oturum/CAN çalışma kitapları ve
uçtan uca (oturum bitince otomatik). Doğrulama bağımlılıksızdır (zip + XML); openpyxl varsa ayrıca okunur."""
import os
import time
import xml.etree.ElementTree as ET
import zipfile

import pytest

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def read_xlsx(path: str) -> dict:
    """{sayfa adı: [[hücre değerleri]]} (metin/sayı/mantıksal; boş hücre None)."""
    out = {}
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
        target = {r.get("Id"): r.get("Target") for r in rels}
        for sh in wb.find("m:sheets", NS):
            part = "xl/" + target[sh.get(f"{{{NS['r']}}}id")]
            root = ET.fromstring(z.read(part))
            rows = []
            for row in root.find("m:sheetData", NS):
                vals = []
                for c in row:
                    ref = c.get("r")
                    col = 0
                    for ch in "".join(x for x in ref if x.isalpha()):
                        col = col * 26 + ord(ch) - 64
                    while len(vals) < col - 1:
                        vals.append(None)
                    t = c.get("t")
                    if t == "inlineStr":
                        vals.append("".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t")))
                    elif t == "b":
                        vals.append(c.find("m:v", NS).text == "1")
                    else:
                        v = c.find("m:v", NS)
                        vals.append(float(v.text) if v is not None else None)
                rows.append(vals)
            out[sh.get("name")] = rows
    return out


def test_writer_produces_valid_workbook_with_special_characters_and_unique_names(tmp_path):
    import datetime
    from app.xlsx_export import XlsxWorkbook
    p = str(tmp_path / "a.xlsx")
    with XlsxWorkbook(p) as wb:
        s = wb.sheet("Özet: [x]/y", ["Alan", "Değer"])
        s.row(["ş ğ İ <&> \"q\"", 1.5])
        s.row(["bool", True])
        s.row(["nan", float("nan")])
        s.row(["kontrol", "a\x01b"])
        d = wb.sheet("Veri", ["t"], formats=["datetime"])
        d.row([datetime.datetime(2026, 11, 17, 12, 0, 0)])
        wb.sheet("veri", ["a"]).row(["aynı ad (büyük/küçük harf farkı)"])
    data = read_xlsx(p)
    assert list(data) == ["Özet_ _x__y", "Veri", "veri (2)"]
    rows = data["Özet_ _x__y"]
    assert rows[1] == ["ş ğ İ <&> \"q\"", 1.5] and rows[2] == ["bool", True]
    assert rows[3] == ["nan"] and rows[4] == ["kontrol", "ab"]          # NaN boş, kontrol karakteri atılır
    assert not os.path.exists(p + ".tmp")


def test_writer_splits_sheets_at_the_row_limit_and_leaves_no_partial_file_on_error(tmp_path, monkeypatch):
    import app.xlsx_export as xe
    monkeypatch.setattr(xe, "MAX_ROWS", 5)
    p = str(tmp_path / "b.xlsx")
    with xe.XlsxWorkbook(p) as wb:
        sh = wb.sheet("Veri", ["n"])
        for i in range(12):
            sh.row([i])
    data = read_xlsx(p)
    assert list(data) == ["Veri", "Veri (2)", "Veri (3)"]
    got = [r[0] for name in data for r in data[name][1:]]
    assert got == [float(i) for i in range(12)]                          # hiçbir satır kaybolmadı/tekrarlanmadı
    assert all(r[0] == "n" for r in (data[n][0] for n in data))          # her parçada başlık var
    q = str(tmp_path / "c.xlsx")
    with pytest.raises(RuntimeError):
        with xe.XlsxWorkbook(q) as wb:
            wb.sheet("X", ["a"]).row([1])
            raise RuntimeError("yazma sırasında hata")
    assert not os.path.exists(q) and not os.path.exists(q + ".tmp")


def _record_csv(path: str, n_seconds: int = 5):
    from app.session_recorder import SessionRecorder
    rec = SessionRecorder()
    csv_path = rec.start(str(path), "Soğutma testi")
    t0 = time.time()
    for i in range(n_seconds * 10):
        t = t0 + i * 0.1
        rec.record("a2l:RPM", 1000 + i, t)
        if i % 10 == 0:
            rec.record("gauge:PLA", 20 + i // 10, t)
    rec.stop()
    return csv_path


def test_session_workbook_has_summary_stats_long_wide_events_and_calibration_sheets(tmp_path):
    from app.eventlog import EventEntry
    from app.history import HistoryEntry
    from app.log_export import SessionInfo, write_session_workbook
    csv_path = _record_csv(tmp_path)
    now = time.time()
    info = SessionInfo(name="Soğutma testi", operator="Zeynep", started=now - 10, ended=now, record_csv=csv_path)
    events = [EventEntry(now - 5, "KALIBRASYON", "x = 1 (RAM) yazıldı", "Zeynep", "Mühendis"),
              EventEntry(now - 4, "HATA", "CAN bus-off", "Zeynep", "Mühendis")]
    history = [HistoryEntry(now - 5, "Zeynep", "Mühendis", "clbc_x", 0.5, 1.0, "%", persistent=False),
               HistoryEntry(now - 3, "Zeynep", "Yönetici", "clbc_y", 2.0, 3.0, "bar", persistent=True)]
    out = str(tmp_path / "oturum.xlsx")
    stats = write_session_workbook(out, info, events, history)
    assert stats == {"rows": 55, "signals": 2}
    data = read_xlsx(out)
    assert list(data) == ["Özet", "Girişler (tüm sayfalar)", "Kalibrasyon yazımları", "Olay günlüğü",
                          "Sinyal özeti", "Parametre kaydı", "Geniş tablo"]
    summary = {r[0]: r[1] for r in data["Özet"][1:] if len(r) > 1}
    assert summary["Operatör"] == "Zeynep" and summary["Parametre kaydı: örnek sayısı"] == 55
    assert summary["  bunlardan HATA"] == 1 and summary["Kalibrasyon yazımı (RAM)"] == 1
    assert summary["Kalibrasyon yazımı (FLAŞ)"] == 1
    assert any("ECU'ya (RAM/flaş) yazılmaz" in str(r[1]) for r in data["Özet"] if len(r) > 1)
    sig = {r[0]: r for r in data["Sinyal özeti"][1:]}
    assert sig["a2l:RPM"][1] == 50 and sig["a2l:RPM"][4] == 1000 and sig["a2l:RPM"][5] == 1049
    assert sig["gauge:PLA"][1] == 5 and sig["gauge:PLA"][4] == 20 and sig["gauge:PLA"][5] == 24
    long = data["Parametre kaydı"]
    assert long[0] == ["Tarih/saat", "Süre (sn)", "Sinyal", "Değer"] and len(long) == 56
    wide = data["Geniş tablo"]
    assert wide[0] == ["Süre (sn)", "a2l:RPM", "gauge:PLA"]
    assert len(wide) >= 5 and all(r[1] is not None for r in wide[1:])     # RPM her saniye dilimde var
    assert wide[1][2] == 20 and wide[2][2] == 21                         # PLA örneği dilimlerde (sample & hold)
    assert [r[1] for r in data["Olay günlüğü"][1:]] == ["KALIBRASYON", "HATA"]
    cal = data["Kalibrasyon yazımları"]
    assert [r[1] for r in cal[1:]] == ["RAM", "FLAŞ"] and cal[2][4] == "clbc_y"


def test_session_workbook_without_a_record_file_still_has_events_and_notes(tmp_path):
    from app.log_export import SessionInfo, write_session_workbook
    out = str(tmp_path / "bos.xlsx")
    stats = write_session_workbook(out, SessionInfo(name="Kayıtsız"), [], [])
    assert stats == {"rows": 0, "signals": 0}
    assert list(read_xlsx(out)) == ["Özet", "Girişler (tüm sayfalar)", "Kalibrasyon yazımları", "Olay günlüğü"]


def test_can_csv_converts_to_xlsx_and_skips_corrupt_lines(tmp_path):
    from app.log_export import can_csv_to_xlsx
    from app.logger import CanLogger
    lg = CanLogger()
    csv_path = lg.start(str(tmp_path))
    lg.write(1_700_000_000.123, 0x1A0, 3, b"\x01\x02\x03", False, "RX", "ENG_STATUS")
    lg.write(1_700_000_000.223, 0x1FFFFFFF, 8, bytes(range(8)), True, "TX")
    lg.stop()
    with open(csv_path, "a", encoding="utf-8") as f:
        f.write("bozuk satır\nxx,RX,1,,0,,0\n")
    out = str(tmp_path / "can.xlsx")
    assert can_csv_to_xlsx(csv_path, out) == 2
    rows = read_xlsx(out)["CAN kaydı"]
    assert rows[0][2:5] == ["Yön", "CAN ID (hex)", "Mesaj"]
    assert rows[1][2:] == ["RX", "1A0", "ENG_STATUS", 3.0, "01 02 03", False]
    assert rows[2][2:4] == ["TX", "1FFFFFFF"] and rows[2][7] is True
    assert rows[1][1] == pytest.approx(1_700_000_000_123.0)


def test_openpyxl_and_libreoffice_style_readers_accept_the_file(tmp_path):
    openpyxl = pytest.importorskip("openpyxl")
    from app.log_export import SessionInfo, write_session_workbook
    out = str(tmp_path / "o.xlsx")
    write_session_workbook(out, SessionInfo(name="x", record_csv=_record_csv(tmp_path)), [], [])
    wb = openpyxl.load_workbook(out)
    assert "Parametre kaydı" in wb.sheetnames and wb["Parametre kaydı"].freeze_panes == "A2"


# ---------------------------------------------------------------- uçtan uca
@pytest.fixture
def win(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_ending_a_session_saves_an_excel_file_next_to_the_csv_without_touching_the_ecu(win, tmp_path):
    st = win.session_tab
    st.name_edit.setText("Excel testi")
    st.operator_edit.setText("Zeynep")
    st._on_start()
    for i in range(30):
        win.session_recorder.record("input:throttle", 3000 + i)
    win._log_event("KALIBRASYON", "elle bir olay")
    csv_path = win.session_recorder.path
    st._on_stop()
    xlsx = os.path.splitext(csv_path)[0] + ".xlsx"
    assert os.path.exists(csv_path) and os.path.exists(xlsx), "CSV silinmemeli, Excel yanında olmalı"
    data = read_xlsx(xlsx)
    assert "Parametre kaydı" in data and len(data["Parametre kaydı"]) == 31
    assert any("elle bir olay" in str(r) for r in data["Olay günlüğü"])
    assert win._last_excel == xlsx
    assert any("Excel dosyası kaydedildi" in e.message for e in win.event_log.entries)
    assert win.ccp_session.state == "idle" and win.ccp_client is None   # CCP oturumu hiç kurulmadı: ECU'ya yazma yok


def test_excel_failure_keeps_the_csv_and_reports_an_error(win, monkeypatch):
    import app.ui.mainwin.exports as ex
    st = win.session_tab
    st._on_start()
    win.session_recorder.record("input:throttle", 1.0)
    csv_path = win.session_recorder.path
    monkeypatch.setattr(ex, "write_session_workbook", lambda *a, **k: (_ for _ in ()).throw(OSError("disk dolu")))
    st._on_stop()
    assert os.path.exists(csv_path)
    assert any(e.category == "HATA" and "Excel dosyası yazılamadı" in e.message and "CSV" in e.message
               for e in win.event_log.entries)


def test_manual_excel_export_and_can_log_stop_create_files(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    target = str(tmp_path / "elle")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (target, "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    win._log_event("BILGI", "elle aktarılacak olay")
    win.session_tab.excel_button.click()
    out = target + ".xlsx"
    assert os.path.exists(out)
    assert any("elle aktarılacak olay" in str(r) for r in read_xlsx(out)["Olay günlüğü"])
    # CAN kaydı: durdurunca Excel de oluşur; menüden kapatılınca oluşmaz
    win._on_log_start(str(tmp_path / "can"))
    win.can_logger.write(time.time(), 0x100, 2, b"\x01\x02", False, "RX")
    win._on_log_stop()
    assert any(f.endswith(".xlsx") for f in os.listdir(tmp_path / "can"))
    win.log_tab._excel_action.setChecked(False)
    before = set(os.listdir(tmp_path / "can"))
    win._on_log_start(str(tmp_path / "can"))
    win.can_logger.write(time.time(), 0x101, 2, b"\x01\x02", False, "RX")
    win._on_log_stop()
    new = set(os.listdir(tmp_path / "can")) - before
    assert new and not any(f.endswith(".xlsx") for f in new)


# ---------------------------------------------------------------- tüm sayfalardaki girişler Excel'de
@pytest.fixture
def can_win(win, monkeypatch):
    """DBC yüklü, CAN 'bağlı' (gönderilen kareler toplanır), Mühendis rolü."""
    from app.user_roles import Role
    sent = []
    monkeypatch.setattr(type(win.connection), "is_connected", property(lambda s: True))
    monkeypatch.setattr(win.connection, "send", lambda i, d, e: sent.append((i, bytes(d))))
    win.transmit_tab.dbc.load(os.path.join(os.path.dirname(__file__), "data", "sample.dbc"))
    win._on_dashboard_sources_changed()
    win._panel_sources_changed()
    win.current_role = Role.ENGINEER
    win.current_user = "Zeynep"
    win.dashboard_tab.set_role(Role.ENGINEER)
    win.control_panel_tab.set_allowed(True)
    return win


def test_inputs_from_every_page_are_recorded_and_exported_together(can_win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.dashboard_config import SOURCE_CAN, Binding
    win = can_win
    # Ana Sayfa: eyleyici değeri + switch, motor komutu
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 45.0, "Yakıt Pompası Start değeri")
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc_sw"), 1.0, "Yakıt Pompası Start anahtarı")
    assert win._write_binding(Binding(SOURCE_CAN, "CMD", "start_req"), 1.0, "Motor Start", merge=False)
    # Kontrol Paneli
    win._on_panel_apply({"can": {"AIRCRAFT": {"mach": 0.5}}, "cycles": {}, "ccp": []})
    entries = win.input_log.entries
    by = {(e.page, e.kind, e.target): e for e in entries}
    assert by[("Ana Sayfa", "Değer girişi", "OVERRIDE.pump_dc")].new_value == 45.0
    assert ("Ana Sayfa", "Switch (_sw)", "OVERRIDE.pump_dc_sw") in by
    assert ("Ana Sayfa", "Motor komutu", "CMD.start_req") in by
    assert by[("Kontrol Paneli", "Uçak girişi (CAN)", "AIRCRAFT.mach")].new_value == 0.5
    assert {e.user for e in entries} == {"Zeynep"} and all(e.role == "Mühendis" for e in entries)
    # aynı hedefe ikinci giriş: eski değer önceki girilen değerdir
    assert win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 60.0, "Yakıt Pompası Start değeri")
    assert win.input_log.entries[-1].old_value == 45.0 and win.input_log.entries[-1].new_value == 60.0
    # Excel: tüm sayfalardan girişler TEK sayfada
    target = str(tmp_path / "hepsi.xlsx")
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (target, "")))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: QMessageBox.Ok))
    win.session_tab.excel_button.click()
    data = read_xlsx(target)
    rows = data["Girişler (tüm sayfalar)"]
    assert rows[0][1:5] == ["Sayfa", "Tür", "Kaynak", "Hedef (sinyal / parametre)"]
    pages = {r[1] for r in rows[1:]}
    assert {"Ana Sayfa", "Kontrol Paneli"} <= pages
    assert any(r[4] == "OVERRIDE.pump_dc" and r[6] == 60.0 and r[5] == 45.0 for r in rows[1:])
    summary = {r[0]: r[1] for r in data["Özet"][1:] if len(r) > 1}
    assert summary["Giriş / değişiklik sayısı (tüm sayfalar)"] == len(win.input_log.entries)
    assert summary["  Ana Sayfa"] >= 3 and summary["  Kontrol Paneli"] >= 1


def test_failed_attempts_are_recorded_too(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from app.dashboard_config import SOURCE_CAN, Binding
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.Ok))
    assert not win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 5.0, "Pompa değeri")   # CAN bağlı değil
    e = win.input_log.entries[-1]
    assert (e.page, e.ok, e.new_value) == ("Ana Sayfa", False, 5.0) and "CAN bağlı değil" in e.detail


def test_session_inputs_are_also_written_to_a_csv_next_to_the_recording_and_end_up_in_the_session_excel(can_win):
    from app.dashboard_config import SOURCE_CAN, Binding
    win = can_win
    win.session_tab._on_start()
    win._write_binding(Binding(SOURCE_CAN, "OVERRIDE", "pump_dc"), 12.5, "Pompa değeri")
    csv_path = os.path.splitext(win.session_recorder.path)[0] + "_girisler.csv"
    assert os.path.exists(csv_path) and "OVERRIDE.pump_dc" in open(csv_path, encoding="utf-8").read()
    win.session_tab._on_stop()
    xlsx = os.path.splitext(win.session_recorder.path)[0] + ".xlsx"
    rows = read_xlsx(xlsx)["Girişler (tüm sayfalar)"]
    assert any(r[4] == "OVERRIDE.pump_dc" and r[6] == 12.5 for r in rows[1:])
