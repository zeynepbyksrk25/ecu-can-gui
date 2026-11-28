"""Kullanıcı ve bağlantı/CCP profilleri."""

from PySide6.QtWidgets import (
    QMessageBox,
)

from app.profiles import ConfigProfile
from app.user_roles import ROL_ADI


class ProfilesMixin:

    def _on_user_applied(self, user_name: str):
        self.current_user = user_name
        if hasattr(self, "header_user_label"):
            self._update_user_label()
        self._log_event("KULLANICI", f"Kullanıcı uygulandı: {user_name} ({ROL_ADI})")

    def _on_profile_save(self, name: str):
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
        ans = QMessageBox.question(self, "Profil silinsin mi?", f"'{name}' profili silinecek.",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if ans != QMessageBox.Yes:
            return
        self.profile_store.delete(name)
        self.user_tab.set_profiles(self.profile_store.names())
        self._log_event("PROFIL", f"Profil silindi: {name}")
