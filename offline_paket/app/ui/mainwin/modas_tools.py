"""MainWindow — Modas araçları: Data file manager, Parameter file manager, Macro manager.

Tüm ECU yazımları ``ModasMixin``'deki güvenli yollardan (``_modas_restore_plan`` → ``_modas_write_value`` /
``_modas_write_table``) geçer: rol denetimi, yedek, geri okuma doğrulaması, kayıt. Dosyalar ve macro'lar
tek başlarına hiçbir şey yazmaz.
"""
from __future__ import annotations

import logging
import os
import time

from PySide6.QtWidgets import QFileDialog, QInputDialog, QMenu, QMessageBox, QToolButton

from app.modas_datafiles import (DataFileError, ParameterFolder, compare_with_file, export_values, load_values,
                                 safe_file_name)
from app.modas_macros import MacroError, MacroRecorder, MacroStore, describe, missing_labels
from app.paths import data_path
from app.ui.modas.dataset_dialogs import DiffListDialog
from app.ui.modas.tools_dialogs import MacroDialog, ParameterFilesDialog
from app.ui.modas.windows import TableWindow, ValueWindow, format_phys

log = logging.getLogger(__name__)


class ModasToolsMixin:
    # ======================================================================
    # Bağlama
    # ======================================================================
    def _wire_modas_tools(self):
        b = self.modas_ribbon.buttons
        self.macro_recorder = MacroRecorder()
        self._macro_dialog = None
        menu = QMenu(b["data_file"])
        menu.addAction("Save WP to file…").triggered.connect(lambda: self._modas_save_wp_file())
        menu.addAction("Compare file with WP…").triggered.connect(lambda: self._modas_compare_file())
        b["data_file"].setMenu(menu)
        b["data_file"].setPopupMode(QToolButton.InstantPopup)
        b["param_files"].clicked.connect(self._modas_parameter_files)
        b["macros"].clicked.connect(self._modas_macro_manager)

    # ======================================================================
    # Dosya yardımcıları
    # ======================================================================
    def _modas_project_label(self) -> tuple:
        wbk = self._modas_workbase
        return (wbk[0].name, wbk[1].name) if wbk is not None else ("", "")

    def _modas_params_folder(self) -> ParameterFolder:
        wbk = self._modas_workbase
        folder = os.path.join(wbk[0].path, "DATA", "PARAMETERS") if wbk is not None else data_path("parametre_dosyalari")
        return ParameterFolder(folder)

    def _modas_macro_store(self) -> MacroStore:
        wbk = self._modas_workbase
        return MacroStore(os.path.join(wbk[0].path, "MACRO") if wbk is not None else data_path("makrolar"))

    def _modas_save_wp_file(self, path: str | None = None):
        snap = self._modas_snapshot()
        if not snap:
            self.statusBar().showMessage("Kaydedilecek değer yok: worksheet'e ayar değeri ekleyip ECU'dan okuyun.", 5000)
            return False
        if path is None:
            proj, wbn = self._modas_project_label()
            default = f"{proj + '_' if proj else ''}{wbn + '_' if wbn else ''}{time.strftime('%Y%m%d-%H%M%S')}.json"
            path, _ = QFileDialog.getSaveFileName(self, "Save WP to file", default, "Parametre dosyası (*.json)")
            if not path:
                return False
        try:
            n = export_values(path, snap, *self._modas_project_label())
        except DataFileError as exc:
            QMessageBox.warning(self, "Data file", str(exc))
            return False
        self._log_event("KALIBRASYON", f"WP dosyaya kaydedildi: {path} ({n} etiket)")
        self.statusBar().showMessage(f"WP dosyaya kaydedildi ({n} etiket): {path}", 6000)
        return True

    def _modas_compare_file(self, path: str | None = None) -> tuple:
        """Dosyayı WP ile karşılaştırır; seçilen farklar onaydan sonra ECU RAM'ine yazılır. ``(ok, mesaj)`` döner."""
        if path is None:
            path, _ = QFileDialog.getOpenFileName(self, "Compare file with WP", "", "Parametre dosyası (*.json)")
            if not path:
                return False, ""
        try:
            fvals = load_values(path)
        except DataFileError as exc:
            QMessageBox.warning(self, "Data file", str(exc))
            return False, str(exc)
        snap = self._modas_snapshot()
        diffs, only_file, _only_wp = compare_with_file(snap, fvals)
        note = f" {len(only_file)} etiket worksheet'te açık olmadığı için karşılaştırılamadı." if only_file else ""
        if not diffs:
            msg = "Dosya ile WP aynı." + note
            self.statusBar().showMessage(msg, 6000)
            return True, msg
        can = self.ccp_client is not None
        reason = "" if can else "ECU çevrimdışı."
        dlg = DiffListDialog([(d.name, d.pc, d.ecu) for d in diffs], can, reason, self,
                             headers=("Label", "WP", "File"), title="Compare file with WP",
                             action_text="Write selected (File → WP)",
                             intro=f"{len(diffs)} etiketin WP değeri dosyadakinden farklı.{note}")
        if dlg.exec() == DiffListDialog.Accepted and dlg.selected_names():
            plan = {d.name: d.ecu for d in diffs if d.name in set(dlg.selected_names())}
            self._modas_restore_plan(plan, "Dosya → WP", "dosyadaki")
            return True, f"{len(plan)} etiket için yazma istendi."
        return True, f"{len(diffs)} fark var; yazılmadı." + note

    # ======================================================================
    # Parameter file manager
    # ======================================================================
    def _modas_parameter_files(self):
        folder = self._modas_params_folder()
        dlg = ParameterFilesDialog(folder, self._modas_param_save, self._modas_compare_file_result,
                                   self._modas_param_delete, self)
        dlg.exec()

    def _modas_param_save(self):
        snap = self._modas_snapshot()
        if not snap:
            return False, "Kaydedilecek değer yok: worksheet'e ayar değeri ekleyip ECU'dan okuyun."
        name, ok = QInputDialog.getText(self, "Save WP as", "Dosya adı:", text=time.strftime("%Y%m%d-%H%M%S"))
        if not ok:
            return None
        try:
            name = safe_file_name(name)
            folder = self._modas_params_folder()
            overwrite = False
            if os.path.exists(folder.path_for(name)):
                if QMessageBox.question(self, "Save WP as", f"'{name}' zaten var; üzerine yazılsın mı?") != QMessageBox.Yes:
                    return False, "Kaydedilmedi."
                overwrite = True
            path = folder.save(name, snap, *self._modas_project_label(), overwrite=overwrite)
        except (DataFileError, OSError) as exc:
            return False, str(exc)
        self._log_event("KALIBRASYON", f"Parametre dosyası kaydedildi: {path} ({len(snap)} etiket)")
        return True, f"Kaydedildi ({len(snap)} etiket): {os.path.basename(path)}"

    def _modas_compare_file_result(self, path: str):
        return self._modas_compare_file(path)

    def _modas_param_delete(self, name: str):
        if QMessageBox.question(self, "Delete", f"'{name}' parametre dosyası silinsin mi?") != QMessageBox.Yes:
            return False, "Silinmedi."
        try:
            ok = self._modas_params_folder().delete(name)
        except (DataFileError, OSError) as exc:
            return False, str(exc)
        if ok:
            self._log_event("KALIBRASYON", f"Parametre dosyası silindi: {name}")
        return ok, "Silindi." if ok else "Dosya bulunamadı."

    # ======================================================================
    # Macro manager
    # ======================================================================
    def _modas_macro_manager(self):
        if self._macro_dialog is None or not self._macro_dialog.isVisible():
            self._macro_dialog = MacroDialog(self._modas_macro_store(), self.macro_recorder, self._modas_macro_toggle,
                                             self._modas_macro_play, self._modas_macro_delete, self)
        self._macro_dialog.show()
        self._macro_dialog.raise_()

    def _modas_macro_toggle(self):
        """Record ↔ Stop & save. Kayıt sırasında yapılan BAŞARILI yazımlar eklenir."""
        rec = self.macro_recorder
        if not rec.active:
            rec.start()
            self._log_event("KALIBRASYON", "Macro kaydı başladı")
            return True, "● Kayıt başladı: worksheet'te değer / tablo / test girişi yazımları macro'ya eklenir."
        steps = rec.stop()
        self._log_event("KALIBRASYON", f"Macro kaydı bitti ({len(steps)} adım)")
        if not steps:
            return False, "Hiç yazım yapılmadı; macro kaydedilmedi."
        name, ok = QInputDialog.getText(self, "Save macro", "Macro adı:")
        if not ok or not name.strip():
            return False, "Macro kaydedilmedi."
        store = self._modas_macro_store()
        try:
            overwrite = name.strip() in store.names()
            if overwrite and QMessageBox.question(self, "Save macro", f"'{name.strip()}' zaten var; üzerine yazılsın mı?") != QMessageBox.Yes:
                return False, "Macro kaydedilmedi."
            store.save(name, steps, overwrite=overwrite)
        except (MacroError, OSError) as exc:
            return False, str(exc)
        return True, f"Macro kaydedildi: {name.strip()} ({len(steps)} adım)"

    def _modas_macro_delete(self, name: str):
        if QMessageBox.question(self, "Delete macro", f"'{name}' macro'su silinsin mi?") != QMessageBox.Yes:
            return False, "Silinmedi."
        try:
            ok = self._modas_macro_store().delete(name)
        except (MacroError, OSError) as exc:
            return False, str(exc)
        return ok, "Silindi." if ok else "Macro bulunamadı."

    def _modas_macro_play(self, name: str):
        """Macro'yu oynatır: önce tüm önkoşullar denetlenir (çevrimiçi, yetki, etiketler açık), sonra özet onaylanır; adımlar
        sırayla güvenli yoldan yazılır ve İLK başarısızlıkta durur."""
        try:
            steps = self._modas_macro_store().load(name)
        except MacroError as exc:
            return False, str(exc)
        if self.macro_recorder.active:
            return False, "Kayıt sürerken oynatılamaz."
        if self.ccp_client is None:
            return False, "ECU çevrimdışı: macro oynatılamaz."
        windows = {w.label: w for w in self.modas_tab.windows()}
        missing = missing_labels(steps, set(windows))
        if missing:
            return False, "Worksheet'te açık olmayan etiketler var: " + ", ".join(missing[:6]) + (" …" if len(missing) > 6 else "")
        wrong = [s["label"] for s in steps if not self._modas_step_window_ok(s, windows[s["label"]])]
        if wrong:
            return False, "Etiket türü macro adımıyla uyuşmuyor: " + ", ".join(sorted(set(wrong))[:6])
        listing = "\n".join(f"{i}. {describe(s)}" for i, s in enumerate(steps[:12], 1)) + ("\n…" if len(steps) > 12 else "")
        if QMessageBox.question(self, "Play macro", f"'{name}' macro'su {len(steps)} adımı ECU RAM'ine yazacak:\n\n{listing}\n\n"
                                "Devam edilsin mi?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return False, "Oynatılmadı."
        for i, s in enumerate(steps, 1):
            if not self._modas_play_step(s, windows[s["label"]]):
                self._log_event("HATA", f"Macro '{name}' {i}. adımda durdu: {describe(s)}")
                return False, f"{i}. adımda durdu ({describe(s)}); sonraki adımlar uygulanmadı."
        self._log_event("KALIBRASYON", f"Macro oynatıldı: {name} ({len(steps)} adım)")
        self.statusBar().showMessage(f"Macro oynatıldı: {name} ({len(steps)} adım)", 5000)
        return True, f"Macro oynatıldı ({len(steps)} adım)."

    @staticmethod
    def _modas_step_window_ok(step: dict, win) -> bool:
        return ((step["kind"] == "value" and isinstance(win, ValueWindow) and win.is_calibration)
                or (step["kind"] == "table" and isinstance(win, TableWindow)))

    def _modas_play_step(self, step: dict, win) -> bool:
        """Tek adımı güvenli yoldan yazar; başarıyı pencerenin sonuç durumundan okur."""
        was_recording = self.macro_recorder.active                # oynatma kendi yazımlarını kaydetmesin
        self.macro_recorder.active = False
        try:
            if step["kind"] == "value":
                self._modas_write_value(win, format_phys(step["value"], 9))
                return win.edit.property("bad") is not True and not win.has_pending
            if step["kind"] == "table":
                win.load_grid_as_edit(step["value"])
                self._modas_write_table(win)
                return not win.is_modified()
            return False
        finally:
            self.macro_recorder.active = was_recording
