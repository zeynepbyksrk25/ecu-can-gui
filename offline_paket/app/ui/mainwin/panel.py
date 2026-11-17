"""Kontrol Paneli, simülasyon girişleri ve Performans sayfası."""

from PySide6.QtWidgets import (
    QMessageBox,
)

from app.ccp import protocol as ccp_protocol
from app import control_panel as cpanel
from app.sim_interface import FLIGHT_DEFS
from app.user_roles import (
    can_override_actuator,
)


class PanelMixin:

    # ---- Kullanıcı / Profil -------------------------------------------------
    # ---- Kontrol Paneli ---------------------------------------------------
    def _panel_send(self, can_id: int, data: bytes, extended: bool):
        self.connection.send(can_id, data, extended)

    def _panel_conn_state(self):
        self.control_panel_tab.set_connection_state(
            self.connection.is_connected, self.ccp_client is not None, self._conn_lost)
        self.performance_tab.set_connection_state(
            self.connection.is_connected, self.ccp_client is not None, self._conn_lost)

    def _panel_sources_changed(self):
        self.control_panel_tab.refresh_sources(self.transmit_tab.dbc, self.a2l_tab.db)
        self.dashboard_tab.sim_inputs.refresh_sources(self.transmit_tab.dbc)
        self.performance_tab.refresh_sources(self.transmit_tab.dbc, self.a2l_tab.db)
        self._push_flight()

    def _push_flight(self):
        vals = self.dashboard_tab.sim_inputs.values()
        self.performance_tab.set_flight({k: v for k, v in vals.items() if k in self._sim_sent})

    def _sync_sim_inputs(self):
        """Kontrol Paneli'nden gönderilen değerleri Ana Sayfa girişlerine yansıtır."""
        panel = self.dashboard_tab.sim_inputs
        vals = {}
        for d in FLIGHT_DEFS:
            m = panel.mapped(d.key)
            if m is None:
                continue
            cur = self.tx_scheduler.values_of(m[0])
            if m[1] in cur:
                vals[d.key] = cur[m[1]]
        if vals:
            panel.set_values(vals)
            self._sim_sent.update(vals)
            self._push_flight()

    def _on_sim_inputs(self, values: dict):
        panel = self.dashboard_tab.sim_inputs

        def record(ok: bool, detail: str, only=None):
            """Her uçuş koşulu girişi (başarısız denemeler dahil) giriş kaydına yazılır."""
            from app.sim_interface import INPUT_BY_KEY
            for key, v in values.items():
                if only is not None and key not in only:
                    continue
                m = panel.mapped(key)
                d = INPUT_BY_KEY.get(key)
                self._record_input("Ana Sayfa", "Uçuş koşulu", "CAN", f"{m[0]}.{m[1]}" if m else key, v, ok=ok,
                                   detail=detail, unit=(d.unit if d else ""))

        if not can_override_actuator(self.current_role):
            panel.set_status("Yetki yok: Mühendis veya Yönetici rolü gerekir.", False)
            record(False, "Yetki yok: Mühendis veya Yönetici rolü gerekir")
            return
        if not self.connection.is_connected:
            panel.set_status("CAN bağlı değil: değerler gönderilemedi.", False)
            record(False, "CAN bağlı değil")
            return
        by_msg: dict[str, dict] = {}
        unmapped = []
        for key, v in values.items():
            m = panel.mapped(key)
            if m is None:
                unmapped.append(key)
                continue
            by_msg.setdefault(m[0], {})[m[1]] = v
        errors = []
        for msg, vals in by_msg.items():
            try:
                self.tx_scheduler.set_values(msg, vals, None, start=not self._panel_paused)
                for sig, v in vals.items():
                    self.control_panel_tab.set_external_applied(msg, sig, v)
            except Exception as exc:
                errors.append(f"{msg}: {exc}")
                record(False, str(exc), only={k for k in values if (panel.mapped(k) or ("",))[0] == msg})
        failed_msgs = {e.split(":", 1)[0] for e in errors}
        record(True, "", only={k for k in values if (panel.mapped(k) or (None,))[0] in by_msg
                                and panel.mapped(k)[0] not in failed_msgs})
        if unmapped:
            record(False, "DBC sinyaline bağlı değil (gönderilmedi)", only=set(unmapped))
        sent = sum(len(v) for v in by_msg.values()) - len(errors)
        panel.set_sent([k for k in values if k not in unmapped], ok=not errors)
        if not errors:
            self._sim_sent.update(k for k in values if k not in unmapped)
        if errors:
            panel.set_status("Gönderilemedi: " + "; ".join(errors), False)
        else:
            txt = f"{sent} değer gönderildi."
            if unmapped:
                txt += f" {len(unmapped)} giriş DBC'ye bağlı olmadığı için atlandı."
            panel.set_status(txt, not unmapped)
            self._log_event("SIMÜLASYON", "Giriş gönderildi: " + ", ".join(
                f"{k}={v:g}" for k, v in values.items() if k not in unmapped))
        self._push_flight()
        self._panel_tx_state()

    def _on_perf_poll(self):
        pt = self.performance_tab
        if self.ccp_client is None:
            return
        for key, info in pt.ccp_poll_targets():
            try:
                pt.set_ccp_value(key, cpanel.ccp_read_value(self.ccp_reader, info))
            except ccp_protocol.CCPTimeoutError:
                pt.set_ccp_error(key, "ECU cevap vermedi")
                continue
            except Exception as exc:
                pt.set_ccp_error(key, str(exc))

    def _panel_tx_state(self):
        self.control_panel_tab.set_tx_running(
            set(self.tx_scheduler.running_messages()), paused=self._panel_paused)

    _panel_paused = False

    def _on_panel_tx_failed(self, message: str, error: str):
        self._log_event("HATA", f"Kontrol Paneli: {message} gönderilemiyor ({error}); hat düzelince "
                                "otomatik yeniden denenecek")
        self.control_panel_tab._set_status(
            f"{message} gönderilemiyor: {error} — hat düzelince otomatik sürecek", False)

    def _on_panel_tx_recovered(self, message: str):
        self._log_event("BAGLANTI", f"Kontrol Paneli: {message} gönderimi yeniden başladı")
        self.control_panel_tab._set_status(f"{message} gönderimi yeniden başladı", True)

    def _on_panel_tx_toggle(self, stop: bool):
        if stop:
            self.tx_scheduler.stop_all()
            self._panel_paused = True
        else:
            self._panel_paused = False
            if self.connection.is_connected:
                self.tx_scheduler.resume_all()
        self._log_event("KONTROL PANELİ", "Uçak girişi gönderimi " + ("durduruldu" if stop else "başlatıldı"))
        self._panel_tx_state()

    def _on_panel_apply(self, changes: dict):
        panel = self.control_panel_tab
        results = []
        if not can_override_actuator(self.current_role):
            panel._set_status("Yetki yok: Mühendis veya Yönetici rolü gerekir.", False)
            return
        can_items = changes.get("can", {})
        if can_items and not self.connection.is_connected:
            panel._set_status("CAN bağlı değil: uçak girişleri gönderilemedi.", False)
            for msg, vals in can_items.items():
                for sig, v in vals.items():
                    self._record_input("Kontrol Paneli", "Uçak girişi (CAN)", "CAN", f"{msg}.{sig}", v, ok=False,
                                       detail="CAN bağlı değil")
            can_items = {}
            changes = dict(changes, can={})
        for msg, vals in can_items.items():
            try:
                self.tx_scheduler.set_values(msg, vals, changes.get("cycles", {}).get(msg),
                                             start=not self._panel_paused)
                ok, err = True, ""
            except Exception as exc:
                ok, err = False, str(exc)
            for sig in vals:
                self._record_input("Kontrol Paneli", "Uçak girişi (CAN)", "CAN", f"{msg}.{sig}", vals[sig], ok=ok,
                                   detail=err)
                key = next((s.key for s in panel._catalog if s.message == msg and s.signal == sig), None)
                if key:
                    results.append({"key": key, "field": "value", "ok": ok, "error": err})
        ccp_items = list(changes.get("ccp", []))
        client = self.ccp_client

        def work():
            out = []
            failed_keys = set()
            for it in ccp_items:
                if it["key"] in failed_keys and it["field"] == "enable":
                    out.append({"key": it["key"], "field": "enable", "ok": False,
                                "error": "değer yazılamadığı için bayrak açılmadı"})
                    continue
                try:
                    cpanel.ccp_write_value(client, it["info"], it["value"])
                    out.append({"key": it["key"], "field": it["field"], "ok": True, "error": ""})
                except Exception as exc:  # noqa: BLE001
                    failed_keys.add(it["key"])
                    out.append({"key": it["key"], "field": it["field"], "ok": False, "error": str(exc)})
            return out

        if ccp_items:
            if client is None:
                error = "CCP bağlı değil"
            else:
                error = ""
                try:
                    job = self._ccp_job("Override değerleri yazılıyor", work)
                    results.extend(job)
                    for it, r in zip(ccp_items, job):
                        self._record_ccp_override(it, r["ok"], r["error"])
                except (ValueError, RuntimeError) as exc:
                    error = str(exc)
            if error:
                results.extend({"key": it["key"], "field": it["field"], "ok": False, "error": error}
                               for it in ccp_items)
                for it in ccp_items:
                    self._record_ccp_override(it, False, error)
        okn = sum(1 for r in results if r["ok"])
        self._log_event("KONTROL PANELİ", f"Uygula: {okn}/{len(results)} değişiklik başarılı")
        panel.apply_finished(results)
        self._sync_sim_inputs()
        self._panel_tx_state()

    def _record_ccp_override(self, item: dict, ok: bool, error: str):
        kind = "Override anahtarı (CCP)" if item.get("field") == "enable" else "Override değeri (CCP)"
        info = item.get("info")
        self._record_input("Kontrol Paneli", kind, "A2L", getattr(info, "name", item.get("key", "?")), item.get("value"),
                           ok=ok, detail=error, unit=getattr(info, "unit", "") or "")

    def _on_panel_poll(self):
        panel = self.control_panel_tab
        if self.ccp_client is None:
            return
        for key, kind, info in panel.ccp_poll_targets():
            try:
                panel.set_ccp_value(key, kind, cpanel.ccp_read_value(self.ccp_reader, info))
            except ccp_protocol.CCPTimeoutError:
                panel.set_ccp_error(key, "ECU cevap vermedi")
                break
            except Exception as exc:
                panel.set_ccp_error(key, str(exc))

    def _on_panel_kill_overrides(self, infos: list):
        panel = self.control_panel_tab
        if self.ccp_client is None:
            panel._set_status("CCP bağlı değil: override kapatılamadı.", False)
            return
        # Override'ları KAPATMAK güvenlik eylemidir: hiçbir rol kısıtına takılmamalı.
        bad = 0
        with self._ccp_urgent():                # arka plandaki uzun yazmanın parçaları arasına girer
            for info in infos:
                try:
                    cpanel.ccp_write_value(self.ccp_client, info, 0, enforce_limits=False)
                    self._record_input("Kontrol Paneli", "Override kapatma (CCP)", "A2L", info.name, 0, unit=info.unit or "")
                except Exception as exc:
                    bad += 1
                    self._record_input("Kontrol Paneli", "Override kapatma (CCP)", "A2L", info.name, 0, ok=False,
                                       detail=str(exc), unit=info.unit or "")
        self._log_event("KONTROL PANELİ", f"Tüm override'lar kapatıldı ({len(infos) - bad}/{len(infos)})")
        if bad == 0:
            panel.overrides_killed()
        else:
            panel._set_status(f"{bad} override kapatılamadı!", False)

    def _on_panel_reload(self):
        try:
            if self.transmit_tab.dbc.path:
                self.transmit_tab.dbc.load(self.transmit_tab.dbc.path)
            if self.a2l_tab.db.path:
                self.a2l_tab.load_path(self.a2l_tab.db.path, notify=False)
        except Exception as exc:
            QMessageBox.warning(self, "Yeniden yükleme hatası", str(exc))
            return
        self.tx_scheduler.refresh_frames()
        self.control_panel_tab.refresh_sources(self.transmit_tab.dbc, self.a2l_tab.db)
