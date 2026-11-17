"""Arayüzü bloklamayan giriş-çıkış: CCP yazmaları ve periyodik gönderim arka planda yürür, Acil Durdurma
onay sormaz, gönderilen her kare izleme/kayda düşer, olay günlüğü tablosu artımlı güncellenir ve kalıcı
dosyalar yalnızca `.bak` kalmışken de geri yüklenir."""
import os
import threading
import time

import can
import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from app.ccp.client import CCPClient
from app.ccp.simulator import CCPSlaveSimulator

DATA = os.path.join(os.path.dirname(__file__), "data")
CRO, DTO = 0x100, 0x101


# ---------------------------------------------------------------- kalıcı dosyalar
def test_load_json_falls_back_to_bak_when_main_file_is_missing(tmp_path):
    from app.persist import atomic_write_json, load_json
    path = str(tmp_path / "ayar.json")
    assert atomic_write_json(path, {"v": 1}) and atomic_write_json(path, {"v": 2})
    os.remove(path)                       # iki os.replace arasında çökme: geriye yalnızca .bak kalır
    assert load_json(path, {}, dict) == {"v": 1}
    os.remove(path + ".bak")
    assert load_json(path, "varsayılan", dict) == "varsayılan"


# ---------------------------------------------------------------- olay günlüğü tablosu
def _table_rows(t):
    return [(t.table.item(r, 2).text(), t.table.item(r, 3).text()) for r in range(t.table.rowCount())]


@pytest.mark.parametrize("errors_only", [False, True])
def test_event_log_table_incremental_update_matches_full_render(qapp, monkeypatch, errors_only):
    import app.eventlog as eventlog
    from app.ui.event_log_table import EventLogTable
    monkeypatch.setattr(eventlog, "MAX_MEMORY_ENTRIES", 20)      # baştan kırpma da sınansın
    log = eventlog.EventLog()
    t = EventLogTable()
    t.set_errors_only(errors_only)
    renders = []
    original = t._render
    monkeypatch.setattr(t, "_render", lambda: (renders.append(1), original())[1])
    for i in range(60):
        log.add("HATA" if i % 3 == 0 else "CCP", f"olay {i}")
        t.set_entries(log.entries)
    ref = EventLogTable()
    ref.set_errors_only(errors_only)
    ref.set_entries(log.entries)
    assert _table_rows(t) == _table_rows(ref) and t.table.rowCount() > 0
    assert t.error_count == ref.error_count == sum(1 for e in log.entries if e.category == "HATA")
    assert len(renders) <= 1, "her olayda tablo baştan çizilmemeli"
    other = eventlog.EventLog()
    other.add("CCP", "başka liste")
    t.set_entries(other.entries)          # ilgisiz liste: baştan çizilir
    assert t.error_count == 0 and (t.table.rowCount() == (0 if errors_only else 1))


# ---------------------------------------------------------------- TX kareleri
class _Bus:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)

    def recv(self, timeout=None):
        time.sleep(min(timeout or 0.01, 0.01))
        return None

    def shutdown(self):
        pass


def test_every_sent_frame_reaches_the_tx_queue_including_periodic_ones():
    from app.can_worker import CanConnection
    from app.scheduler import PeriodicManager
    conn = CanConnection(bus_factory=lambda **kw: _Bus())
    conn.connect("virtual", "x", 500000)
    try:
        conn.send(0x123, b"\x01", False)
        pm = PeriodicManager(lambda: conn.bus, on_sent=conn.note_tx)
        pm.start("r", 0x300, b"\x07", False, 10)
        time.sleep(0.15)
        pm.stop_all()
        frames = []
        while not conn.tx_queue.empty():
            frames.append(conn.tx_queue.get_nowait())
        periodic = [f for f in frames if f.arbitration_id == 0x300]
        assert frames[0].arbitration_id == 0x123 and len(periodic) >= 5
        assert len({id(f) for f in periodic}) == len(periodic)                 # her kare ayrı kopya
        assert periodic[-1].timestamp > periodic[0].timestamp                  # kendi zaman damgasıyla
    finally:
        conn.disconnect()


def test_main_window_shows_periodic_tx_frames_in_monitor(qapp):
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        w.connection.note_tx(can.Message(arbitration_id=0x321, data=b"\x01\x02", is_extended_id=False))
        w.connection.note_tx(can.Message(arbitration_id=0x321, data=b"\x01\x03", is_extended_id=False))
        w._drain_rx_queue()
        row, _pos = w.monitor_tab.model.row_for("TX", 0x321, False)
        assert row.count == 2 and row.data == b"\x01\x03"
    finally:
        w.close()


# ---------------------------------------------------------------- Kontrol Paneli gönderimi
def test_tx_scheduler_sends_from_a_background_thread_without_the_event_loop(qapp):
    from app.control_panel import TxScheduler
    from app.dbc import DbcDatabase
    dbc = DbcDatabase()
    dbc.load(os.path.join(DATA, "sample.dbc"))
    sent = []
    ts = TxScheduler(dbc, lambda i, d, e: sent.append((threading.get_ident(), bytes(d))))
    try:
        ts.set_values("AIRCRAFT", {"altitude": 8.0}, cycle_ms=10)
        assert ts.is_running("AIRCRAFT") and len(sent) == 1
        time.sleep(0.2)                    # olay döngüsü DÖNMÜYOR: arayüz donmuş gibi
        assert len(sent) >= 8, "arayüz takılıyken periyodik gönderim sürmeli"
        assert {ident for ident, _d in sent[1:]} != {threading.get_ident()}
        first = sent[-1][1]
        ts.set_values("AIRCRAFT", {"altitude": 3.0})
        time.sleep(0.06)
        assert sent[-1][1] != first        # yeni değer periyodik karelere yansır
        ts.stop_all()
        n = len(sent)
        time.sleep(0.06)
        assert len(sent) == n and not ts.is_running("AIRCRAFT")
        ts.resume_all()                    # son değer ve son periyotla (10 ms) sürer
        time.sleep(0.08)
        assert len(sent) >= n + 3
    finally:
        ts.stop_all()


# ---------------------------------------------------------------- CCP: bölünmez diziler + öncelik
@pytest.fixture
def link():
    a = can.Bus(interface="virtual", channel="bg1")
    b = can.Bus(interface="virtual", channel="bg1")
    sim = CCPSlaveSimulator(b, CRO, DTO)
    sim.start()
    cli = CCPClient(a, CRO, DTO, timeout=0.3, retries=1)
    cli.connect()
    yield cli, sim
    cli.disconnect()
    sim.stop()
    a.shutdown()
    b.shutdown()


def test_urgent_write_interleaves_with_a_long_write_without_corrupting_either(link):
    cli, sim = link
    big = bytes((i % 250) + 1 for i in range(3000))        # ~500 parça: acil yazmalar bitmeden bitmez
    errors = []

    def long_write():
        try:
            cli.write_memory(0x1000, big)
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    th = threading.Thread(target=long_write)
    th.start()
    deadline = time.time() + 5
    while 0x1000 not in sim.memory and time.time() < deadline:    # uzun yazma gerçekten başlasın
        time.sleep(0.001)
    alive_after_urgent = []
    for i in range(5):                     # uzun yazma sürerken araya giren "acil" yazmalar
        with cli.urgent():
            cli.write_memory(0x8000 + 2 * i, bytes([0xA0 + i, 0xB0 + i]))
        alive_after_urgent.append(th.is_alive())
    th.join(30)
    assert not errors and not th.is_alive()
    assert alive_after_urgent[0], "acil yazma, uzun yazma bitmeden araya girebilmeli"
    assert bytes(sim.memory[0x1000 + i] for i in range(len(big))) == big       # MTA karışmadı
    for i in range(5):
        assert (sim.memory[0x8000 + 2 * i], sim.memory[0x8001 + 2 * i]) == (0xA0 + i, 0xB0 + i)


# ---------------------------------------------------------------- MainWindow: arka plan CCP işi
@pytest.fixture
def win(qapp, monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append(("critical", a)) or QMessageBox.Ok))
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: shown.append(("warning", a)) or QMessageBox.Yes))
    from app.ui.main_window import MainWindow
    w = MainWindow()
    w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
    w._on_dashboard_sources_changed()
    w._shown = shown
    yield w
    w.close()


def test_ccp_job_keeps_the_ui_responsive_and_rejects_a_second_job(win):
    from app.ui.main_window import CcpBusyError
    seen = {}

    def during():
        seen["tick"] = True
        seen["pages_locked"] = not win.kalibrasyon_tab.isEnabled()
        try:
            win._ccp_job("ikinci", lambda: 1)
        except CcpBusyError:
            seen["busy"] = True

    QTimer.singleShot(60, during)
    main = threading.get_ident()
    result = win._ccp_job("uzun iş", lambda: (time.sleep(0.4), threading.get_ident())[1])
    assert result != main                                    # iş arayüz iş parçacığında çalışmadı
    assert seen == {"tick": True, "pages_locked": True, "busy": True}   # olay döngüsü döndü
    assert win.kalibrasyon_tab.isEnabled() and not win._ccp_busy
    assert win._ccp_job("kısa", lambda: 42) == 42            # iş bitince yenisi başlatılabilir


def test_ccp_job_reraises_known_errors_and_wraps_bus_errors(win):
    from app.ccp import protocol as ccp

    def timeout():
        raise ccp.CCPTimeoutError("cevap yok")

    def bus_error():
        raise can.CanOperationError("adaptör gitti")

    with pytest.raises(ccp.CCPTimeoutError):
        win._ccp_job("x", timeout)
    with pytest.raises(ValueError, match="İletişim hatası"):
        win._ccp_job("x", bus_error)
    assert not win._ccp_busy


def test_window_does_not_close_while_a_ccp_job_is_running(win):
    closed = {}
    QTimer.singleShot(60, lambda: closed.setdefault("accepted", win.close()))
    win._ccp_job("uzun iş", lambda: time.sleep(0.3))
    assert closed == {"accepted": False}


# ---------------------------------------------------------------- Acil Durdurma
def test_mapped_estop_is_sent_without_any_confirmation(win, monkeypatch):
    from app.dashboard_config import SOURCE_CAN, Binding, DashboardConfig, MotorCommand
    sent = []
    monkeypatch.setattr(type(win.connection), "is_connected", property(lambda s: True))
    monkeypatch.setattr(win.connection, "send", lambda i, d, e: sent.append((i, bytes(d))))
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_CAN, "CMD", "estop_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    win._shown.clear()
    win.dashboard_tab.estop_button.click()
    assert sent, "komut tek tıkla gitmeli"
    assert win._shown == [], "Acil Durdurma onay/uyarı penceresi açmamalı"


# ---------------------------------------------------------------- arka planda dosya yükleme
def test_run_with_progress_keeps_event_loop_alive_and_returns_or_raises(qapp):
    from app.ui.background import run_with_progress
    ticks = []
    timer = QTimer()
    timer.setInterval(10)
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start()
    main = threading.get_ident()
    assert run_with_progress(None, "bekleyin", lambda: (time.sleep(0.3), threading.get_ident())[1]) != main
    timer.stop()
    assert len(ticks) >= 5, "iş sürerken olay döngüsü dönmeli"
    assert run_with_progress(None, "kısa", lambda: 7) == 7
    with pytest.raises(ValueError, match="bozuk"):
        run_with_progress(None, "hata", lambda: (_ for _ in ()).throw(ValueError("bozuk dosya")))


def test_a2l_is_parsed_off_the_ui_thread_and_usable_afterwards(qapp, monkeypatch):
    from app.ccp import codec
    from app.ui.a2l_tab import A2LTab
    tab = A2LTab()
    threads = []
    original = tab.db.load
    monkeypatch.setattr(tab.db, "load", lambda path: (threads.append(threading.get_ident()), original(path))[1])
    loaded = []
    tab.a2l_loaded.connect(lambda: loaded.append(1))
    summary = tab.load_path(os.path.join(DATA, "sample.a2l"))
    assert threads and threads[0] != threading.get_ident()
    assert loaded == [1] and tab.tree.topLevelItemCount() == 2
    # Arka planda kurulan dönüşüm nesneleri arayüz iş parçacığında kullanılabilir olmalı.
    for obj in summary.measurements + summary.characteristics:
        assert isinstance(codec.raw_to_physical(obj.compu_method, 10), (int, float))
    with pytest.raises(ValueError):
        tab.load_path(os.path.join(DATA, "yok.a2l"))
    assert tab.db.summary is summary          # başarısız yükleme öncekini bozmaz


# ---------------------------------------------------------------- yapı ve tema
def test_main_window_logic_lives_in_area_modules():
    import inspect
    from app.ui import main_window
    from app.ui.mainwin import calibration, connection, dashboard, panel, profiles
    mw = main_window.MainWindow
    for mod, method in ((connection, "_check_connection_health"), (calibration, "_on_ccp_write"),
                        (dashboard, "_on_estop"), (panel, "_on_panel_apply"), (profiles, "_on_profile_apply")):
        assert inspect.getmodule(getattr(mw, method)) is mod
    assert len(inspect.getsource(main_window).splitlines()) < 700


def test_ui_colours_come_from_the_single_theme_module():
    import re
    from app import theme
    from app.ui import dash_widgets
    assert dash_widgets.DK_RED is theme.DANGER and dash_widgets.DK_GREEN is theme.OK
    tokens = {v.upper() for k, v in vars(theme).items() if k.isupper() and isinstance(v, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", v)}
    ui_dir = os.path.join(os.path.dirname(DATA), "..", "app", "ui")
    offenders = []
    for root, _dirs, files in os.walk(ui_dir):
        for name in files:
            if not name.endswith(".py") or name == "dark_theme.py":
                continue
            text = open(os.path.join(root, name), encoding="utf-8").read()
            # Yalnızca tek başına renk sabiti olan dizgeler ("#C22A1D"): token'ı varsa o kullanılmalı.
            for m in re.finditer(r"#[0-9A-Fa-f]{6}\b", text):
                if m.group(0).upper() in tokens:
                    offenders.append((name, m.group(0)))
    assert not offenders and len(tokens) > 20


# ---------------------------------------------------------------- kısayol ve erişilebilirlik
def test_estop_shortcut_is_application_wide_and_buttons_have_accessible_names(win, monkeypatch):
    from PySide6.QtCore import Qt
    from app.dashboard_config import SOURCE_CAN, Binding, DashboardConfig, MotorCommand
    sent = []
    monkeypatch.setattr(type(win.connection), "is_connected", property(lambda s: True))
    monkeypatch.setattr(win.connection, "send", lambda i, d, e: sent.append((i, bytes(d))))
    cfg = DashboardConfig()
    cfg.estop = MotorCommand(Binding(SOURCE_CAN, "CMD", "estop_req"), 1.0)
    win.dashboard_tab.set_config(cfg)
    assert win._estop_shortcut.context() == Qt.ApplicationShortcut
    assert win._estop_shortcut.key().toString() == "Ctrl+Shift+E"
    win._estop_shortcut.activated.emit()
    assert sent, "kısayol Acil Durdurma'yı göndermeli"
    dt = win.dashboard_tab
    for w in (dt.start_button, dt.stop_button, dt.estop_button, win.header_conn_pill, win.ccp_chip, win.nav_bar):
        assert w.accessibleName(), w
    assert "Ctrl+Shift+E" in dt.estop_button.toolTip()


# ---------------------------------------------------------------- tablo yedeği
def _arr(name="TAB", rows=2, cols=3, address=0x3000):
    from types import SimpleNamespace
    return SimpleNamespace(name=name, address=address, unit="%", kind="ARRAY", axes=[], dims=(rows, cols),
                           index_mode="ROW_DIR", datatype="UWORD", byte_order="MSB_FIRST", compu_method=None,
                           minimum=0.0, maximum=100.0, read_only=False, address_extension=0)


def test_table_backup_roundtrip_is_validated_and_scoped_to_its_object(tmp_path):
    from app.ccp import mapio, table_backup
    folder = str(tmp_path)
    ch = _arr()
    grid = [[1.0, 2.0, 3.0], [4.0, 5.5, 6.0]]
    f1 = table_backup.save(folder, ch, grid)
    f2 = table_backup.save(folder, ch, grid)                       # aynı saniye: üzerine yazılmaz
    assert f1 and f2 and f1 != f2
    table_backup.save(folder, _arr(name="TAB_2"), [[9.0]])          # ad öneki benzer başka nesne
    items = table_backup.list_backups(folder, ch)
    assert len(items) == 2                                          # TAB_2'nin yedeği karışmadı
    assert table_backup.load(items[0].path, ch, mapio.grid_shape(ch)) == grid
    with pytest.raises(ValueError, match="boyut"):
        table_backup.load(items[0].path, _arr(rows=3), (3, 3))
    with pytest.raises(ValueError, match="adres"):
        table_backup.load(items[0].path, _arr(address=0x4000), (2, 3))
    bad = tmp_path / "TAB_20260101_000000.json"
    bad.write_text('{"name": "TAB", "address": 12288, "grid": [[1, "x", 3], [4, 5, 6]]}', encoding="utf-8")
    with pytest.raises(ValueError, match="sayısal"):
        table_backup.load(str(bad), ch, (2, 3))
    (tmp_path / "TAB_20260101_000001.json").write_text("{bozuk", encoding="utf-8")
    assert len(table_backup.list_backups(folder, ch)) == 3          # bozuk dosya listeyi bozmaz


def test_map_editor_restore_loads_backup_as_undoable_edit_without_writing(qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from app.ccp import table_backup
    from app.ui.map_editor_tab import MapEditorTab
    import app.paths as paths
    monkeypatch.setattr(paths, "_cached", str(tmp_path))
    ch = _arr()
    tab = MapEditorTab()
    doc = tab.open_characteristic(ch)
    doc.set_grid_from_ecu([[0.0] * 3, [0.0] * 3])
    assert tab.restore_button.isEnabled()
    table_backup.save(str(tmp_path / "tablo_yedekleri"), ch, [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]])
    monkeypatch.setattr(QInputDialog, "getItem", staticmethod(lambda w, t, l, items, *a, **k: (items[0], True)))
    tab._on_restore_clicked()
    assert doc.current_grid() == [[1.0, 2.0, 3.0], [4.0, 5.0, 6.0]] and doc.is_modified()
    doc.undo()
    assert doc.current_grid() == [[0.0] * 3, [0.0] * 3]


# ---------------------------------------------------------------- zamanlayıcı çözünürlüğü
def test_timer_resolution_is_a_safe_noop_off_windows_and_calls_winmm_on_windows(monkeypatch):
    import sys
    import types
    from app import timer_resolution as tr
    monkeypatch.setattr(tr, "_active", False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert tr.enable_high_resolution_timer() is False
    calls = []
    fake = types.SimpleNamespace(windll=types.SimpleNamespace(winmm=types.SimpleNamespace(
        timeBeginPeriod=lambda ms: calls.append(("begin", ms)) or 0,
        timeEndPeriod=lambda ms: calls.append(("end", ms)) or 0)))
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(tr.atexit, "register", lambda *a, **k: None)
    assert tr.enable_high_resolution_timer(1) is True and calls == [("begin", 1)]
    assert tr.enable_high_resolution_timer(1) is True and calls == [("begin", 1)]      # ikinci çağrı tekrarlamaz
    monkeypatch.setattr(tr, "_active", False)
    bad = types.SimpleNamespace(windll=types.SimpleNamespace(winmm=types.SimpleNamespace(timeBeginPeriod=lambda ms: 97)))
    monkeypatch.setitem(sys.modules, "ctypes", bad)
    assert tr.enable_high_resolution_timer(1) is False


# ---------------------------------------------------------------- CCP koruma (GET_SEED / UNLOCK)
def test_protected_resource_rejects_writes_until_unlocked_with_the_right_key(link):
    from app.ccp import protocol as ccp
    cli, sim = link
    sim.protection_secret = 0xA5A5A5A5
    with pytest.raises(ccp.CCPError) as ei:
        cli.write_memory(0x2000, b"\x01\x02")
    assert ei.value.return_code == ccp.RC_ACCESS_LOCKED
    protected, seed = cli.get_seed(ccp.RESOURCE_CAL)
    assert protected and len(seed) == 4

    def key_fn(s):
        return (int.from_bytes(s, "big") ^ 0xA5A5A5A5).to_bytes(4, "big")

    wrong = lambda s: b"\x00\x00\x00\x00"  # noqa: E731
    with pytest.raises(ccp.CCPError) as ei:
        cli.unlock_resource(ccp.RESOURCE_CAL, wrong)
    assert ei.value.return_code == ccp.RC_ACCESS_DENIED
    assert cli.unlock_resource(ccp.RESOURCE_CAL, key_fn) is True
    cli.write_memory(0x2000, b"\x01\x02", verify=False)
    assert sim.memory[0x2000] == 1 and sim.memory[0x2001] == 2
    with pytest.raises(ccp.CCPError):                      # programlama kaynağı ayrı: hâlâ kilitli
        cli.write_flash_memory(0x4000, b"\x09", clear_first=False)
    assert cli.unlock_resource(ccp.RESOURCE_CAL, lambda s: pytest.fail("açıkken anahtar hesaplanmamalı")) is True


def test_unprotected_resource_needs_no_key(link):
    from app.ccp import protocol as ccp
    cli, _sim = link
    assert cli.get_seed(ccp.RESOURCE_CAL)[0] is False
    assert cli.unlock_resource(ccp.RESOURCE_PGM, lambda s: pytest.fail("kilitsiz kaynak")) is True


# ---------------------------------------------------------------- okunabilirlik
def _luminance(hex_color: str) -> float:
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    lin = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4  # noqa: E731
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def test_map_table_headers_are_readable(qapp):
    """Başlık zemini ile yazı rengi arasında yeterli kontrast (eskiden koyu lacivert zemin + koyu yazıydı)."""
    import re
    from app.ui.map_editor_tab import MapEditorTab
    doc = MapEditorTab().open_characteristic(_arr())
    for header in (doc.table.horizontalHeader(), doc.table.verticalHeader()):
        css = header.styleSheet()
        bg = re.search(r"background:(#[0-9A-Fa-f]{6})", css).group(1)
        fg = re.search(r"(?<!-)color:(#[0-9A-Fa-f]{6})", css).group(1)
        lo, hi = sorted((_luminance(bg), _luminance(fg)))
        assert (hi + 0.05) / (lo + 0.05) >= 4.5, (bg, fg)


# ---------------------------------------------------------------- yerleşim: içerik büyüyünce metin kırpılmaz
def test_trend_range_buttons_are_not_clipped_after_loading_a_dbc(qapp, monkeypatch, tmp_path):
    """DBC yüklenince sol kart genişler; pencere asgari boyutu güncellenmezse Canlı Trendler düğmeleri kırpılırdı."""
    from PySide6.QtTest import QTest
    import app.paths as paths
    monkeypatch.setenv("OPENECU_VERI_KLASORU", str(tmp_path))
    monkeypatch.setattr(paths, "_cached", None)
    from app.ui.main_window import MainWindow
    w = MainWindow()
    try:
        w.show()
        QTest.qWait(50)
        w.transmit_tab.dbc.load(os.path.join(DATA, "sample.dbc"))
        w.transmit_tab.dbc_loaded.emit()
        QTest.qWait(150)
        assert w.width() >= w.minimumWidth() >= w.centralWidget().minimumSizeHint().width()
        trend = w.dashboard_tab.trend
        assert trend.width() >= trend.minimumSizeHint().width(), "trend paneli asgari genişliğinin altına sıkışmış"
        for _secs, b in trend._win_buttons:
            assert b.width() >= b.sizeHint().width(), f"{b.text()!r} düğmesi kırpılıyor"
    finally:
        w.close()
