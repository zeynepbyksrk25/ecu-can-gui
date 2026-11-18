"""Ana Sayfa: eşleşme (Binding) yazımı, motor komutları ve Acil Durdurma, gösterge/grafik beslemesi,
oturum parametre kaydı ve Çalışma Alanı okuması."""
import os

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QMessageBox,
)

from app.ccp import codec as ccp_codec
from app.ccp import protocol as ccp_protocol
from app import control_panel as cpanel
from app.dashboard_config import (
    COMMAND_VALUE, CONTROL_KEYS, GAUGE_KEYS, SENSOR_KEYS, SOURCE_A2L, SOURCE_CAN, Binding,
)
from app.paths import data_path
from app.ui.mainwin.common import (
    SAFETY_A2L_ATTEMPTS, SAFETY_REPEAT_COUNT, SAFETY_REPEAT_MS,
)


class DashboardMixin:

    # ---- Ana Sayfa (Dashboard) -----------------------------------------------
    # Her değişken bir Binding ile tanımlıdır: CAN (DBC mesaj.sinyal) ya da A2L (CCP).
    def _write_binding(self, binding: Binding, value: float, label: str, merge: bool = True,
                       safety: bool = False) -> bool:
        """Bir Binding'e değer yazar (DashboardTab.writer). Başarısızlıkta kullanıcıyı
        bilgilendirir ve False döner. ``merge``: eyleyici/sensör yazımı. Değer, Kontrol Paneli ve Ana Sayfa
        girişleriyle AYNI değer tablosundan (``tx_scheduler``) gider: aynı mesajın diğer sinyalleri korunur
        (değer + anahtar aynı mesajda olabilir) ve iki ekran birbirinin değerini ezmez. ``merge=False``:
        motor komutları (Başlat/Durdur/Acil Durdurma), tek sinyallik tek seferlik darbe.
        ``safety``: güvenlik komutu (Acil Durdurma): A2L min/max + READ_ONLY ve DBC min/max denetimi
        komutu ENGELLEMEZ (sınır dışıysa günlüğe not düşülür); değer veri tipine / bit genişliğine
        sığmıyorsa yine gönderilmez."""
        if not binding.is_set:
            QMessageBox.warning(self, "Eşleşme yok", f"{label} için eşleşme tanımlı değil (⚙ Eşleşmeler).")
            return False
        if binding.source == SOURCE_A2L:
            return self._write_a2l(binding, value, label, safety, merge)
        return self._write_can(binding, value, label, merge, safety)

    @staticmethod
    def _input_kind(label: str, merge: bool, safety: bool) -> str:
        if safety or not merge:
            return "Motor komutu"
        return "Switch (_sw)" if label.endswith("anahtarı") else "Değer girişi"

    def _write_can(self, binding: Binding, value: float, label: str, merge: bool = True,
                   safety: bool = False, extra: dict | None = None) -> bool:
        """``extra``: aynı mesajın ek sinyalleri ({sinyal: değer}); komut + _sw tek karede gitsin diye."""
        if not self.connection.is_connected:
            QMessageBox.warning(self, "CAN bağlantısı yok",
                                f"{label} göndermeden önce CAN hattına bağlanın.")
            self._record_input("Ana Sayfa", self._input_kind(label, merge, safety), "CAN",
                               f"{binding.message}.{binding.signal}", value, ok=False,
                               detail=f"{label}: CAN bağlı değil")
            return False
        vals = {binding.signal: value}
        if extra:
            vals.update(extra)
        try:
            if merge and not safety:
                # Ortak değer tablosu: Kontrol Paneli'nin periyodik göndericisi aynı mesajı eski değerle
                # geri yazmasın (eyleyici anahtarı bir periyotta 0'a dönerdi). Mesaj periyodik sürer.
                can_id, data = self.tx_scheduler.set_values(binding.message, vals, None,
                                                            start=not self._panel_paused)
                extended = bool(self.transmit_tab.dbc.get_message(binding.message).is_extended_frame)
                self.control_panel_tab.set_external_applied(binding.message, binding.signal, value)
            elif safety:
                try:
                    self.transmit_tab.dbc.encode(binding.message, dict(vals))
                except ValueError as exc:
                    # Sınır (min/max) dışı olabilir: güvenlik komutu engellenmez. Gerçekten kodlanamıyorsa
                    # (bit genişliği) aşağıdaki strict=False kodlama da hata verir ve gönderilmez.
                    self._log_event("MOTOR", f"{label}: DBC sınır denetimi güvenlik komutu olduğu için atlandı ({exc})")
                can_id, data, extended = self.transmit_tab.dbc.encode(binding.message, dict(vals), strict=False)
                self.connection.send(can_id, data, extended)
            else:
                can_id, data, extended = self.transmit_tab.dbc.encode(binding.message, dict(vals))
                self.connection.send(can_id, data, extended)
        except Exception as exc:  # cantools/python-can çeşitli hata tipleri fırlatabilir
            hint = ("\n\nDeğer sinyalin bit genişliğine sığmıyor: yapılandırılmış komut değerini "
                    "(⚙ Eşleşmeler) düzeltin.") if safety else ""
            QMessageBox.critical(self, f"{label} gönderilemedi", f"{exc}{hint}")
            self._log_event("HATA", f"{label} gönderilemedi: {exc}")
            self._record_input("Ana Sayfa", self._input_kind(label, merge, safety), "CAN",
                               f"{binding.message}.{binding.signal}", value, ok=False, detail=f"{label}: {exc}")
            return False
        self._drain_tx_queue()
        self._log_event("EYLEYICI", f"{label} [CAN {binding.message}.{binding.signal}] = {value:g} "
                                    f"({self.current_user}/{self.current_role.value})")
        self._record_input("Ana Sayfa", self._input_kind(label, merge, safety), "CAN",
                           f"{binding.message}.{binding.signal}", value, detail=label)
        if safety:
            self._repeat_safety_frame(label, can_id, data, extended, SAFETY_REPEAT_COUNT)
        return True

    def _repeat_safety_frame(self, label: str, can_id: int, data: bytes, extended: bool, remaining: int):
        """Güvenlik komutunun (Acil Durdurma / Durdur) AYNI karesini kısa aralıkla birkaç kez daha yollar.
        Tek karenin hatta/ECU tarafında kaçma ihtimaline karşı (ECU'nun komutu mandallayıp mandallamadığı
        bilinmiyor); değer değişmediği için tekrar zararsızdır. Arayüzü bloklamaz; hata olursa günlüğe yazar."""
        if remaining <= 0:
            self._log_event("MOTOR", f"{label}: {SAFETY_REPEAT_COUNT + 1} kare gönderildi")
            return
        timer = QTimer(self)
        timer.setSingleShot(True)

        def step():
            timer.deleteLater()
            try:
                if not self.connection.is_connected:
                    raise RuntimeError("Bağlantı yok.")
                self.connection.send(can_id, data, extended)
            except Exception as exc:  # noqa: BLE001
                self._log_event("HATA", f"{label}: tekrar karesi gönderilemedi ({exc}); ilk kare gönderilmişti")
                return
            self._repeat_safety_frame(label, can_id, data, extended, remaining - 1)

        timer.timeout.connect(step)
        timer.start(SAFETY_REPEAT_MS)

    def _a2l_info(self, name: str):
        summary = self.a2l_tab.db.summary
        if summary is None:
            return None
        for coll in (summary.measurements, summary.characteristics):
            for m in coll:
                if m.name == name:
                    return m
        return None

    def _write_a2l(self, binding: Binding, value: float, label: str, safety: bool = False, merge: bool = True) -> bool:
        if self.ccp_client is None:
            QMessageBox.warning(self, "CCP bağlı değil",
                                f"{label} A2L üzerinden yazılmadan önce CCP bağlantısı kurun.")
            self._record_input("Ana Sayfa", self._input_kind(label, merge, safety), "A2L", binding.a2l_name, value,
                               ok=False, detail=f"{label}: CCP bağlı değil")
            return False
        info = self._a2l_info(binding.a2l_name)
        try:
            if info is None:
                raise ValueError(f"A2L'de '{binding.a2l_name}' bulunamadı")
            if info.address is None:
                raise ValueError(f"'{binding.a2l_name}' için ECU adresi yok")
            if safety:
                try:
                    ccp_codec.validate_write(info, value)
                except ccp_codec.WriteValidationError as exc:
                    self._log_event("MOTOR", f"{label}: A2L sınır/READ_ONLY denetimi güvenlik komutu olduğu için "
                                             f"atlandı ({exc})")
            # 0 = kapat/güvenli yön: A2L alt sınırı kapatmayı engellemesin (yine de sonlu/tür kontrolü var).
            # Güvenlik komutunda (safety) değer ne olursa olsun sınır/READ_ONLY denetimi atlanır.
            # Güvenlik komutunda yalnızca İLETİŞİM hatası (zaman aşımı/CCP hatası) yeniden denenir; her deneme
            # SET_MTA'dan başladığı için tekrar güvenlidir. Geri OKUMA doğrulaması bilerek yok: komut bayrağını
            # ECU modeli tüketip sıfırlayabilir, bu yüzden uyuşmazlık başarısızlık anlamına gelmez.
            attempts = SAFETY_A2L_ATTEMPTS if safety else 1
            for attempt in range(1, attempts + 1):
                try:
                    # Öncelikli: arka planda uzun bir yazma (harita/flaş) sürüyorsa parçaları arasına girer.
                    with self._ccp_urgent():
                        cpanel.ccp_write_value(self.ccp_client, info, value,
                                               enforce_limits=(not safety and float(value) != 0.0))
                    break
                except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError) as exc:
                    if attempt >= attempts:
                        raise
                    self._log_event("HATA", f"{label}: A2L yazma denemesi {attempt}/{attempts} başarısız ({exc}); "
                                            f"yeniden deneniyor")
        except Exception as exc:
            hint = ("\n\nDeğer veri tipine sığmıyor: yapılandırılmış komut değerini "
                    "(⚙ Eşleşmeler) düzeltin.") if safety else ""
            QMessageBox.critical(self, f"{label} yazılamadı", f"{exc}{hint}")
            self._log_event("HATA", f"{label} A2L yazılamadı: {exc}")
            self._record_input("Ana Sayfa", self._input_kind(label, merge, safety), "A2L", binding.a2l_name, value,
                               ok=False, detail=f"{label}: {exc}", unit=getattr(info, "unit", "") or "")
            return False
        self._log_event("EYLEYICI", f"{label} [A2L {binding.a2l_name}] = {value:g} "
                                    f"({self.current_user}/{self.current_role.value})")
        self._record_input("Ana Sayfa", self._input_kind(label, merge, safety), "A2L", binding.a2l_name, value,
                           detail=label, unit=getattr(info, "unit", "") or "")
        return True

    def _send_motor_command(self, command_name: str, cmd, safety: bool = False,
                            value: float = COMMAND_VALUE) -> bool:
        """Basılınca eşlenen sinyale/değişkene sabit ``COMMAND_VALUE`` (1) yazar: tek sinyallik, tek seferlik darbe.
        Değer ve Switch (_sw) yoktur; mesajın diğer sinyallerinin eski değerleri taşınmaz."""
        if not cmd.binding.is_set:
            self._log_event("HATA", f"{command_name} GÖNDERİLEMEDİ: eşleme tanımlı değil")
            return False
        ok = self._write_binding(cmd.binding, value, command_name, merge=False, safety=safety)
        if ok:
            self._log_event("MOTOR", f"{command_name} gönderildi ({cmd.binding.text}={value:g})")
        else:
            self._log_event("HATA", f"{command_name} GÖNDERİLEMEDİ ({cmd.binding.text})")
        return ok

    def _on_motor_start(self):
        self._send_motor_command("Motor Start", self.dashboard_tab.config.motor_start)

    def _on_motor_stop(self):
        # Durdurma "güvenli yön" komutudur: A2L/DBC sınırı ya da READ_ONLY yüzünden reddedilmez
        # (Motor Start sınırda kalır; bkz. _write_binding safety).
        self._send_motor_command("Motor Stop", self.dashboard_tab.config.motor_stop, safety=True)

    def _on_estop(self):
        cmd = self.dashboard_tab.config.estop
        if not cmd.binding.is_set:
            # Sessizce dönme: operatör komutun GİTMEDİĞİNİ açıkça görmeli.
            self._log_event("HATA", "ACİL DURDURMA GÖNDERİLEMEDİ: eşleme tanımlı değil")
            QMessageBox.critical(
                self, "ACİL DURDURMA GÖNDERİLEMEDİ",
                "Acil Durdurma için DBC sinyali veya A2L değişkeni TANIMLI DEĞİL; komut ECU'ya gitmedi.\n\n"
                "Motoru manuel / fiziksel olarak hemen durdurun. Sonra ⚙ Eşleşmeler penceresinden "
                "Acil Durdurma eşlemesini tanımlayın.")
            self.dashboard_tab.reset_estop_latch()
            return
        # Güvenlik komutu: A2L/DBC sınırı ya da READ_ONLY yüzünden reddedilmez (bkz. _write_binding).
        if not self._send_motor_command("ACİL DURDURMA", cmd, safety=True):
            self.dashboard_tab.reset_estop_latch()      # gitmediyse kilitli görünmesin

    def _on_estop_released(self):
        """Kilitli Acil Durdurma 2. basışla açılmak isteniyor: onay ister, Acil Durdurma sinyalini 0'a çeker.
        Motor Start GÖNDERİLMEZ (operatör ayrıca başlatır). Onay verilmezse ya da yazma başarısızsa kilit
        kapalı (kilitli) kalır."""
        dt = self.dashboard_tab
        cmd = dt.config.estop
        answer = QMessageBox.question(
            self, "Acil Durdurma kilidi açılsın mı?",
            "Acil Durdurma sinyali 0'a çekilecek ve kilit açılacak.\n"
            "Motor kendiliğinden BAŞLAMAZ; gerekirse Motor Başlat'a ayrıca basın.\n\nDevam edilsin mi?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            self._log_event("MOTOR", "Acil Durdurma kilidi açma iptal edildi (kilitli kalıyor)")
            return
        if self._send_motor_command("Acil Durdurma kilidi açma", cmd, safety=True, value=0.0):
            self._log_event("MOTOR", "Acil Durdurma kilidi açıldı (sinyal=0)")
            dt.reset_estop_latch()
        else:
            self._log_event("HATA", "Acil Durdurma kilidi AÇILAMADI: sinyal 0'a çekilemedi, kilitli kalıyor")

    def _migrate_control_bindings(self):
        """Eski sürümde Motor Kontrol girişleri (Start/Spark/Gaz Kolu/Birincil Yakıt) ``sim_interface.json``
        içinde "dbc:MESAJ.SİNYAL" olarak tutuluyordu ve doğrudan gönderiliyordu. Artık Eyleyiciler gibi
        (kilitli, değer + isteğe bağlı _sw, CAN/A2L): eski DBC eşlemesi DEĞER bağlaması olarak taşınır."""
        cfg = self.dashboard_tab.config
        legacy = self.sim_config.input_map
        changed = False
        for key in CONTROL_KEYS:
            old = legacy.pop(key, None)
            m = cfg.actuator_map(key)
            if old and old.startswith("dbc:") and "." in old and not m.value.is_set:
                msg, sig = old[4:].split(".", 1)
                m.value = Binding(SOURCE_CAN, msg, sig)
                changed = True
        if legacy is not None and any(k in self.sim_config.input_values for k in CONTROL_KEYS):
            for k in CONTROL_KEYS:
                self.sim_config.input_values.pop(k, None)
        if changed:
            self.dashboard_config_store.save(cfg)
        self.sim_config.save()

    def _on_dashboard_config_saved(self, cfg):
        if not self.dashboard_config_store.save(cfg):
            self._log_event("HATA", "Eşleşmeler DİSKE YAZILAMADI (bellekte geçerli, yeniden açınca kaybolur).")
            QMessageBox.warning(self, "Ayarlar kaydedilemedi",
                                "Eşleşmeler diske yazılamadı; program kapanınca kaybolacak.")
        self._rebuild_dash_can_map()
        self._log_event("AYAR", "Eşleşmeler (CAN/A2L) kaydedildi.")

    def _on_dashboard_sources_changed(self, *_):
        summary = self.a2l_tab.db.summary
        self.dashboard_tab.set_sources(self.transmit_tab.dbc, summary)
        self._rebuild_dash_can_map()

    # ---- Ana Sayfa: CAN'dan (DBC) sensör okuma --------------------------------
    _dash_can: dict = {}

    def _rebuild_dash_can_map(self):
        """CAN kaynaklı sensör değer/arıza sinyallerini frame id'ye göre indeksler."""
        self._dash_can = {}
        cdb = getattr(self.transmit_tab.dbc, "_db", None)
        if cdb is None:
            return
        cfg = self.dashboard_tab.config
        for key in SENSOR_KEYS:           # Motor Modu da CAN'dan okunur
            smap = cfg.sensor_map(key)
            for role, b in (("value", smap.value), ("fault", smap.fault)):
                if b.source != SOURCE_CAN or not b.is_set:
                    continue
                try:
                    msg = cdb.get_message_by_name(b.message)
                except KeyError:
                    continue
                ent = self._dash_can.setdefault(msg.frame_id, {"msg": msg, "sigs": []})
                ent["sigs"].append((b.signal, role, key))

    def _dash_on_can_frame(self, can_id: int, data: bytes):
        ent = self._dash_can.get(can_id)
        if ent is None:
            return
        try:
            vals = ent["msg"].decode(bytes(data), decode_choices=False)
        except Exception:
            return
        dt = self.dashboard_tab
        for sig, role, key in ent["sigs"]:
            v = vals.get(sig)
            if not isinstance(v, (int, float)):
                continue
            if role == "value":
                dt.set_gauge_value(key, float(v))
            else:
                dt.set_sensor_fault(key, "Sensör arızası" if v else None)

    def _on_session_record_start(self, name: str, operator: str):
        try:
            path = self.session_recorder.start(data_path("oturum_kayitlari"), name)
        except OSError as exc:
            self.event_log.add("HATA", f"Parametre kaydı başlatılamadı: {exc}")
            self.session_tab.set_record_info(f"Parametre kaydı BAŞLATILAMADI: {exc}")
            self.session_tab.refresh_log()
            return
        self.input_log.start_file(os.path.splitext(path)[0] + "_girisler.csv")    # girişler oturum boyunca diske
        self._ccp_last_bytes = {}                                                  # ilk okuma başlangıç değeri olarak yazılsın
        self.frame_recorder.start()
        self.connection.frame_tap = self.frame_recorder.submit                     # her CAN karesi geliş zamanında
        self.event_log.add("OTURUM", f"Parametre kaydı başladı: {path}")
        self.session_tab.set_record_info(f"● Parametre kaydı: {path}")
        self.session_tab.refresh_log()

    def _on_session_record_stop(self):
        rec = self.session_recorder
        path, rows, err = rec.path, rec.rows, rec.error
        rec.stop()
        self.input_log.stop_file()
        self.connection.frame_tap = None
        self.frame_recorder.stop()
        if path and self.frame_recorder.frames:
            self.event_log.add("OTURUM", f"CAN kare kaydı: {self.frame_recorder.frames} kare çözümlenip yazıldı")
        if self.frame_recorder.dropped:
            self.event_log.add("HATA", f"CAN kaydı: {self.frame_recorder.dropped} kare kuyruk dolduğu için YAZILAMADI")
        if path:
            self._last_record_csv = path
            self.event_log.add("OTURUM", f"Parametre kaydı bitti: {rows} örnek, {path}")
            self.session_tab.set_record_info(f"Parametre kaydı kaydedildi ({rows} örnek): {path}")
        if err:
            self.event_log.add("HATA", f"Parametre kaydı diske yazılamadı, kayıt durdu: {err}")
        # Excel (.xlsx): oturum özeti, parametre kaydı, olay günlüğü ve kalibrasyon yazımları tek dosyada.
        xlsx = self._export_session_excel(path)
        if xlsx:
            self.session_tab.set_record_info(f"Kayıt: {path or '-'}\nExcel: {xlsx}")
        self.session_tab.refresh_log()

    def _on_hub_sample(self, sid: str, value):
        """Sinyal deposundan gelen örnek: yalnızca kullanıcı girişleri kayda yazılır (diğerleri kaynakta yazılır)."""
        if sid.startswith("input:"):
            self.session_recorder.record(sid, value)

    def _rebuild_record_index(self):
        """A2L yüklenince: CCP okuma anahtarı (adres, uzantı, boyut) -> A2L nesneleri. CCP iş parçacığı değeri
        çözümleyip adıyla yazabilsin diye (yeni sözlük atomik olarak yerine konur)."""
        index: dict = {}
        summary = self.a2l_tab.db.summary
        for obj in (summary.readable() if summary is not None else []):
            if obj.address is None or not obj.datatype:
                continue
            try:
                size = ccp_codec.datatype_size(obj.datatype)
            except ccp_codec.UnknownDatatypeError:
                continue
            index.setdefault((obj.address, obj.address_extension or 0, size), []).append(obj)
        self._record_index = index

    def _on_ccp_sample(self, key: tuple, data: bytes, t: float):
        """CCP iş parçacığından, HER başarılı okumada: değer DEĞİŞMİŞSE okuma zamanıyla kayda yazar. Değişmeyen
        değer çözümlenmez bile (hızlı yol)."""
        rec = self.session_recorder
        if not rec.is_active:
            return
        infos = self._record_index.get(key)
        if not infos:
            return
        data = bytes(data)
        if self._ccp_last_bytes.get(key) == data:
            return
        self._ccp_last_bytes[key] = data
        for info in infos:
            try:
                raw = ccp_codec.decode_value(info.datatype, data, info.byte_order)
                phys = ccp_codec.raw_to_physical(info.compu_method, raw)
            except Exception:  # noqa: BLE001
                continue
            rec.record_change(f"a2l:{info.name}", phys, t)

    def _sync_workspace_a2l(self):
        summary = self.a2l_tab.db.summary
        self.workspace_tab.set_a2l_measurements(summary.readable() if summary is not None else [])

    def _on_workspace_tick(self, names: list):
        """Çalışma Alanı'nda seçili A2L ölçümlerini CCP ile (arka planda) okuyup hub'a yazar."""
        for name, _m, reading in self._iter_a2l_samples(names):
            self.workspace_tab.push(f"a2l:{name}", reading.phys)

    def _sync_dashboard_measurements(self):
        summary = self.a2l_tab.db.summary
        self.dashboard_tab.set_measurements(summary.readable() if summary is not None else [])

    # ---- Ana Sayfa: A2L'den (CCP) okuma --------------------------------------
    def _on_dashboard_tick(self, names: list):
        dt = self.dashboard_tab
        cfg = dt.config
        a2l_gauges = cfg.gauge_a2l_map()                    # gösterge -> A2L adı
        if self.ccp_client is None:
            reason = self.ccp_session.not_ready_reason()
            for key in a2l_gauges:
                dt.set_gauge_error(key, reason)
            return
        summary = self.a2l_tab.db.summary
        if summary is None:
            for key in a2l_gauges:
                dt.set_gauge_error(key, "A2L yüklü değil")
            return

        by_name = summary.readable_by_name()
        roles: dict[str, list] = {}                          # A2L adı -> [(rol, gösterge)]
        for key, name in a2l_gauges.items():
            roles.setdefault(name, []).append(("value", key))
            m = by_name.get(name)
            if m is not None:
                dt.set_gauge_limits(key, m.minimum, m.maximum)
        for key in GAUGE_KEYS:
            f = cfg.sensor_map(key).fault
            if f.source == SOURCE_A2L and f.a2l_name.strip():
                roles.setdefault(f.a2l_name.strip(), []).append(("fault", key))
        graph_names = set(dt.graph_measurement_names())

        for name in names:
            targets = roles.get(name, [])
            graph_wanted = name in graph_names
            if not targets and not graph_wanted:
                continue
            m = by_name.get(name)

            def fail(reason: str, targets=targets):
                for role, key in targets:
                    if role == "value":
                        dt.set_gauge_error(key, reason)

            if m is None:
                fail(f"A2L'de '{name}' yok")
                continue
            if m.address is None:
                fail("ECU adresi yok")
                continue
            try:
                reading = ccp_codec.read_value(self.ccp_reader, m)
                raw_value, phys_value = reading.raw, reading.phys
            except ccp_protocol.CCPTimeoutError as exc:
                fail(str(exc) or "ECU cevap vermedi")
                continue
            except ccp_protocol.CCPError as exc:
                fail(f"CCP hatası: {exc}")
                continue
            except ccp_codec.UnknownDatatypeError:
                fail(f"Veri tipi desteklenmiyor ({m.datatype})")
                continue
            except ValueError as exc:
                fail(str(exc))
                continue
            if graph_wanted and isinstance(phys_value, (int, float)):
                dt.add_measurement_sample(name, float(phys_value))
            for role, key in targets:
                if role == "value":
                    dt.set_gauge_value(key, float(phys_value))
                    dt.set_gauge_debug(
                        key, f"A2L: {name}  @0x{m.address:X}  {m.datatype}  "
                             f"{m.byte_order or 'bayt sırası: varsayılan (MSB_FIRST)'}\n"
                             f"ham = {raw_value}   →   fiziksel = {float(phys_value):.6g} {m.unit or ''}"
                             f"   [{getattr(m.compu_method, 'conversionType', 'dönüşüm yok')}]")
                else:
                    dt.set_sensor_fault(key, "Sensör arızası" if phys_value else None)
