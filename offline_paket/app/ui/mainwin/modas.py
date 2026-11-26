"""Modas çalışma alanının MainWindow tarafı: ölçüm turu, değer/tablo okuma-yazma, WP/RP, Ribbon düğmeleri, kısayollar.

Güvenlik: yazma yolları Parametre Listesi / Harita Editörü ile AYNIDIR — rol denetimi (Mühendis/Yönetici), CCP bağlı olma,
``encode_for_write`` doğrulaması, yazma sonrası geri okuma, tablo yedeği + geri alma, giriş kaydı ve kalibrasyon geçmişi.
Modas penceresi yalnızca arayüzdür; ECU'ya doğrudan dokunmaz.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMessageBox

from app import theme
from app.ccp import codec as ccp_codec
from app.ccp import protocol as ccp_protocol
from app.ccp.worker import IDLE, CONNECTING, LOST, ONLINE
from app.ui.mainwin.common import _CCP_IO_ERRORS
from app.ui.modas.pages import RP, WP
from app.ui.modas.project_manager import ProjectManagerDialog
from app.ui.modas.ribbon import glyph_icon
from app.ui.modas.windows import TableWindow, ValueWindow, format_phys
from app.ui.watch_tab import parse_value_text
from app.user_roles import can_write_calibration

log = logging.getLogger(__name__)

PAGE = "Worksheets"
ECU_STATES = {IDLE: ("off", "OFFLINE"), CONNECTING: ("wait", "CONNECTING"), ONLINE: ("on", "ONLINE"),
              LOST: ("off", "ECU LOST")}


class ModasMixin:

    # ======================================================================
    # Bağlama
    # ======================================================================
    def _wire_modas(self):
        tab, rb = self.modas_tab, self.modas_ribbon
        b = rb.buttons
        self._modas_last_status = None
        self.project_manager = ProjectManagerDialog(self)
        self.project_manager.load_a2l_requested.connect(self.a2l_tab._on_load)
        self.project_manager.connection_requested.connect(self._open_connection_page)
        self.project_manager.settings_requested.connect(self.open_settings)

        # çalışma alanı → MainWindow
        tab.read_requested.connect(self._modas_tick)
        tab.value_write_requested.connect(self._modas_write_value)
        tab.table_read_requested.connect(self._modas_read_tables)
        tab.table_write_requested.connect(self._modas_write_table)
        tab.measuring_changed.connect(self._modas_measuring_changed)
        tab.layout_changed.connect(self._modas_update_diff)
        self.a2l_tab.a2l_loaded.connect(self._modas_on_a2l_loaded)
        self.session_tab.session_started.connect(lambda *_: self._modas_set_record_checked(True))
        self.session_tab.session_stopped.connect(lambda: self._modas_set_record_checked(False))

        # Ribbon düğmeleri
        b["ecu"].clicked.connect(self._open_connection_page)
        b["measure"].clicked.connect(self._modas_on_measure_clicked)
        b["record"].clicked.connect(self._modas_on_record_clicked)
        b["wp"].clicked.connect(lambda: self._modas_set_page(WP))
        b["rp"].clicked.connect(lambda: self._modas_set_page(RP))
        b["copy_wp_rp"].clicked.connect(self._modas_copy_wp_to_rp)
        b["copy_rp_wp"].clicked.connect(self._modas_copy_rp_to_wp)
        b["read_ecu"].clicked.connect(self._modas_read_all)
        b["write_ecu"].clicked.connect(self._modas_write_pending)
        b["add_label"].clicked.connect(self._modas_add_selected)
        b["remove_label"].clicked.connect(tab.remove_selected)
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
        rb._pages_btn_group.idClicked.connect(self.nav_bar.setCurrentIndex)
        self.nav_bar.currentChanged.connect(rb.select_page)
        rb.select_page(self.nav_bar.currentIndex())

        self._install_modas_shortcuts()
        self._modas_sync_permissions()
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
            app_sc("F10", rb.toggle_key_tips),
            app_sc("F12", self._modas_save),
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
        status = (state, self.a2l_tab.db.summary is not None, self.current_role)
        if not force and status == getattr(self, "_modas_last_status", None):
            return
        self._modas_last_status = status
        led, text = ECU_STATES.get(state, ("off", "OFFLINE"))
        rb = self.modas_ribbon
        rb.set_ecu_state(led, text)
        online = state == ONLINE
        self.modas_tab.set_online(online)
        for key in ("measure", "read_ecu", "write_ecu", "copy_rp_wp"):
            rb.buttons[key].setEnabled(online)
        summary = self.a2l_tab.db.summary
        rb.set_field("project", getattr(summary, "project_name", "") if summary else "")
        path = getattr(summary, "path", "") if summary else ""
        rb.set_field("a2l", path.replace("\\", "/").rsplit("/", 1)[-1] if path else "")
        try:
            iface = f"{self.connection_tab.current_interface()} / {self.connection_tab.current_channel()}"
        except Exception:  # noqa: BLE001 - sekme henüz hazır değilse alan boş kalır
            iface = ""
        rb.set_field("workbase", iface)

    def _modas_sync_permissions(self):
        self.modas_tab.set_allowed(can_write_calibration(self.current_role))
        self._modas_last_status = None
        self._modas_sync_status(force=True)

    def _modas_on_a2l_loaded(self):
        self.modas_tab.set_summary(self.a2l_tab.db.summary)
        self.page_model.clear()
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
        return True

    def _modas_tick(self):
        """Ölçüm turu (250 ms): tüm değer pencereleri arka plan CCP önbelleğinden okunur (arayüz beklemez)."""
        if self.ccp_client is None:
            return
        for win in self.modas_tab.value_windows():
            self._modas_read_window(win)
        self.page_model.adopt_missing(self._modas_value_snapshot())
        self._modas_update_diff()

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
            self._log_event("KALIBRASYON", f"Worksheets: {ok}/{len(wins)} tablo ECU'dan okundu")

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
        self._log_event("KALIBRASYON", f"Worksheets: ECU'dan okundu ({len(values)} değer, {len(tables)} tablo)")
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
        b.setText("Stop" if on else "Start")
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
    def _modas_set_record_checked(self, on: bool):
        b = self.modas_ribbon.buttons["record"]
        b.blockSignals(True)
        b.setChecked(on)
        b.blockSignals(False)
        b.setText("Stop" if on else "Start")
        b.setIcon(glyph_icon("■" if on else "●", theme.DANGER))

    def _modas_on_record_clicked(self, _checked: bool = False, toggle: bool = False):
        st = self.session_tab
        recording = not st.start_button.isEnabled()
        want = (not recording) if toggle else self.modas_ribbon.buttons["record"].isChecked()
        if want and not recording:
            st.start_button.click()
        elif not want and recording:
            st.stop_button.click()
        self._modas_set_record_checked(not st.start_button.isEnabled())

    # ======================================================================
    # Yazma (Parametre Listesi / Harita Editörü ile aynı güvenlik yolu)
    # ======================================================================
    def _modas_write_value(self, win: ValueWindow, text: str):
        obj = win.obj
        unit = obj.unit or ""

        def deny(detail: str):
            self._record_input(PAGE, "RAM yazımı", "A2L", obj.name, text, ok=False, detail=detail, unit=unit)
            win.set_write_result(False, detail)

        if self.ccp_client is None:
            return deny("CCP bağlı değil; değer yazılamadı.")
        if not can_write_calibration(self.current_role):
            return deny("Yetki yok: kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir.")
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
            return deny(detail)
        win.set_write_result(True, "RAM'e yazıldı (ECU'dan doğrulandı).")
        self._log_event("KALIBRASYON", f"{obj.name} = {phys} {unit} (RAM, Worksheets) yazıldı")
        self.calibration_history.add(self.current_user, self.current_role.value, obj.name, old, phys, unit,
                                     persistent=False)
        self._record_input(PAGE, "RAM yazımı", "A2L", obj.name, phys, old_value=old, unit=unit)
        self.history_tab.refresh()
        self._modas_read_window(win)
        self._modas_update_diff()

    def _modas_write_table(self, win: TableWindow):
        if self.ccp_client is None:
            win.set_write_result(False, "CCP bağlı değil; tablo yazılamadı.")
            return
        if not can_write_calibration(self.current_role):
            win.set_write_result(False, "Yetki yok: tablo yazmak için Mühendis veya Yönetici rolü gerekir.")
            self._record_denied_write(PAGE, "Tablo yazımı (RAM)", "Yetki yok: Mühendis veya Yönetici rolü gerekir",
                                      win.characteristic.name)
            return
        self._write_map_docs([win])
        self._modas_update_diff()

    def _modas_write_pending(self):
        """Write data to ECU: bekleyen (sarı) değerleri RAM'e yazar. Kalıcı (Flaş) yazma ayrı ve riskli bir işlemdir:
        Kalibrasyon > CCP sayfasındaki 'Kalıcı Kaydet (Flaş)' akışı (Yönetici + onay) kullanılır."""
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
        self.modas_tab.set_reference(self.page_model.reference)
        self._modas_update_diff()
        self._log_event("KALIBRASYON", f"Worksheets: WP → RP kopyalandı ({n} etiket, yerel referans)")
        self.statusBar().showMessage(f"WP → RP: {n} etiket referans olarak saklandı (ECU Flaş'ına yazılmadı).", 5000)

    def _modas_copy_rp_to_wp(self):
        if self.page_model.active == RP:
            self._modas_set_page(WP)
        plan = self.page_model.restore_plan(self._modas_snapshot())
        if not plan:
            self.statusBar().showMessage("WP ile RP aynı: geri yazılacak değer yok.", 4000)
            return
        if self.ccp_client is None:
            self.statusBar().showMessage("ECU çevrimdışı: RP → WP yapılamaz.", 4000)
            return
        if not can_write_calibration(self.current_role):
            QMessageBox.warning(self, "Yetki yok", "Kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir.")
            return
        names = ", ".join(sorted(plan)[:8]) + (" …" if len(plan) > 8 else "")
        ans = QMessageBox.question(
            self, "RP → WP",
            f"{len(plan)} etiket referans (RP) değerine geri yazılacak (ECU RAM):\n{names}\n\nDevam edilsin mi?",
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
        self._log_event("KALIBRASYON", f"Worksheets: RP → WP geri yazıldı ({done}/{len(plan)} etiket)")
        self._modas_update_diff()

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
        cur = w.fmt if isinstance(w, ValueWindow) else "phys"
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
        self.statusBar().showMessage("Worksheet düzeni kaydedildi." if ok else "Worksheet düzeni kaydedilemedi.", 3000)

    def _modas_project_manager(self):
        s = self.a2l_tab.db.summary
        self.project_manager.set_info({
            "A2L dosyası": getattr(s, "path", "") if s else "",
            "Proje": getattr(s, "project_name", "") if s else "",
            "Modül": getattr(s, "module_name", "") if s else "",
            "Ölçüm / kalibrasyon nesnesi": f"{len(s.measurements)} / {len(s.characteristics)}" if s else "",
            "CAN arayüzü": self.connection_tab.current_interface(),
            "CAN kanalı": self.connection_tab.current_channel(),
            "CCP durumu": self.ccp_session.status_text(),
            "Kullanıcı / rol": f"{self.current_user} / {self.current_role.value}",
            "Worksheet düzeni": self.modas_tab.store.path or "",
        })
        self.project_manager.exec()
