"""Modas çalışma alanının MainWindow tarafı: ölçüm turu, değer/tablo okuma-yazma, WP/RP, Ribbon düğmeleri, kısayollar.

Güvenlik: yazma yolları CCP sekmesindeki RAM yazımıyla AYNI ilkelere uyar — denetim kaydı, CCP bağlı olma,
``encode_for_write`` doğrulaması, yazma sonrası geri okuma, tablo yedeği + geri alma, giriş kaydı ve kalibrasyon geçmişi.
Modas penceresi yalnızca arayüzdür; ECU'ya doğrudan dokunmaz.
"""

from __future__ import annotations

import logging
import os
import time

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QInputDialog, QMenu, QMessageBox, QToolButton

from app import theme
from app.ccp import codec as ccp_codec
from app.ccp import protocol as ccp_protocol
from app.ccp.worker import IDLE, CONNECTING, LOST, ONLINE
from app.ui.mainwin.common import _CCP_IO_ERRORS
from app.ui.modas.workspace import ModasSheetStore
from app.ui.modas.pages import RP, WP, _same
from app.modas_dataset import DatasetStore, compare
from app.modas_projects import ProjectStore
from app.modas_templates import BUILTINS, TemplateStore, build_specs
from app.paths import data_path
from app.ui.modas.dataset_dialogs import READ_ECU, WRITE_PC, DatasetChoiceDialog, DiffListDialog
from app.ui.modas.project_manager import ProjectManagerDialog
from app.ui.modas.ribbon import glyph_icon
from app.ui.modas.windows import TableWindow, ValueWindow, format_phys
from app.value_text import parse_value_text
from app.user_roles import ROL_ADI

log = logging.getLogger(__name__)

PAGE = "Çalışma Sayfaları"
ECU_STATES = {IDLE: ("off", "ÇEVRİMDIŞI"), CONNECTING: ("wait", "BAĞLANIYOR"), ONLINE: ("on", "ÇEVRİMİÇİ"),
              LOST: ("off", "ECU KAYIP")}


class ModasMixin:

    # ======================================================================
    # Bağlama
    # ======================================================================
    def _wire_modas(self):
        tab, rb = self.modas_tab, self.modas_ribbon
        b = rb.buttons
        self._modas_last_status = None
        self.project_store = ProjectStore(data_path("modas_projects"))
        self._modas_workbase = None                      # (Project, Workbase): açık workbase; Ribbon alanlarına yansır
        self._dataset_checked = False                    # bu CCP bağlantısında PC↔ECU veri seti kontrolü yapıldı mı
        self._dataset_dialog_open = False
        self._dataset_diffs: list = []                   # çözülmemiş (Decide later) PC↔ECU farkları
        self.project_manager = ProjectManagerDialog(self.project_store, self)
        self.project_manager.workbase_opened.connect(self._modas_open_workbase)
        self.project_manager.settings_requested.connect(self.open_settings)

        # çalışma alanı → MainWindow
        tab.read_requested.connect(self._modas_tick)
        tab.value_write_requested.connect(self._modas_write_value)
        tab.table_read_requested.connect(self._modas_read_tables)
        tab.table_write_requested.connect(self._modas_write_table)
        tab.history_requested.connect(self._modas_show_history)
        tab.measuring_changed.connect(self._modas_measuring_changed)
        tab.layout_changed.connect(self._modas_update_diff)
        self.a2l_tab.a2l_loaded.connect(self._modas_on_a2l_loaded)
        self.session_tab.session_started.connect(lambda *_: self._modas_set_record_checked(True))
        self.session_tab.session_stopped.connect(lambda: self._modas_set_record_checked(False))

        # Ribbon düğmeleri
        b["ecu"].clicked.connect(self._open_connection_page)
        b["measure"].clicked.connect(self._modas_on_measure_clicked)
        b["record"].clicked.connect(self._modas_on_record_clicked)
        b["mark"].clicked.connect(self._modas_add_marker)
        b["open_record"].clicked.connect(self._modas_open_record_folder)
        self._modas_marker_count = 0
        b["wp"].clicked.connect(lambda: self._modas_set_page(WP))
        b["rp"].clicked.connect(lambda: self._modas_set_page(RP))
        b["copy_wp_rp"].clicked.connect(self._modas_copy_wp_to_rp)
        b["copy_rp_wp"].clicked.connect(self._modas_copy_rp_to_wp)
        b["read_ecu"].clicked.connect(self._modas_on_read_clicked)
        rb.diff_clicked.connect(self._modas_show_diff_list)
        b["write_ecu"].clicked.connect(self._modas_write_pending)
        b["add_label"].clicked.connect(self._modas_add_selected)
        b["remove_label"].clicked.connect(tab.remove_selected)
        b["add_scope"].clicked.connect(lambda: tab.add_scope(self._selected_var_labels()))
        b["add_actuators"].clicked.connect(tab.add_actuators)
        tab.actuator_state = lambda: dict(self.dashboard_tab._act_open)
        tab.actuator_lock_requested.connect(self._modas_actuator_lock)
        tab.actuator_submit_requested.connect(self._modas_actuator_submit)
        b["add_gauge"].clicked.connect(lambda: [tab.add_gauge(n) for n in self._selected_var_labels()])
        self.template_store = TemplateStore(data_path("modas_templates.json"))
        tmenu = QMenu(b["sheet_template"])
        tmenu.aboutToShow.connect(lambda: self._modas_fill_template_menu(tmenu))
        b["sheet_template"].setMenu(tmenu)
        b["sheet_template"].setPopupMode(QToolButton.InstantPopup)
        b["var_info"].clicked.connect(self._modas_show_info)
        for key, fmt in (("fmt_phys", "phys"), ("fmt_dec", "dec"), ("fmt_hex", "hex"), ("fmt_bin", "bin")):
            b[key].clicked.connect(lambda _c=False, f=fmt: tab.set_format(f))
        b["sheet_new"].clicked.connect(lambda: tab.new_sheet())
        b["sheet_rename"].clicked.connect(lambda: tab.rename_sheet(tab.tabs.currentIndex()))
        b["sheet_delete"].clicked.connect(self._modas_delete_sheet)
        b["save_workfolder"].clicked.connect(self._modas_save)
        b["tile"].clicked.connect(tab.tile)
        b["cascade"].clicked.connect(tab.cascade)
        b["close_all"].clicked.connect(tab.close_all)
        b["toggle_vars"].clicked.connect(lambda on: tab.toggle_variable_list(on))
        b["toggle_log"].clicked.connect(lambda on: tab.toggle_log(on))
        b["project_manager"].clicked.connect(self._modas_project_manager)
        rb._pages_btn_group.idClicked.connect(lambda i: self.open_tool(self._nav_pages[i][2]))

        self._install_modas_shortcuts()
        self._modas_on_a2l_loaded()
        self._modas_sync_status(force=True)

    def _install_modas_shortcuts(self):
        """PDF §8 kısayolları. F-tuşları uygulama kapsamlıdır; biçim kısayolları (Ctrl+B/H/D/P/F/I) yalnızca
        çalışma alanında geçerlidir (başka sayfalardaki metin kutularıyla çakışmasın)."""
        tab, rb = self.modas_tab, self.modas_ribbon

        def app_sc(seq: str, fn):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ApplicationShortcut)
            sc.activated.connect(fn)
            return sc

        def ws_sc(seq: str, fn):
            sc = QShortcut(QKeySequence(seq), tab)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)
            return sc

        self._modas_shortcuts = [
            app_sc("F2", self._modas_toggle_vars),
            app_sc("F3", self._modas_toggle_log),
            app_sc("F5", self._modas_refresh),
            app_sc("F7", self._modas_project_manager),
            app_sc("F8", self._modas_toggle_page),
            app_sc("F9", lambda: self._modas_on_measure_clicked(toggle=True)),
            app_sc("Ctrl+F9", lambda: self._modas_on_record_clicked(toggle=True)),
            app_sc("F4", self._modas_add_marker),
            app_sc("F10", rb.toggle_key_tips),
            app_sc("F12", self._modas_save),
            ws_sc("Ctrl+Z", lambda: self._modas_undo_redo(False)),
            ws_sc("Ctrl+Y", lambda: self._modas_undo_redo(True)),
            ws_sc("Ctrl+P", lambda: tab.set_format("phys")),
            ws_sc("Ctrl+D", lambda: tab.set_format("dec")),
            ws_sc("Ctrl+H", lambda: tab.set_format("hex")),
            ws_sc("Ctrl+B", lambda: tab.set_format("bin")),
            ws_sc("Ctrl+F", self._modas_cycle_format),
            ws_sc("Ctrl+I", self._modas_show_info),
        ]

    # ======================================================================
    # Durum (Ribbon ↔ ECU / A2L / yetki)
    # ======================================================================
    def _modas_sync_status(self, force: bool = False):
        """ECU durum lambası, çevrimiçi/çevrimdışı ve Ribbon alanları; değişmediyse hiçbir şey yapmaz (100 ms çağrılır)."""
        if not hasattr(self, "modas_ribbon"):
            return
        state = self.ccp_session.state
        if state != ONLINE:
            self._dataset_checked = False                # bağlantı düştü: yeniden bağlanınca veri seti tekrar kontrol edilir
        elif not self._dataset_checked and self._modas_workbase is not None:
            self._dataset_checked = True
            QTimer.singleShot(0, self._modas_check_dataset)
        status = (state, self.a2l_tab.db.summary is not None)
        if not force and status == getattr(self, "_modas_last_status", None):
            return
        self._modas_last_status = status
        led, text = ECU_STATES.get(state, ("off", "ÇEVRİMDIŞI"))
        rb = self.modas_ribbon
        rb.set_ecu_state(led, text)
        online = state == ONLINE
        self.modas_tab.set_online(online)
        for key in ("measure", "read_ecu", "write_ecu", "copy_rp_wp"):
            rb.buttons[key].setEnabled(online)
        summary = self.a2l_tab.db.summary
        wbk = self._modas_workbase
        rb.set_field("project", wbk[0].name if wbk else (getattr(summary, "project_name", "") if summary else ""))
        path = getattr(summary, "path", "") if summary else ""
        rb.set_field("a2l", path.replace("\\", "/").rsplit("/", 1)[-1] if path else "")
        try:
            iface = f"{self.connection_tab.current_interface()} / {self.connection_tab.current_channel()}"
        except Exception:  # noqa: BLE001 - sekme henüz hazır değilse alan boş kalır
            iface = ""
        rb.set_field("workbase", wbk[1].name if wbk else iface)

    def _modas_on_a2l_loaded(self):
        self.modas_tab.set_summary(self.a2l_tab.db.summary)
        self.page_model.clear()
        self.undo_stack.clear()                           # yeni A2L: eski adres/etiketlere ait geri alma kayıtları geçersiz
        self.modas_tab.set_reference({})
        self._modas_sync_status(force=True)

    # ======================================================================
    # Ölçüm / okuma
    # ======================================================================
    def _modas_read_window(self, win: ValueWindow) -> bool:
        obj = win.obj
        if getattr(obj, "address", None) is None or not getattr(obj, "datatype", ""):
            win.set_error("ECU adresi / veri tipi A2L'de tanımlı değil.")
            return False
        try:
            reading = ccp_codec.read_value(self.ccp_reader, obj)
        except ccp_protocol.CCPTimeoutError as exc:
            win.set_error(str(exc) or "ECU cevap vermedi")
            return False
        except (ccp_protocol.CCPError, ccp_codec.UnknownDatatypeError, ValueError) as exc:
            win.set_error(str(exc))
            return False
        except Exception as exc:  # noqa: BLE001 - tek pencere hatası tüm turu bozmasın
            win.set_error(f"Okuma hatası: {exc}")
            return False
        win.set_reading(reading)
        self.change_tracker.observe(obj.name, reading.phys, getattr(obj, "unit", "") or "",
                                    writable=win.is_calibration and not getattr(obj, "read_only", False))
        if win.is_calibration:
            self._modas_mark_change(win)
        return True

    def _modas_show_history(self, name: str):
        """Değişiklik okuna tıklanınca: Calibration Tools > Geçmiş sekmesini açar, parametreyi süzüp son kaydı seçer."""
        found = self.history_tab.show_object(name)
        self.open_tool("Kalibrasyon Araçları")
        self.kalibrasyon_tab.inner_tabs.setCurrentWidget(self.history_tab)
        if not found:
            self.statusBar().showMessage(f"{name}: Değişiklik Geçmişi'nde kayıt yok.", 5000)

    def _modas_mark_change(self, win: ValueWindow):
        """Değer penceresinde son değişikliğin okunu / farkını gösterir (ortak ChangeTracker)."""
        name = win.obj.name
        state, arrow, delta, mode = self.change_tracker.change_view(name)
        win.set_change(arrow, delta, self.change_tracker.summary(name), mode, failed=(state == "failed"))

    def _modas_tick(self):
        """Ölçüm turu (250 ms): tüm değer pencereleri arka plan CCP önbelleğinden okunur (arayüz beklemez)."""
        if self.ccp_client is None:
            return
        open_labels = set()
        for win in self.modas_tab.value_windows():
            self._modas_read_window(win)
            open_labels.add(win.label)
            v = win.wp_value()
            if v is not None:
                self.modas_tab.push_sample(win.label, v)       # açık değer penceresi aynı zamanda osiloskop kaynağı
        for name in self.modas_tab.scope_labels():
            if name not in open_labels:
                self._modas_scope_sample(name)
        for g in self.modas_tab.gauge_windows():
            self._modas_gauge_sample(g)
        self.page_model.adopt_missing(self._modas_value_snapshot())
        self._modas_update_diff()

    def _modas_scope_sample(self, name: str):
        """Yalnızca osiloskopta izlenen etiket: arka plan CCP önbelleğinden okunur; okunamazsa örnek eklenmez (boşluk)."""
        obj = self.modas_tab.object_by_name(name)
        if obj is None or getattr(obj, "address", None) is None or not getattr(obj, "datatype", ""):
            return
        try:
            reading = ccp_codec.read_value(self.ccp_reader, obj)
        except Exception:  # noqa: BLE001 - tek sinyal hatası ölçüm turunu bozmasın
            return
        self.modas_tab.push_sample(name, reading.phys)

    def _modas_gauge_sample(self, gauge):
        """Gösterge penceresinin ölçümünü arka plan CCP önbelleğinden okur; okunamazsa gösterge boşalır (eski değer kalmaz)."""
        obj = gauge.obj
        if getattr(obj, "address", None) is None or not getattr(obj, "datatype", ""):
            gauge.set_value(None)
            return
        try:
            gauge.set_value(ccp_codec.read_value(self.ccp_reader, obj).phys)
        except Exception:  # noqa: BLE001 - tek gösterge hatası ölçüm turunu bozmasın
            gauge.set_value(None)

    def _modas_value_snapshot(self) -> dict:
        return {w.label: w.wp_value() for w in self.modas_tab.value_windows() if w.is_calibration and w.wp_value() is not None}

    def _modas_read_tables(self, wins: list):
        if self.ccp_client is None or not wins:
            return
        ok = self._read_map_docs(wins)
        snap = {w.label: w.wp_grid() for w in wins if w._original is not None}
        self.page_model.adopt_missing(snap)
        self.modas_tab.set_reference(self.page_model.reference)
        self._modas_update_diff()
        if ok:
            self._log_event("KALIBRASYON", f"Çalışma sayfası: {ok}/{len(wins)} tablo ECU'dan okundu")

    def _modas_read_all(self):
        """Read data from ECU: çalışma alanındaki tüm etiketler (değerler + tablolar) ECU'dan okunur."""
        if self.ccp_client is None:
            self.statusBar().showMessage("ECU çevrimdışı: önce CCP bağlantısı kurun.", 4000)
            return
        values = self.modas_tab.value_windows()
        for win in values:
            self._modas_read_window(win)
        tables = self.modas_tab.table_windows()
        self._modas_read_tables(tables)
        self.page_model.adopt_missing(self._modas_value_snapshot())
        self.modas_tab.set_reference(self.page_model.reference)
        self._modas_update_diff()
        self._log_event("KALIBRASYON", f"Çalışma sayfası: ECU'dan okundu ({len(values)} değer, {len(tables)} tablo)")
        self.statusBar().showMessage(f"ECU'dan okundu: {len(values)} değer, {len(tables)} tablo", 4000)

    def _modas_refresh(self):
        """F5: Variable list'i A2L'den yeniler; ECU çevrimiçiyse etiketleri yeniden okur."""
        self.modas_tab.var_panel.set_summary(self.a2l_tab.db.summary)
        if self.ccp_client is not None:
            self._modas_read_all()

    def _modas_measuring_changed(self, on: bool):
        b = self.modas_ribbon.buttons["measure"]
        b.blockSignals(True)
        b.setChecked(on)
        b.blockSignals(False)
        b.setText("Durdur" if on else "Başlat")
        b.setIcon(glyph_icon("■" if on else "▶"))
        self.statusBar().showMessage("Ölçüm başladı" if on else "Ölçüm durdu", 2500)

    def _modas_on_measure_clicked(self, _checked: bool = False, toggle: bool = False):
        if toggle:                                  # F9: düğme kapalıysa (çevrimdışı) hiçbir şey yapma
            if not self.modas_ribbon.buttons["measure"].isEnabled():
                return
            self.modas_tab.toggle_measurement()
            return
        want = self.modas_ribbon.buttons["measure"].isChecked()
        if want:
            self.modas_tab.start_measurement()
        else:
            self.modas_tab.stop_measurement()

    # ---- Kayıt ---------------------------------------------------------------------
    def _modas_sync_record_buttons(self):
        b = self.modas_ribbon.buttons
        b["mark"].setEnabled(self._modas_recording())
        path = getattr(self, "_last_record_csv", None)
        b["open_record"].setEnabled(bool(path) and os.path.isdir(os.path.dirname(path)))

    def _modas_set_record_checked(self, on: bool):
        b = self.modas_ribbon.buttons["record"]
        b.blockSignals(True)
        b.setChecked(on)
        b.blockSignals(False)
        b.setText("Durdur" if on else "Başlat")
        b.setIcon(glyph_icon("■" if on else "●", theme.DANGER))
        if on:
            self._modas_marker_count = 0                       # işaretler her kayıtta #1'den başlar
        else:
            path = getattr(self, "_last_record_csv", None)
            if path:
                self.modas_tab.log_panel.add_text(f"Kayıt kaydedildi: {path}")
                self.statusBar().showMessage("Kayıt kaydedildi. Ribbon'da 'Open folder' ile klasörü açabilirsiniz.", 6000)
        self._modas_sync_record_buttons()

    def _modas_on_record_clicked(self, _checked: bool = False, toggle: bool = False):
        st = self.session_tab
        recording = not st.start_button.isEnabled()
        want = (not recording) if toggle else self.modas_ribbon.buttons["record"].isChecked()
        if want and not recording:
            self._modas_prefill_session()
            st.start_button.click()
        elif not want and recording:
            st.stop_button.click()
        self._modas_set_record_checked(not st.start_button.isEnabled())

    def _modas_auto_session_name(self) -> str:
        """Kayıt adı: ``Proje_Workbase_20260101-120000`` (workbase açık değilse yalnızca zaman damgası)."""
        stamp = time.strftime("%Y%m%d-%H%M%S")
        wbk = self._modas_workbase
        return f"{wbk[0].name}_{wbk[1].name}_{stamp}" if wbk is not None else f"Oturum_{stamp}"

    def _modas_prefill_session(self):
        """Tek tuşla kayıt: boş bırakılan oturum adı ve operatör otomatik doldurulur (kullanıcının yazdığı değer korunur)."""
        st = self.session_tab
        if not st.name_edit.text().strip():
            st.name_edit.setText(self._modas_auto_session_name())
        if not st.operator_edit.text().strip() and self.current_user and self.current_user != "bilinmeyen":
            st.operator_edit.setText(self.current_user)

    def _modas_recording(self) -> bool:
        return not self.session_tab.start_button.isEnabled()

    def _modas_add_marker(self):
        """F4: kayıt sürerken olay günlüğüne (Excel / PDF raporda da görünür) zaman damgalı test işareti yazar."""
        if not self._modas_recording():
            self.statusBar().showMessage("İşaret için önce kaydı başlatın (Ctrl+F9).", 3000)
            return
        self._modas_marker_count += 1
        n = self._modas_marker_count
        self._on_record_marker(f"Test işareti #{n}")          # kayıt dosyası (events + ASC), olay günlüğü ve trend
        self.modas_tab.log_panel.add_text(f"İşaret #{n} eklendi ({time.strftime('%H:%M:%S')})")
        self.statusBar().showMessage(f"İşaret #{n} kayda eklendi.", 3000)

    def _modas_open_record_folder(self):
        path = getattr(self, "_last_record_csv", None)
        if path and os.path.isdir(os.path.dirname(path)):
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    # ======================================================================
    # Yazma (CCP sekmesiyle aynı güvenlik ilkeleri: rol, yedek, geri okuma doğrulaması)
    # ======================================================================
    def _modas_write_value(self, win: ValueWindow, text: str):
        obj = win.obj
        unit = obj.unit or ""

        def deny(detail: str):
            self._record_input(PAGE, "RAM yazımı", "A2L", obj.name, text, ok=False, detail=detail, unit=unit)
            win.set_write_result(False, detail)

        if self.ccp_client is None:
            return deny("CCP bağlı değil; değer yazılamadı.")
        if getattr(obj, "address", None) is None or not getattr(obj, "datatype", ""):
            return deny("ECU adresi / veri tipi A2L'de tanımlı değil.")
        try:
            phys = parse_value_text(text)
        except ValueError as exc:
            return deny(str(exc))
        client = self.ccp_client

        def work():
            try:
                old = ccp_codec.read_value(client, obj).phys
            except _CCP_IO_ERRORS:
                old = None
            raw_bytes = ccp_codec.encode_for_write(obj, phys)          # doğrulama: sonlu, tür aralığı, A2L sınırı, READ_ONLY
            client.write_memory(obj.address, raw_bytes, getattr(obj, "address_extension", 0) or 0, verify=True)
            return old

        try:
            old = self._ccp_job("Parametre yazılıyor", work)
        except _CCP_IO_ERRORS + (RuntimeError, ValueError) as exc:
            detail = str(exc) or "ECU cevap vermedi"
            self._log_event("HATA", f"{obj.name} RAM yazma hatası: {detail}")
            self.change_tracker.failed(obj.name, detail, unit)
            self._note_failed_write(obj.name, None, phys, unit, detail, "worksheets")
            self._modas_mark_change(win)
            return deny(detail)
        win.set_write_result(True, "RAM'e yazıldı (ECU'dan doğrulandı).")
        if not self._undo_busy:
            self.undo_stack.push("value", obj.name, old, phys)
        self.macro_recorder.add("value", obj.name, phys)
        self._log_event("KALIBRASYON", f"{obj.name} = {phys} {unit} (RAM, çalışma sayfası) yazıldı")
        self.calibration_history.add(self.current_user, ROL_ADI, obj.name, old, phys, unit,
                                     persistent=False, source="worksheets")
        self.change_tracker.applied(obj.name, old, phys, unit)
        self._modas_mark_change(win)
        self._record_cal_sample(obj.name, phys, unit)
        self._record_input(PAGE, "RAM yazımı", "A2L", obj.name, phys, old_value=old, unit=unit)
        self.history_tab.refresh()
        self._modas_read_window(win)
        self._modas_update_diff()

    def _modas_write_table(self, win: TableWindow):
        if self.ccp_client is None:
            win.set_write_result(False, "CCP bağlı değil; tablo yazılamadı.")
            return
        before = [list(r) for r in win._original] if win._original is not None else None
        self._write_map_docs([win])
        if not win.is_modified():                          # başarılı yazım (yedek + geri okuma doğrulandı)
            if not self._undo_busy and before is not None and before != win.current_grid():
                self.undo_stack.push("table", win.label, before, win.current_grid())
            self.macro_recorder.add("table", win.label, win.current_grid())
        self._modas_update_diff()

    def _modas_undo_redo(self, redo: bool):
        """Ctrl+Z / Ctrl+Y: son başarılı yazımı güvenli yazım yoluyla geri alır / yineler."""
        st = self.undo_stack
        entry = st.peek_redo() if redo else st.peek_undo()
        verb = "Yinelenecek" if redo else "Geri alınacak"
        if entry is None:
            self.statusBar().showMessage(f"{verb} yazım yok.", 3000)
            return
        win = next((w for w in self.modas_tab.windows() if w.label == entry.name
                    and isinstance(w, ValueWindow if entry.kind == "value" else TableWindow)), None)
        if win is None or self.ccp_client is None:
            self.statusBar().showMessage(
                f"{entry.name}: " + ("pencere açık değil." if win is None else "ECU çevrimdışı."), 4000)
            return
        target = entry.new if redo else entry.old
        self._undo_busy = True
        try:
            if entry.kind == "value":
                self._modas_write_value(win, format_phys(target, 9))
                ok = not win.edit.property("bad")
            else:
                win.load_grid_as_edit(target)
                self._modas_write_table(win)
                ok = not win.is_modified()
        finally:
            self._undo_busy = False
        if ok:
            (st.commit_redo if redo else st.commit_undo)()
            self._log_event("KALIBRASYON", f"{entry.name}: {'yinele' if redo else 'geri al'} uygulandı")
            nxt = st.peek_redo() if redo else st.peek_undo()
            tail = f" Sıradaki: {nxt.name}." if nxt else ""
            self.statusBar().showMessage(f"{entry.name}: {'yinelendi' if redo else 'geri alındı'}.{tail}", 4000)
        else:
            self.statusBar().showMessage(f"{entry.name}: yazılamadı; ECU değeri değişmedi.", 5000)

    def _modas_actuator_lock(self, key: str, want_open: bool):
        """Eyleyiciler penceresi → Test Tezgâhı mantığı (eşleşme, oturum onayı, yazım, bırakma tek yerde)."""
        self.dashboard_tab._on_actuator_lock(key, want_open)
        for w in self.modas_tab.actuator_windows():
            w.sync()

    def _modas_actuator_submit(self, key: str, text: str):
        dash = self.dashboard_tab
        dash._act_rows[key]["control"].setText(text)
        dash._on_actuator_submit(key)
        bad = bool(dash._act_rows[key]["control"].property("bad"))
        for w in self.modas_tab.actuator_windows():
            w.mark(key, bad)

    def _modas_write_pending(self):
        """Write data to ECU: bekleyen (sarı) değerleri RAM'e yazar. Kalıcı (Flaş) yazma ayrı ve riskli bir işlemdir:
        Kalibrasyon > CCP sayfasındaki 'Kalıcı Kaydet (Flaş)' akışı (güçlü onay) kullanılır."""
        pend = [w for w in self.modas_tab.value_windows() if w.has_pending]
        tabs = [t for t in self.modas_tab.table_windows() if t.is_modified() and t.is_writable()]
        if not pend and not tabs:
            self.statusBar().showMessage("Yazılacak bekleyen değer yok.", 3000)
            return
        for w in pend:
            self._modas_write_value(w, w.edit.text())
        for t in tabs:
            self._modas_write_table(t)
        self.statusBar().showMessage(f"ECU RAM'ine yazıldı: {len(pend)} değer, {len(tabs)} tablo", 4000)

    # ======================================================================
    # WP / RP
    # ======================================================================
    def _modas_snapshot(self) -> dict:
        return self.modas_tab.wp_snapshot()

    def _modas_update_diff(self, *_):
        if not hasattr(self, "page_model"):
            return
        self.modas_ribbon.set_diff(self.page_model.diff_count(self._modas_snapshot()))

    def _modas_set_page(self, page: str):
        self.page_model.set_active(page)
        self.modas_tab.set_reference(self.page_model.reference)
        self.modas_tab.set_page(page)
        b = self.modas_ribbon.buttons
        for key, p in (("wp", WP), ("rp", RP)):
            b[key].blockSignals(True)
            b[key].setChecked(self.page_model.active == p)
            b[key].blockSignals(False)
        self.statusBar().showMessage(
            "RP (referans) gösteriliyor — salt okunur" if page == RP else "WP (çalışma sayfası) gösteriliyor", 3000)

    def _modas_toggle_page(self):
        self._modas_set_page(RP if self.page_model.active == WP else WP)

    def _modas_copy_wp_to_rp(self):
        if self.page_model.active == RP:
            self._modas_set_page(WP)
        n = self.page_model.copy_wp_to_rp(self._modas_snapshot())
        self._modas_save_dataset()
        self.modas_tab.set_reference(self.page_model.reference)
        self._modas_update_diff()
        self._log_event("KALIBRASYON", f"Çalışma sayfası: WP → RP kopyalandı ({n} etiket, yerel referans)")
        self.statusBar().showMessage(f"WP → RP: {n} etiket referans olarak saklandı (ECU Flaş'ına yazılmadı).", 5000)

    def _modas_copy_rp_to_wp(self):
        if self.page_model.active == RP:
            self._modas_set_page(WP)
        self._modas_restore_plan(self.page_model.restore_plan(self._modas_snapshot()), "RP → WP", "referans (RP)")

    def _modas_restore_labels(self, names: list):
        """Yalnızca verilen etiketleri RP değerine geri yazar (Diff listesi)."""
        full = self.page_model.restore_plan(self._modas_snapshot())
        self._modas_restore_plan({n: full[n] for n in names if n in full}, "RP → WP", "referans (RP)")

    def _modas_restore_plan(self, plan: dict, title: str = "RP → WP", source: str = "RP"):
        if not plan:
            self.statusBar().showMessage("WP ile RP aynı: geri yazılacak değer yok.", 4000)
            return
        if self.ccp_client is None:
            self.statusBar().showMessage("ECU çevrimdışı: RP → WP yapılamaz.", 4000)
            return
        names = ", ".join(sorted(plan)[:8]) + (" …" if len(plan) > 8 else "")
        ans = QMessageBox.question(
            self, title,
            f"{len(plan)} etiket {source} değerine yazılacak (ECU RAM):\n{names}\n\nDevam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        done = 0
        for name, ref in plan.items():
            win = next((w for w in self.modas_tab.windows() if w.label == name), None)
            if isinstance(win, ValueWindow):
                self._modas_write_value(win, format_phys(ref, 9))
                done += 1
            elif isinstance(win, TableWindow):
                win.load_grid_as_edit(ref)
                self._modas_write_table(win)
                done += 1
        self._log_event("KALIBRASYON", f"Çalışma sayfası: {title} yazıldı ({done}/{len(plan)} etiket)")
        self._modas_update_diff()

    def _modas_show_diff_list(self):
        """Diff: WP ≠ RP etiketleri; seçilenler RP değerine geri alınabilir."""
        snap = self._modas_snapshot()
        names = self.page_model.diff_names(snap)
        rows = [(n, snap[n], self.page_model.reference[n]) for n in names]
        ok = self.ccp_client is not None
        reason = "" if ok else "ECU çevrimdışı."
        dlg = DiffListDialog(rows, ok, reason, self)
        if dlg.exec() == DiffListDialog.Accepted and dlg.selected_names():
            self._modas_restore_labels(dlg.selected_names())

    # ======================================================================
    # PC ↔ ECU veri seti (kılavuz §4): workbase'in kayıtlı veri seti ile ECU karşılaştırılır
    # ======================================================================
    def _modas_dataset_store(self):
        wbk = self._modas_workbase
        return DatasetStore(wbk[1].path) if wbk is not None and wbk[1].path else None

    def _modas_save_dataset(self, replace: dict | None = None) -> bool:
        """Workbase açıkken worksheet etiketlerinin WP değerlerini kayıtlı veri sete işler (mevcut diğer etiketler korunur)."""
        store = self._modas_dataset_store()
        if store is None:
            return False
        merged = dict(store.load() or {})
        merged.update(self._modas_snapshot() if replace is None else replace)
        return store.save(merged)

    def _modas_check_dataset(self):
        """ECU ONLINE olunca bir kez: worksheet etiketlerini oku, kayıtlı veri setle karşılaştır; fark varsa kullanıcıya sor."""
        store = self._modas_dataset_store()
        if store is None or self.ccp_client is None:
            return
        if self._ccp_busy or self._dataset_dialog_open:
            QTimer.singleShot(500, self._modas_check_dataset)
            return
        pc = store.load()
        self._modas_read_all()
        ecu = self._modas_snapshot()
        if pc is None:                                   # ilk bağlantı: ECU ilk veri seti olur, sorulacak bir şey yok
            if ecu:
                store.save(ecu)
                self._log_event("KALIBRASYON", f"Veri seti ilk kez kaydedildi ({len(ecu)} etiket)")
            return
        diffs = compare(pc, ecu)
        if not diffs:
            self.statusBar().showMessage("PC ve ECU veri setleri aynı.", 4000)
            self._dataset_diffs = []
            self.modas_ribbon.set_dataset_alert(False)
            return
        self._dataset_diffs = diffs
        self.modas_ribbon.set_dataset_alert(True)
        dlg = DatasetChoiceDialog(diffs, True, "", self)
        self._dataset_dialog_open = True
        try:
            dlg.exec()
        finally:
            self._dataset_dialog_open = False
        self._modas_apply_dataset_choice(dlg.choice, diffs, pc, ecu)

    def _modas_apply_dataset_choice(self, choice: str, diffs: list, pc: dict, ecu: dict):
        n = len(diffs)
        if choice == WRITE_PC:
            done = 0
            for d in diffs:
                win = next((w for w in self.modas_tab.windows() if w.label == d.name), None)
                if isinstance(win, ValueWindow):
                    self._modas_write_value(win, format_phys(d.pc, 9))
                    done += 1
                elif isinstance(win, TableWindow):
                    win.load_grid_as_edit(d.pc)
                    self._modas_write_table(win)
                    done += 1
            left = [d for d in diffs if not self._modas_dataset_written_ok(d)]
            self._modas_update_diff()
            self._dataset_diffs = left
            self.modas_ribbon.set_dataset_alert(bool(left))
            self._log_event("KALIBRASYON", f"Veri seti: PC → ECU yazıldı ({done}/{n} etiket, kalan fark {len(left)})")
            self._record_input(PAGE, "Veri seti PC→ECU", "A2L", "worksheet", f"{done}/{n} etiket", ok=not left,
                               detail="" if not left else f"{len(left)} etiket yazılamadı / doğrulanamadı")
            self.statusBar().showMessage(f"PC veri seti ECU'ya yazıldı ({done}/{n}).", 5000)
        elif choice == READ_ECU:
            self._modas_accept_ecu_dataset(ecu, pc, n)
        else:
            self._log_event("KALIBRASYON", f"Veri seti: karar ertelendi ({n} etiket farklı)")
            self._record_input(PAGE, "Veri seti ertelendi", "A2L", "worksheet", f"{n} etiket farklı", ok=True)
            self.statusBar().showMessage(
                f"PC ve ECU veri setleri farklı ({n} etiket): karar ertelendi. 'Read data from ECU' ECU'yu kabul eder.", 8000)

    def _modas_dataset_written_ok(self, d) -> bool:
        """PC değeri ECU'ya gerçekten yazıldı mı? Değerler ECU'dan DOĞRUDAN (önbelleksiz) okunur; tablolar için
        güvenli yazma yolu zaten geri okuyup doğruladığından 'değişiklik kalmadı' yeterlidir."""
        win = next((w for w in self.modas_tab.windows() if w.label == d.name), None)
        try:
            if isinstance(win, ValueWindow):
                return _same(ccp_codec.read_value(self.ccp_client, win.obj).phys, d.pc)
            if isinstance(win, TableWindow):
                return not win.is_modified() and _same(win.wp_grid(), d.pc)
        except Exception:  # noqa: BLE001 - okunamayan etiket "yazılamadı" sayılır
            return False
        return False

    def _modas_accept_ecu_dataset(self, ecu: dict, pc: dict | None, n: int = 0):
        """ECU değerleri kabul edilir: kayıtlı veri set ve RP ECU değerleriyle yenilenir."""
        self._modas_save_dataset(replace={**(pc or {}), **ecu})
        self.page_model.copy_wp_to_rp(ecu)
        self.modas_tab.set_reference(self.page_model.reference)
        self._dataset_diffs = []
        self.modas_ribbon.set_dataset_alert(False)
        self._modas_update_diff()
        self._log_event("KALIBRASYON", f"Veri seti: ECU → PC kabul edildi ({n} etiket farklıydı)")
        self._record_input(PAGE, "Veri seti ECU→PC", "A2L", "worksheet", f"{n} etiket", ok=True)
        self.statusBar().showMessage("ECU veri seti kabul edildi; PC veri seti güncellendi.", 5000)

    def _modas_on_read_clicked(self):
        """Ribbon 'Read data from ECU': okur; çözülmemiş veri seti farkı varsa bu açık okuma ECU'yu kabul etmektir."""
        pending = list(self._dataset_diffs)
        self._modas_read_all()
        if pending and self.ccp_client is not None:
            store = self._modas_dataset_store()
            self._modas_accept_ecu_dataset(self._modas_snapshot(), store.load() if store else None, len(pending))

    # ======================================================================
    # Ribbon yardımcıları
    # ======================================================================
    def _modas_add_selected(self):
        objs = self.modas_tab.var_panel.selected_objects()
        if not objs:
            self.modas_tab.toggle_variable_list(True)
            self.modas_ribbon.buttons["toggle_vars"].setChecked(True)
            self.modas_tab.var_panel.search.setFocus()
            return
        for o in objs:
            self.modas_tab.add_label(o)

    # ======================================================================
    # Worksheet şablonları
    # ======================================================================
    def _modas_fill_template_menu(self, menu: QMenu):
        menu.clear()
        for t in BUILTINS:
            act = menu.addAction(t.name)
            act.setToolTip(t.description)
            act.triggered.connect(lambda _c=False, n=t.name: self._modas_apply_template(n))
        user = self.template_store.names()
        if user:
            menu.addSeparator()
            for n in user:
                menu.addAction(n).triggered.connect(lambda _c=False, n=n: self._modas_apply_template(n))
        menu.addSeparator()
        menu.addAction("Çalışma sayfasını şablon olarak kaydet…").triggered.connect(self._modas_save_template)
        if user:
            sub = menu.addMenu("Şablonu sil")
            for n in user:
                sub.addAction(n).triggered.connect(lambda _c=False, n=n: self._modas_delete_template(n))

    def _modas_apply_template(self, name: str):
        """Şablondan yeni worksheet kurar. Hiçbir şey ECU'ya yazılmaz, ölçüm başlatılmaz."""
        specs = build_specs(name, self.a2l_tab.db.summary, self.template_store)
        if specs is None:
            self.statusBar().showMessage(f"Şablon bulunamadı: {name}", 4000)
            return
        if not specs:
            self.statusBar().showMessage(f"'{name}' için eşleşen etiket yok (A2L yüklü mü?).", 6000)
            return
        sheet, built, wanted = self.modas_tab.new_sheet_from_specs(name, specs)
        self._log_event("KULLANICI", f"Worksheet şablonu uygulandı: {name} ({built}/{wanted} pencere)")
        note = "" if built == wanted else f" — {wanted - built} etiket A2L'de bulunamadı (A2L yüklenince kurulur)"
        self.statusBar().showMessage(f"'{sheet.name}' worksheet'i kuruldu: {built} pencere{note}.", 6000)
        self._modas_update_diff()

    def _modas_save_template(self):
        name, ok = QInputDialog.getText(self, "Şablon olarak kaydet", "Şablon adı:")
        if not ok or not name.strip():
            return
        if not self.template_store.save(name, self.modas_tab.sheet_specs()):
            QMessageBox.warning(self, "Şablon", "Şablon kaydedilemedi (ad boş ya da hazır şablon adı).")
            return
        self.statusBar().showMessage(f"Şablon kaydedildi: {name.strip()}", 4000)

    def _modas_delete_template(self, name: str):
        if QMessageBox.question(self, "Şablonu sil", f"'{name}' şablonu silinsin mi?") == QMessageBox.Yes:
            self.template_store.delete(name)

    def _selected_var_labels(self) -> list:
        """Variable list'te seçili etiketler (yeni osiloskop bunlarla açılır)."""
        return [o.name for o in self.modas_tab.var_panel.selected_objects()]

    def _modas_show_info(self):
        w = self.modas_tab.active_window()
        if w is not None and hasattr(w, "obj"):
            self.modas_tab.show_info(w.obj)
        elif w is not None:
            self.modas_tab.show_info(w.characteristic)
        else:
            objs = self.modas_tab.var_panel.selected_objects()
            if objs:
                self.modas_tab.show_info(objs[0])

    def _modas_cycle_format(self):
        order = ["phys", "dec", "hex", "bin"]
        w = self.modas_tab.active_window()
        cur = w.fmt if isinstance(w, (ValueWindow, TableWindow)) else "phys"
        self.modas_tab.set_format(order[(order.index(cur) + 1) % len(order)])

    def _modas_toggle_vars(self):
        on = self.modas_tab.toggle_variable_list()
        self.modas_ribbon.buttons["toggle_vars"].setChecked(on)

    def _modas_toggle_log(self):
        on = self.modas_tab.toggle_log()
        self.modas_ribbon.buttons["toggle_log"].setChecked(on)

    def _modas_delete_sheet(self):
        tab = self.modas_tab
        if not tab.delete_sheet(tab.tabs.currentIndex()):
            self.statusBar().showMessage("Son worksheet silinemez.", 3000)

    def _modas_save(self):
        ok = self.modas_tab.save()
        if ok and self._modas_workbase is not None:
            ok = self._modas_save_dataset()                # workbase açıkken PC veri seti de kaydedilir
        self.statusBar().showMessage("Worksheet düzeni kaydedildi." if ok else "Worksheet düzeni kaydedilemedi.", 3000)

    def _modas_project_manager(self):
        self.project_manager.refresh()
        self.project_manager.exec()

    def _modas_switch_layout(self, wb):
        """Çalışma sayfası düzeni çalışma tabanına aittir (``<workbase klasörü>/calisma_sayfalari.json``). Tabanın düzeni
        yoksa mevcut düzen ona devredilir; varsa o düzen yüklenir."""
        if not getattr(wb, "path", "") or not os.path.isdir(wb.path):
            return
        result = self.modas_tab.switch_store(ModasSheetStore(os.path.join(wb.path, "calisma_sayfalari.json")))
        if result == "loaded":
            self._log_event("KULLANICI", f"Çalışma sayfası düzeni yüklendi: {wb.name}")

    def _modas_open_workbase(self, project, wb):
        """Workbase açma (kılavuz §2): A2L yüklenir, iletişim ayarları uygulanır, ECU'ya bağlanmayı dener.
        Hata olursa workbase yine açık sayılır; neden Log'a ve durum çubuğuna yazılır (sessiz hata yok)."""
        self._modas_workbase = (project, wb)
        self.undo_stack.clear()                           # başka çalışma tabanının yazımları geri alınmaz
        self._log_event("KULLANICI", f"Workbase açıldı: {project.name} / {wb.name}")
        self._modas_switch_layout(wb)
        if wb.a2l:
            try:
                self.a2l_tab.load_path(wb.a2l)
            except ValueError as exc:
                self._log_event("HATA", f"Workbase A2L yüklenemedi: {exc}")
                QMessageBox.warning(self, "A2L yüklenemedi", str(exc))
        if wb.protocol != "CCP":
            self._log_event("HATA", f"{wb.protocol} protokolü bu sürümde desteklenmiyor; yalnızca CCP (CAN) kullanılır.")
            self.statusBar().showMessage(f"{wb.protocol} desteklenmiyor — yalnızca CCP.", 6000)
        elif not self.connection.is_connected:
            iface, channel = "pcan", self.connection_tab.current_channel()
            self.connection_tab.apply_profile_values(iface, channel, wb.baudrate)
            iface, channel = self.connection_tab.current_interface(), self.connection_tab.current_channel()
            try:
                self.connection.connect(iface, channel, wb.baudrate)
            except Exception as exc:  # noqa: BLE001 - donanım/sürücü hatası kullanıcıya gösterilir
                self.connection_tab.set_health(False, f"Bağlanılamadı: {exc}")
                self._log_event("HATA", f"Workbase bağlantısı kurulamadı: {exc}")
                self.statusBar().showMessage(f"CAN bağlantısı kurulamadı: {exc}", 8000)
            else:
                self._after_connected(iface, channel, wb.baudrate)
        self._modas_last_status = None
        self._modas_sync_status(force=True)
