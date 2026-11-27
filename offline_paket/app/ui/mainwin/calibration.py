"""CCP oturumu ve kalibrasyon: arka plan CCP işleri, tek değer / harita
okuma-yazma, tanılama ve geçmişten geri alma."""
import contextlib
import os
import threading

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QMessageBox,
)

from app.ccp import codec as ccp_codec
from app.ccp import mapio as ccp_mapio
from app.ccp import protocol as ccp_protocol
from app.ccp.worker import IDLE
from app.paths import data_path
from app.user_roles import (
    can_run_diagnostics, can_write_calibration, can_write_flash,
)
from app.ui.mainwin.common import (
    CCP_JOB_INLINE_S, CcpBusyError, _CCP_IO_ERRORS,
)


class CalibrationMixin:

    # ---- CCP oturumu (arka plan iş parçacığı; bkz. app/ccp/worker.py) ----------------------
    @property
    def ccp_client(self):
        """Açık işlemler (yazma, harita, tanılama) için CCPClient benzeri; oturum yoksa None.
        ECU 'yok' iken çağrılar bekletmeden hata verir."""
        return self.ccp_session.client

    @ccp_client.setter
    def ccp_client(self, client):
        if client is None:
            self.ccp_session.stop(graceful=False)
        else:
            self.ccp_session.adopt(client)

    @property
    def ccp_reader(self):
        """Periyodik okuma yapan arayüz zamanlayıcıları için: önbellekten okur, ASLA beklemez."""
        return self.ccp_session.reader

    def _ccp_job(self, label: str, fn):
        """``fn``'i (yalnızca CCP giriş-çıkışı; Qt nesnesine DOKUNMAZ) arka plan iş parçacığında
        çalıştırır ve sonucunu döner / hatasını yükseltir. İş sürerken arayüz DONMAZ: olay döngüsü döner,
        yani Acil Durdurma tıklanabilir, CAN alımı ve periyodik gönderim sürer. Çağıran için eşzamanlı
        görünür (iş bitince döner); bu yüzden aynı anda ikinci bir uzun iş başlatılamaz (CcpBusyError)
        ve iş sürerken Kalibrasyon / Kontrol Paneli sayfaları geçici olarak kilitlenir."""
        if self._ccp_busy:
            raise CcpBusyError("Başka bir CCP işlemi sürüyor; bitince yeniden deneyin.")
        self._ccp_busy = True
        self._job_progress = ""
        box: dict = {}

        def run():
            try:
                box["result"] = fn()
            except BaseException as exc:  # noqa: BLE001 - arayüz iş parçacığında yeniden yükseltilir
                box["error"] = exc

        thread = threading.Thread(target=run, name="ccp-job", daemon=True)
        try:
            thread.start()
            thread.join(CCP_JOB_INLINE_S)
            if thread.is_alive():
                self._wait_ccp_job(label, thread)
        finally:
            self._ccp_busy = False
        err = box.get("error")
        if err is None:
            return box.get("result")
        if isinstance(err, _CCP_IO_ERRORS + (RuntimeError,)):
            raise err
        # Bus/sürücü hatası (ör. iş sürerken bağlantı kesildi): çağıranların ele aldığı türe çevir.
        raise ValueError(f"İletişim hatası: {err}") from err

    def _wait_ccp_job(self, label: str, thread: threading.Thread):
        """İş parçacığı bitene kadar iç olay döngüsünde bekler; meşgul göstergesini yönetir."""
        loop = QEventLoop(self)
        timer = QTimer(self)
        timer.setInterval(15)

        def poll():
            if not thread.is_alive():
                loop.quit()
                return
            extra = f"  {self._job_progress}" if self._job_progress else ""
            self.statusBar().showMessage(f"⏳ {label}…{extra}   (Acil Durdurma kullanılabilir)")

        timer.timeout.connect(poll)
        pages = [p for p in (self.kalibrasyon_tab, self.control_panel_tab) if p.isEnabled()]
        focus = QApplication.focusWidget()
        for page in pages:
            page.setEnabled(False)
        QApplication.setOverrideCursor(Qt.BusyCursor)
        poll()
        timer.start()
        try:
            if thread.is_alive():
                loop.exec()
        finally:
            timer.stop()
            timer.deleteLater()
            QApplication.restoreOverrideCursor()
            for page in pages:
                page.setEnabled(True)
            if focus is not None:
                try:
                    focus.setFocus()
                except RuntimeError:
                    pass                  # odaktaki bileşen bu arada silinmiş
            self._update_connection_display()

    @contextlib.contextmanager
    def _ccp_urgent(self):
        """Arayüz iş parçacığından yapılan kısa/acil yazmalar (Acil Durdurma, eyleyici, override kapatma)
        süren uzun işin parçaları arasına girsin diye (bkz. CCPClient.urgent)."""
        client = self.ccp_client
        enter = getattr(client, "urgent", None) if client is not None else None
        try:
            cm = enter() if enter is not None else None
        except Exception:  # noqa: BLE001 - ECU yok: asıl yazma kendi hatasını verir
            cm = None
        if cm is None:
            yield
            return
        with cm:
            yield

    # ---- MIL model yaşam döngüsü (Start/Pause/Resume/Stop/Reset, hız) -------------------------
    def _on_model_connect(self, model: str, backend: str):
        from app.sim_bridge import matlab_ctl as mc
        if getattr(self, "backend_mode", "") != "MIL" or not self.connection.is_connected:
            QMessageBox.information(self, "Model", "Önce MIL modunda UDP bağlantısını açın (CAN Monitor sekmesi).")
            return
        if self.model_ctl is not None:
            self.model_ctl.close()
        bus = self.connection.bus
        be = mc.UdpControlBackend(bus) if backend == "udp" else mc.MatlabEngineBackend()
        self.simulink_model_name = model
        self.model_ctl = mc.ModelController(be, bus=bus)
        self._model_events_seen = 0
        self.model_ctl.connect(model)
        self._log_event("MODEL", f"Model denetimi bağlanıyor ({be.name}{', ' + model if model else ''})")

    def _on_model_command(self, cmd: str, arg: float):
        ctl = self.model_ctl
        if ctl is None:
            return
        ok = ctl.set_speed(arg) if cmd == "speed" else ctl.command(cmd, arg)
        if not ok:
            self.statusBar().showMessage(f"Model komutu '{cmd}' bu durumda ({ctl.state}) geçersiz.", 4000)

    def _update_model_panel(self):
        """Panel durumu + model olaylarının kayda/olay günlüğüne aktarımı (250 ms; yalnızca GÖSTERGE)."""
        ctl = self.model_ctl
        panel = self.dashboard_tab.sim_panel
        if getattr(self, "backend_mode", "") != "MIL":
            if ctl is not None:
                ctl.close()
                self.model_ctl = None
            return
        from app.sim_bridge import matlab_ctl as mc
        snap = ctl.snapshot() if ctl is not None else {
            "state": mc.NOT_CONNECTED, "error": "", "sim_time": 0.0, "speed": 1.0,
            "udp": self.connection.bus.link_state()[0] if self.connection.is_connected else "—", "udp_text": ""}
        panel.update_from(snap, ctl.allowed if ctl is not None else (lambda _c: False))
        if ctl is not None:
            while self._model_events_seen < len(ctl.events):
                t, text = ctl.events[self._model_events_seen]
                self._model_events_seen += 1
                self.session_recorder.record_event("MODEL", f"{text} (sim_zamanı={snap['sim_time']:.3f})", t)
                self.event_log.add("MODEL", text, user=self.current_user, role=self.current_role.value)

    # ---- MIL kalibrasyon: A2L <-> Simulink parametre eşleme --------------------------------
    def _init_sim_manifest(self):
        from app.persist import load_json
        self.sim_manifest = None
        self.sim_manifest_path = ""
        raw = load_json(data_path("mil_manifest.json"), {}, dict)
        path = raw.get("path", "")
        if path:
            self._load_sim_manifest(path, quiet=True)

    def _load_sim_manifest(self, path: str, quiet: bool = False) -> bool:
        from app.sim_bridge.parameters import ManifestError, load_manifest
        try:
            self.sim_manifest = load_manifest(path)
        except ManifestError as exc:
            self.sim_manifest = None
            if not quiet:
                QMessageBox.warning(self, "Parametre eşleme", str(exc))
            self.connection_tab.manifest_label.setText("eşleme geçersiz")
            return False
        self.sim_manifest_path = path
        self.connection_tab.manifest_label.setText(
            f"{len(self.sim_manifest.params)} parametre · {os.path.basename(path)}")
        return True

    def _on_sim_manifest_requested(self):
        from app.persist import atomic_write_json
        path, _ = QFileDialog.getOpenFileName(self, "A2L-Simulink parametre eşleme (JSON)", "", "JSON (*.json)")
        if not path or not self._load_sim_manifest(path):
            return
        atomic_write_json(data_path("mil_manifest.json"), {"path": path})
        self._log_event("KALIBRASYON", f"MIL parametre eşlemesi yüklendi: {path}")
        self._apply_sim_params()

    def _apply_sim_params(self, *_args):
        """MIL'de ve eşleme + A2L hazırken Kalibrasyon sayfasını model parametre kanalına bağlar: mevcut CCP
        oturumu (önbellekli okuma, geçmiş, harita editörü) aynen kullanılır; yalnızca istemci farklıdır."""
        if getattr(self, "backend_mode", "") != "MIL" or not self.connection.is_connected:
            return
        summary = self.a2l_tab.db.summary
        manifest = getattr(self, "sim_manifest", None)
        if summary is None or manifest is None:
            self.statusBar().showMessage("MIL kalibrasyon: A2L ve parametre eşleme dosyası yükleyin.", 6000)
            return
        from app.sim_bridge.param_client import SimParamClient
        bus = self.connection.bus
        client = SimParamClient(bus, manifest, summary.characteristics, lambda: getattr(bus, "model_state", 0))
        self.ccp_client = client
        names = client.mapped_names()
        self._log_event("KALIBRASYON", f"MIL kalibrasyon kanalı hazır: {len(names)} eşlenmiş A2L parametresi"
                                       + (f"; eşlemesi olmayan {len(client.unmapped)} A2L parametresi okunamaz/yazılamaz"
                                          if client.unmapped else ""))

    # ---- CCP (kalibrasyon) ------------------------------------------------
    def _on_ccp_connect(self, cro_id: int, dto_id: int, station_address: int):
        """Manuel "CCP Bağlan": arka planda (geri çekilmeli) bağlanmayı başlatır; arayüz beklemez,
        durum CCP sekmesinde ve üst şeritteki çipte canlı görünür."""
        if not self.connection.is_connected:
            QMessageBox.warning(
                self, "CAN bağlantısı yok",
                "CCP bağlantısı kurmadan önce CAN Monitor sekmesinden CAN hattına bağlanın.")
            return
        self.ccp_session.start(cro_id, dto_id, station_address)
        self._log_event("CCP", f"CCP bağlanıyor (CRO=0x{cro_id:X}, DTO=0x{dto_id:X}, istasyon=0x{station_address:X})")

    def _auto_ccp_connect(self):
        """CAN bağlanınca otomatik CCP: sabit gecikme + tek deneme yerine arka planda geri çekilmeli
        sonsuz deneme (ECU henüz açılmamış/hazır değilse sürer; ECU gelince kendiliğinden bağlanır)."""
        if not self.connection.is_connected or self.ccp_session.state != IDLE:
            return
        try:
            cro_id, dto_id, station = self.ccp_tab.parsed_connection_params()
        except ValueError as exc:
            self._log_event("HATA", f"Otomatik CCP bağlantısı atlandı: {exc}")
            return
        self.ccp_session.start(cro_id, dto_id, station)

    def _drop_ccp_client(self):
        """CCP oturumunu bus'a HİÇ yazmadan bırakır (adaptör kopmuşken)."""
        was_active = self.ccp_session.state != IDLE
        self.ccp_session.stop(graceful=False)
        if was_active:
            self._log_event("CCP", "CCP bağlantısı düştü (CAN bağlantısı koptu)")
        self._apply_ccp_state(IDLE, "")

    def _ccp_busy_refuse(self, what: str) -> bool:
        """Uzun bir CCP yazımı (harita/flaş) sürerken DISCONNECT/bağlantı kesme yarım yazılmış tablo bırakır:
        iş bitene kadar reddeder (kullanıcıya bildirir). True = reddedildi."""
        if not self._ccp_busy:
            return False
        self.statusBar().showMessage(f"CCP yazımı sürüyor: {what}; iş bitince tekrar deneyin.", 6000)
        return True

    def _on_ccp_disconnect(self):
        if self._ccp_busy_refuse("CCP bağlantısı kesilemez"):
            return
        was_active = self.ccp_session.state != IDLE
        self.ccp_session.stop(graceful=True)
        if was_active:
            self._log_event("CCP", "CCP bağlantısı kesildi")
        self._apply_ccp_state(IDLE, "")

    def _on_ccp_events(self):
        """Arka plan CCP iş parçacığından gelen durum/günlük olaylarını arayüze uygular (100 ms)."""
        for ev in self.ccp_session.poll_events():
            if ev[0] == "state":
                self._apply_ccp_state(ev[1], ev[2])
            elif ev[0] == "log":
                self._log_event(ev[1], ev[2])
        self._update_ccp_chip()

    def _apply_ccp_state(self, state: str, info: str):
        self.ccp_tab.set_session_state(state, self.ccp_session.status_text())
        self._panel_conn_state()
        self._update_ccp_chip()

    def _update_ccp_chip(self):
        if not hasattr(self, "ccp_chip"):
            return
        st = self.ccp_session.state
        text = self.ccp_session.status_text()
        if self.ccp_chip.text() != text or self.ccp_chip.property("state") != st:
            self.ccp_chip.setText(text)
            self.ccp_chip.setProperty("state", st)
            self.ccp_chip.style().unpolish(self.ccp_chip)
            self.ccp_chip.style().polish(self.ccp_chip)
        if hasattr(self, "modas_ribbon"):
            self._modas_sync_status()

    def _on_ccp_read(self):
        if self.ccp_client is None:
            return
        selected = self.ccp_tab.selected_object()
        if selected is None:
            return
        _, obj = selected
        address = getattr(obj, "address", None)
        if address is None:
            self.ccp_tab.set_write_result(
                False, "Bu nesnenin ECU adresi A2L dosyasında tanımlı değil; okunamaz."
            )
            return
        try:
            reading = ccp_codec.read_value(self.ccp_reader, obj)
            raw_value, phys_value = reading.raw, reading.phys
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError) as exc:
            self.ccp_tab.set_read_value("-")
            self.ccp_tab.set_write_result(False, f"Okuma hatası: {exc}")
            return

        unit = f" {obj.unit}" if obj.unit else ""
        display = f"{phys_value:.4g}" if isinstance(phys_value, float) else str(phys_value)
        self.ccp_tab.set_read_value(f"{display}{unit}  (ham: {raw_value})")

    def _on_ccp_write(self, persistent: bool):
        # persistent=False -> RAM (geçici) yazma; persistent=True -> KALICI
        # (flaş) yazma. CCPTab yalnızca güçlü bir onay diyaloğundan sonra
        # persistent=True gönderir (bkz. app/ui/ccp_tab.py _on_write_flash_clicked).
        if self.ccp_client is None:
            return
        if persistent:
            if not can_write_flash(self.current_role):
                self.ccp_tab.set_write_result(
                    False, "Yetki yok: FLAŞ yazmak için Yönetici rolü gerekir "
                           "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin)."
                )
                self._record_denied_write("Kalibrasyon > CCP", "FLAŞ yazımı", "Yetki yok: FLAŞ için Yönetici rolü gerekir")
                return
        elif not can_write_calibration(self.current_role):
            self.ccp_tab.set_write_result(
                False, "Yetki yok: kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir "
                       "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin)."
            )
            self._record_denied_write("Kalibrasyon > CCP", "RAM yazımı", "Yetki yok: Mühendis veya Yönetici rolü gerekir")
            return
        selected = self.ccp_tab.selected_object()
        if selected is None or selected[0] != "characteristic":
            return
        _, obj = selected
        if obj.read_only:
            return
        address = getattr(obj, "address", None)
        if address is None:
            self.ccp_tab.set_write_result(
                False, "Bu nesnenin ECU adresi A2L dosyasında tanımlı değil; yazılamaz."
            )
            return

        text = self.ccp_tab.entered_value_text()
        try:
            phys_value = float(text.replace(",", "."))
        except ValueError:
            self.ccp_tab.set_write_result(False, f"Geçersiz sayı: {text!r}")
            return

        # RAM'e yazarken ONAY SORULMAZ (kullanıcı isteği: "RAM'e Yaz'a tıklayınca
        # direkt yazsın"). Güvenlik katmanları yine de geçerli: rol kontrolü,
        # salt-okunur nesne kontrolü ve her yazımın geçmişe kaydı (geri alınabilir).
        # FLAŞ (kalıcı) yazma için güçlü onay CCPTab'da (_on_write_flash_clicked)
        # alınmaya DEVAM eder.

        # Geri alınabilir bir revizyon geçmişi tutabilmek için yazmadan
        # önce mevcut (eski) değeri en iyi çaba ile okuyoruz; okunamazsa
        # geçmişte "eski değer bilinmiyor" olarak görünür, yazma yine de
        # devam eder.
        client = self.ccp_client
        ext = getattr(obj, "address_extension", 0) or 0

        def work():
            try:
                old = ccp_codec.read_value(client, obj).phys
            except _CCP_IO_ERRORS:
                old = None
            # Doğrulama (sonlu, A2L min/max, READ_ONLY) + güvenli dönüşüm; yazma
            # sonrası geri okuma ile doğrulanır.
            raw_bytes = ccp_codec.encode_for_write(obj, phys_value)
            if persistent:
                client.write_flash_memory(address, raw_bytes, ext, verify=True)
            else:
                client.write_memory(address, raw_bytes, ext, verify=True)
            return old

        try:
            target = "flaşa" if persistent else "RAM'e"
            old_phys = self._ccp_job(f"{obj.name} {target} yazılıyor", work)
        except _CCP_IO_ERRORS as exc:
            kind = "FLAŞ" if persistent else "RAM"
            self.ccp_tab.set_write_result(False, f"Yazma hatası ({kind}): {exc}")
            self._log_event("HATA", f"{obj.name} {kind} yazma hatası: {exc}")
            self.change_tracker.failed(obj.name, str(exc), obj.unit or "")
            self._note_failed_write(obj.name, None, phys_value, obj.unit or "", str(exc), "ccp", persistent=persistent)
            self._record_input("Kalibrasyon > CCP", f"{kind} yazımı", "A2L", obj.name, phys_value, ok=False,
                               detail=str(exc), unit=obj.unit or "")
            return

        kind_label = "FLAŞ, kalıcı" if persistent else "RAM, geçici"
        self.ccp_tab.set_write_result(True, f"Yazıldı ({kind_label}): {obj.name} = {phys_value}")
        self._log_event(
            "KALIBRASYON",
            f"{obj.name} = {phys_value} {obj.unit or ''} ({'FLAŞ' if persistent else 'RAM'}) yazıldı"
        )
        self.calibration_history.add(
            self.current_user, self.current_role.value, obj.name, old_phys, phys_value, obj.unit or "",
            persistent=persistent, source="ccp",
        )
        self.change_tracker.applied(obj.name, old_phys, phys_value, obj.unit or "")
        self._record_cal_sample(obj.name, phys_value, obj.unit or "")
        self._record_input("Kalibrasyon > CCP", "FLAŞ yazımı" if persistent else "RAM yazımı", "A2L", obj.name,
                           phys_value, old_value=old_phys, unit=obj.unit or "")
        self.history_tab.refresh()

    def _record_cal_sample(self, name: str, value, unit: str):
        """Uygulanan kalibrasyon değişimi kayıtta zaman serisi olarak da görünsün (cal:<ad>); olay satırı _log_event'ten."""
        rec = self.session_recorder
        if rec.is_active:
            rec.register_signal(f"cal:{name}", unit, "Kalibrasyon", "wall_clock")
            rec.record(f"cal:{name}", value)

    def _note_failed_write(self, name: str, old, new, unit: str, error: str, source: str, persistent=False):
        """Başarısız yazma da geçmişe girer (write_ok=False): ne denendiği ve neden uygulanmadığı görülsün."""
        try:
            self.calibration_history.add(self.current_user, self.current_role.value, name, old, float(new), unit,
                                         persistent=persistent, detail="", write_ok=False, source=source)
            self.history_tab.refresh()
        except (TypeError, ValueError):
            pass

    def _record_denied_write(self, page: str, kind: str, detail: str, target: str = "", value=None):
        """Reddedilen (yetki/bağlantı) yazma girişimi de kayda geçer: ne denendiği sonradan görülebilsin."""
        self._record_input(page, kind, "A2L", target or "(seçili nesne)", value, ok=False, detail=detail)

    # ---- Tablolar (CURVE/MAP/ARRAY okuma-yazma; Worksheets/Modas pencereleri) ----------
    def _open_in_modas(self, characteristic):
        """CCP sekmesindeki dizi/tablo nesnesini Worksheets (Modas) sayfasında tablo penceresi olarak açar."""
        self.modas_tab.add_label(characteristic)
        self.setCurrentWidget(self.modas_tab)

    def _require_ccp(self, action_text: str) -> bool:
        if self.ccp_client is None:
            QMessageBox.warning(
                self, "CCP bağlantısı yok",
                f"{action_text} önce Kalibrasyon (CCP) sekmesinden CCP bağlantısı kurun."
            )
            return False
        return True

    def _read_map_docs(self, docs) -> int:
        """Tablo dokümanlarını ECU'dan okur (CCP işi arka planda); okunan doküman sayısını döner."""
        todo = []
        for doc in docs:
            if not doc.characteristic.address:
                doc.set_error("Bu nesnenin ECU adresi A2L dosyasında tanımlı değil.")
            else:
                todo.append((doc, doc.characteristic))
        if not todo:
            return 0
        client = self.ccp_client

        def work():
            out = []
            for i, (_doc, ch) in enumerate(todo, 1):
                self._job_progress = f"{i}/{len(todo)}  {ch.name}"
                try:
                    out.append(ccp_mapio.read_grid(client, ch))
                except _CCP_IO_ERRORS as exc:
                    out.append(exc)
            return out

        try:
            results = self._ccp_job("Tablo okunuyor", work)
        except (ValueError, RuntimeError) as exc:
            results = [exc] * len(todo)
        ok = 0
        for (doc, _ch), res in zip(todo, results):
            if isinstance(res, Exception):
                doc.set_error(f"Okuma hatası: {res}")
            else:
                doc.set_grid_from_ecu(res)
                ok += 1
        return ok

    def _read_map_doc(self, doc) -> bool:
        return self._read_map_docs([doc]) == 1

    @staticmethod
    def _count_changed_cells(old_grid, new_grid) -> int:
        if old_grid is None:
            return sum(len(r) for r in new_grid)
        changed = 0
        for r, row in enumerate(new_grid):
            for c, v in enumerate(row):
                try:
                    if abs(old_grid[r][c] - v) > 1e-9:
                        changed += 1
                except IndexError:
                    changed += 1
        return changed

    def _save_table_backup(self, characteristic, old_grid) -> str:
        """Tablo yazımından önceki ECU içeriğini data_dir()/tablo_yedekleri altına JSON olarak yazar
        (Worksheets > tablo penceresi sağ tık > "Yedekten Yükle…" ile geri getirilir). Başarısızsa '' döner."""
        from app.ccp import table_backup
        return table_backup.save(data_path("tablo_yedekleri"), characteristic, old_grid)

    def _write_map_docs(self, docs) -> tuple[int, int]:
        """Tablo dokümanlarını ECU RAM'ine yazar; (yazılan, başarısız) döner. ONAY SORULMAZ (kullanıcı
        isteği); rol kontrolü çağıranda, geçmiş kaydı burada yapılır. CCP işi arka planda yürür: büyük
        tablo yazılırken arayüz donmaz."""
        failed = 0
        todo = []
        for doc in docs:
            if not doc.is_writable():
                doc.set_write_result(False, "Tabloda boş/geçersiz hücre var; önce tüm hücreleri doldurun.")
                failed += 1
            else:
                todo.append((doc, doc.characteristic, doc.current_grid()))
        if not todo:
            return 0, failed
        client = self.ccp_client

        def work():
            out = []
            for i, (_doc, ch, grid) in enumerate(todo, 1):
                self._job_progress = f"{i}/{len(todo)}  {ch.name}"
                try:
                    # write_grid: önce doğrular, ECU'daki mevcut içeriği anlık görüntü alır, yazar, geri
                    # okuyup doğrular; hata olursa eski içeriği geri yazar. Yazmadan ÖNCEKİ gerçek ECU
                    # içeriğini döndürür.
                    out.append(ccp_mapio.write_grid(client, ch, grid))
                except _CCP_IO_ERRORS + (RuntimeError,) as exc:
                    out.append(exc)
            return out

        try:
            results = self._ccp_job("Tablo yazılıyor", work)
        except (ValueError, RuntimeError) as exc:
            results = [exc] * len(todo)
        written = 0
        for (doc, characteristic, grid), old_grid in zip(todo, results):
            if isinstance(old_grid, Exception):
                doc.set_write_result(False, f"Yazma hatası: {old_grid}")
                self._log_event("HATA", f"{characteristic.name} tablo yazma hatası: {old_grid}")
                self._record_input("Worksheets > Tablo", "Tablo yazımı (RAM)", "A2L", characteristic.name,
                                   f"{len(grid)}×{len(grid[0]) if grid else 0} tablo", ok=False, detail=str(old_grid),
                                   unit=characteristic.unit or "")
                failed += 1
                continue
            backup = self._save_table_backup(characteristic, old_grid)
            rows, cols = len(grid), len(grid[0]) if grid else 0
            changed = self._count_changed_cells(old_grid, grid)
            self._record_input("Worksheets > Tablo", "Tablo yazımı (RAM)", "A2L", characteristic.name,
                               f"{rows}×{cols} tablo", old_value=f"{rows}×{cols} tablo",
                               detail=f"{changed} hücre değişti" + (f"; önceki içerik yedeği: {backup}" if backup else ""),
                               unit=characteristic.unit or "")
            doc.set_write_result(True, f"Yazıldı (RAM, geçici): {characteristic.name} — {changed} hücre değişti")
            self._log_event(
                "KALIBRASYON",
                f"Tablo yazıldı (RAM): {characteristic.name} [{rows}x{cols}], {changed} hücre değişti"
            )
            self.calibration_history.add(
                self.current_user, self.current_role.value,
                f"{characteristic.name} [tablo {rows}×{cols}]", None, 0.0, characteristic.unit or "",
                persistent=False, source="worksheets",
                detail=f"{rows}×{cols} tablo yazıldı, {changed} hücre değişti"
                       + (f"; önceki içerik yedeği: {backup}" if backup else ""),
            )
            written += 1
        if written:
            self.history_tab.refresh()
        return written, failed

    def _write_map_doc(self, doc) -> bool:
        return self._write_map_docs([doc])[0] == 1

    # ---- Grafik (canlı Measurement çizimi) ---------------------------------
    def _iter_a2l_samples(self, names: list):
        """Verilen A2L ölçüm adlarını (önbellekten, beklemeden) okuyup ``(ad, ölçüm, Reading)``
        üretir. Okunamayanlar (A2L'de yok, adres yok, ECU cevap vermiyor, bilinmeyen veri tipi)
        sessizce atlanır; ayrıntılı hata gösterimi isteyenler (Ana Sayfa, Worksheets)
        ``ccp_codec.read_value`` ile kendileri okur."""
        if self.ccp_client is None:
            return
        summary = self.a2l_tab.db.summary
        if summary is None:
            return
        by_name = summary.readable_by_name()
        for name in names:
            m = by_name.get(name)
            if m is None or m.address is None:
                continue
            try:
                reading = ccp_codec.read_value(self.ccp_reader, m)
            except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                    ccp_codec.UnknownDatatypeError, ValueError):
                continue
            yield name, m, reading

    # ---- Diagnostics --------------------------------------------------------
    def _on_diag_test_requested(self):
        if self.ccp_client is None:
            self.diagnostics_tab.set_test_result(False, "CCP bağlantısı yok.")
            return
        ok = self.ccp_client.test_connection()
        self.diagnostics_tab.set_test_result(
            ok, "ECU cevap veriyor." if ok else "ECU cevap vermiyor / bağlantı koptu."
        )

    def _on_diag_requested(self, service_number: int, params: bytes):
        if self.ccp_client is None:
            self.diagnostics_tab.set_diag_result("CCP bağlantısı yok.", ok=False)
            return
        if not can_run_diagnostics(self.current_role):
            self.diagnostics_tab.set_diag_result(
                "Yetki yok: DIAG_SERVICE çalıştırmak için Mühendis veya Yönetici rolü gerekir.", ok=False
            )
            return
        try:
            data = self.ccp_client.diag_service(service_number, params)
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError) as exc:
            self.diagnostics_tab.set_diag_result(f"Hata: {exc}", ok=False)
            self.diagnostics_tab.add_diag_log(service_number, params, None, str(exc))
            self._log_event("HATA", f"DIAG_SERVICE 0x{service_number:04X} başarısız: {exc}")
            return
        self.diagnostics_tab.set_diag_result(f"Cevap verisi (5 bayt): {data.hex(' ')}")
        self.diagnostics_tab.add_diag_log(service_number, params, data)
        self._log_event("BILGI", f"DIAG_SERVICE 0x{service_number:04X} params={params.hex(' ') or '-'} cevap={data.hex(' ')}")

    # ---- Kalibrasyon Geçmişi (revizyon geri alma) --------------------------
    def _on_history_revert(self, index: int):
        if self.ccp_client is None:
            QMessageBox.warning(self, "CCP bağlantısı yok", "Geri yazmak için önce CCP bağlantısı kurun.")
            return
        entries = self.calibration_history.entries
        if index < 0 or index >= len(entries):
            return
        entry = entries[index]
        # FLAŞ kaydı FLAŞ'a, RAM kaydı RAM'e geri yazılır — ve flaş geri
        # alma RAM'den daha riskli olduğu için daha yüksek yetki ister.
        required_ok = can_write_flash(self.current_role) if entry.persistent else can_write_calibration(self.current_role)
        if not required_ok:
            role_needed = "Yönetici" if entry.persistent else "Mühendis veya Yönetici"
            QMessageBox.warning(self, "Yetki yok", f"Bu işlem için {role_needed} rolü gerekir.")
            return
        if getattr(entry, "detail", ""):
            QMessageBox.information(
                self, "Tablo kaydı",
                "Bu kayıt bir tablo (harita/dizi) yazımıdır; tek değere geri alınamaz. "
                "Tabloyu ECU'dan okuyup istediğiniz değerlerle tekrar yazabilirsiniz."
            )
            return
        if entry.old_value is None:
            QMessageBox.warning(
                self, "Eski değer bilinmiyor",
                "Bu kayıt için yazmadan önceki değer okunamamıştı, geri yazılamaz."
            )
            return
        summary = self.a2l_tab.db.summary
        if summary is None:
            return
        obj = next((c for c in summary.characteristics if c.name == entry.object_name), None)
        if obj is None:
            QMessageBox.warning(self, "Nesne bulunamadı", "Bu Characteristic artık yüklü A2L'de yok.")
            return
        if getattr(obj, "address", None) is None:
            QMessageBox.warning(self, "Adres yok", "Bu nesnenin ECU adresi A2L'de tanımlı değil; geri yazılamaz.")
            return

        kind_label = "FLAŞ (kalıcı)" if entry.persistent else "RAM (geçici)"
        # Onay yalnızca KALICI (flaş) geri alma için sorulur; RAM geri alma
        # doğrudan yapılır (kullanıcı isteği: RAM'e yazarken onay istenmesin).
        if entry.persistent:
            confirm = QMessageBox.question(
                self, "Eski değere geri yazılsın mı?",
                f"{obj.name}, {entry.new_value} yerine eski değeri {entry.old_value} ile "
                f"{kind_label} olarak geri yazılacak. Devam edilsin mi?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        client = self.ccp_client

        def work():
            raw_bytes = ccp_codec.encode_for_write(obj, entry.old_value)
            ext = obj.address_extension or 0
            if entry.persistent:
                client.write_flash_memory(obj.address, raw_bytes, ext, verify=True)
            else:
                client.write_memory(obj.address, raw_bytes, ext, verify=True)

        try:
            self._ccp_job(f"{obj.name} eski değerine yazılıyor", work)
        except _CCP_IO_ERRORS as exc:
            QMessageBox.critical(self, "Geri yazma hatası", str(exc))
            self._log_event("HATA", f"{obj.name} geri yazma hatası ({kind_label}): {exc}")
            return

        self.calibration_history.add(
            self.current_user, self.current_role.value, obj.name,
            entry.new_value, entry.old_value, obj.unit or "",
            persistent=entry.persistent, source="geri_al",
        )
        self.change_tracker.applied(obj.name, entry.new_value, entry.old_value, obj.unit or "")
        self._record_cal_sample(obj.name, entry.old_value, obj.unit or "")
        self._record_input("Kalibrasyon > Geçmiş", "Geri alma (FLAŞ)" if entry.persistent else "Geri alma (RAM)", "A2L",
                           obj.name, entry.old_value, old_value=entry.new_value, unit=obj.unit or "",
                           detail="Geçmişten eski değere geri yazıldı")
        self.history_tab.refresh()
        self._log_event("KALIBRASYON", f"{obj.name} eski değerine geri yazıldı: {entry.old_value}")
