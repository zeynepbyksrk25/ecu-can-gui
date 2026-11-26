"""Kullanıcı rolü ve bağlantı/CCP profilleri."""

from PySide6.QtWidgets import (
    QMessageBox,
)

from app.profiles import ConfigProfile
from app.user_roles import (
    Role, can_manage_profiles, can_override_actuator, can_write_calibration,
)


class ProfilesMixin:

    def _on_role_applied(self, user_name: str, role_value: str):
        self.current_user = user_name
        self.current_role = Role(role_value)
        self.dashboard_tab.set_role(self.current_role)
        if hasattr(self, "header_role_label"):
            self._update_role_label()
        self.control_panel_tab.set_allowed(can_override_actuator(self.current_role))
        self.dashboard_tab.sim_inputs.set_allowed(can_override_actuator(self.current_role))
        self.watch_tab.set_write_allowed(can_write_calibration(self.current_role))
        if hasattr(self, "modas_tab"):
            self._modas_sync_permissions()
        self._log_event("KULLANICI", f"Rol uygulandı: {user_name} ({role_value})")

    def _on_profile_save(self, name: str):
        if not can_manage_profiles(self.current_role):
            QMessageBox.warning(self, "Yetki yok", "Profil kaydetmek için Mühendis veya Yönetici rolü gerekir.")
            return
        if self.profile_store.get(name) is not None:
            ans = QMessageBox.question(
                self, "Profil üzerine yazılsın mı?",
                f"'{name}' profili zaten var; mevcut ayarlarla üzerine yazılacak.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ans != QMessageBox.Yes:
                return
        profile = ConfigProfile(
            name=name,
            interface=self.connection_tab.current_interface(),
            channel=self.connection_tab.current_channel(),
            bitrate=self.connection_tab.current_bitrate(),
            cro_id=self.ccp_tab.cro_edit.text().strip(),
            dto_id=self.ccp_tab.dto_edit.text().strip(),
            station_address=self.ccp_tab.station_edit.text().strip(),
            a2l_path=self.a2l_tab.db.path or "",
        )
        try:
            self.profile_store.upsert(profile)
        except OSError as exc:
            QMessageBox.warning(self, "Profil kaydedilemedi", str(exc))
            return
        self.user_tab.set_profiles(self.profile_store.names())
        self._log_event("PROFIL", f"Profil kaydedildi: {name}")

    def _on_profile_apply(self, name: str):
        profile = self.profile_store.get(name)
        if profile is None:
            return
        if self.connection.is_connected:
            QMessageBox.warning(
                self, "Bağlıyken profil uygulanamaz",
                "Bağlantı/CCP ayarlarını değiştirmeden önce önce bağlantıyı kesin."
            )
            return
        self.connection_tab.apply_profile_values(profile.interface, profile.channel, profile.bitrate)
        self.ccp_tab.cro_edit.setText(profile.cro_id)
        self.ccp_tab.dto_edit.setText(profile.dto_id)
        self.ccp_tab.station_edit.setText(profile.station_address)
        self._log_event("PROFIL", f"Profil uygulandı: {name}")

        if profile.a2l_path:
            try:
                self.a2l_tab.load_path(profile.a2l_path)
            except ValueError as exc:
                QMessageBox.warning(self, "A2L yüklenemedi", str(exc))

    def _on_profile_delete(self, name: str):
        if not can_manage_profiles(self.current_role):
            QMessageBox.warning(self, "Yetki yok", "Profil silmek için Mühendis veya Yönetici rolü gerekir.")
            return
        ans = QMessageBox.question(self, "Profil silinsin mi?", f"'{name}' profili silinecek.",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.profile_store.delete(name)
        self.user_tab.set_profiles(self.profile_store.names())
        self._log_event("PROFIL", f"Profil silindi: {name}")
