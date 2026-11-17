"""CCP oturumu ve kalibrasyon: arka plan CCP işleri, tek değer / harita / Parametre Listesi
okuma-yazma, tanılama ve geçmişten geri alma."""
import contextlib
import threading

from PySide6.QtCore import QEventLoop, QTimer, Qt
from PySide6.QtWidgets import (
    QApplication, QMessageBox,
)

from app.ccp import codec as ccp_codec
from app.ccp import mapio as ccp_mapio
from app.ccp import protocol as ccp_protocol
from app.ccp.worker import IDLE, LOST, ONLINE
from app.paths import data_path
from app.ui.watch_tab import parse_value_text
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

    def _on_ccp_disconnect(self):
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
        online = state == ONLINE
        self.ccp_tab.set_session_state(state, self.ccp_session.status_text())
        self.watch_tab.set_live_state(state, self.ccp_session.status_text())
        self.watch_tab.set_connected(state in (ONLINE, LOST))
        self.map_editor_tab.set_online(online)
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
            persistent=persistent,
        )
        self._record_input("Kalibrasyon > CCP", "FLAŞ yazımı" if persistent else "RAM yazımı", "A2L", obj.name,
                           phys_value, old_value=old_phys, unit=obj.unit or "")
        self.history_tab.refresh()

    def _record_denied_write(self, page: str, kind: str, detail: str, target: str = "", value=None):
        """Reddedilen (yetki/bağlantı) yazma girişimi de kayda geçer: ne denendiği sonradan görülebilsin."""
        self._record_input(page, kind, "A2L", target or "(seçili nesne)", value, ok=False, detail=detail)

    # ---- Harita Editörü (CURVE/MAP/ARRAY okuma-yazma; çoklu tablo) ----------
    def _open_in_map_editor(self, characteristic):
        """CCP sekmesindeki dizi/tablo nesnesini Harita Editörü'nde açar."""
        self.map_editor_tab.open_characteristic(characteristic)
        inner = self.kalibrasyon_tab.inner_tabs
        inner.setCurrentWidget(self.map_editor_tab)

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
        (Harita Editörü > "Yedekten Yükle…" ile geri getirilir). Başarısızsa '' döner."""
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
                self._record_input("Kalibrasyon > Harita Editörü", "Tablo yazımı (RAM)", "A2L", characteristic.name,
                                   f"{len(grid)}×{len(grid[0]) if grid else 0} tablo", ok=False, detail=str(old_grid),
                                   unit=characteristic.unit or "")
                failed += 1
                continue
            backup = self._save_table_backup(characteristic, old_grid)
            rows, cols = len(grid), len(grid[0]) if grid else 0
            changed = self._count_changed_cells(old_grid, grid)
            self._record_input("Kalibrasyon > Harita Editörü", "Tablo yazımı (RAM)", "A2L", characteristic.name,
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
                persistent=False,
                detail=f"{rows}×{cols} tablo yazıldı, {changed} hücre değişti"
                       + (f"; önceki içerik yedeği: {backup}" if backup else ""),
            )
            written += 1
        if written:
            self.history_tab.refresh()
        return written, failed

    def _write_map_doc(self, doc) -> bool:
        return self._write_map_docs([doc])[0] == 1

    def _on_map_read(self):
        doc = self.map_editor_tab.current_document()
        if doc is None:
            return
        if not self._require_ccp("Harita okumadan"):
            return
        self._read_map_doc(doc)

    def _on_map_write(self):
        doc = self.map_editor_tab.current_document()
        if doc is None:
            return
        if not self._require_ccp("Harita yazmadan"):
            return
        if not can_write_calibration(self.current_role):
            doc.set_write_result(False, "Yetki yok: harita yazmak için Mühendis veya Yönetici rolü gerekir.")
            self._record_denied_write("Kalibrasyon > Harita Editörü", "Tablo yazımı (RAM)",
                                      "Yetki yok: Mühendis veya Yönetici rolü gerekir", doc.characteristic.name)
            return
        self._write_map_doc(doc)

    def _on_map_read_all(self):
        docs = self.map_editor_tab.documents()
        if not docs or not self._require_ccp("Tabloları okumadan"):
            return
        ok = self._read_map_docs(docs)
        self._log_event("KALIBRASYON", f"{ok}/{len(docs)} tablo ECU'dan okundu")

    def _on_map_write_all(self):
        docs = self.map_editor_tab.documents()
        if not docs or not self._require_ccp("Tabloları yazmadan"):
            return
        if not can_write_calibration(self.current_role):
            for d in docs:
                d.set_write_result(False, "Yetki yok: harita yazmak için Mühendis veya Yönetici rolü gerekir.")
                self._record_denied_write("Kalibrasyon > Harita Editörü", "Tablo yazımı (RAM)",
                                          "Yetki yok: Mühendis veya Yönetici rolü gerekir", d.characteristic.name)
            return
        modified = [d for d in docs if d.is_modified()]
        skipped = len(docs) - len(modified)
        written, failed = self._write_map_docs(modified)
        self._log_event(
            "KALIBRASYON",
            f"Toplu tablo yazma: {written} yazıldı, {skipped} değişmediği için atlandı, {failed} başarısız"
        )

    # ---- Parametre Listesi (çoklu parametre izleme/yazma) --------------------
    def _read_phys_best_effort(self, e):
        try:
            return ccp_codec.read_value(self.ccp_client, e).phys
        except (ccp_protocol.CCPError, ccp_protocol.CCPTimeoutError,
                ccp_codec.UnknownDatatypeError, ValueError):
            return None

    def _on_watch_read(self):
        """Parametre Listesi canlı okuma: değerler arka plan CCP iş parçacığının önbelleğinden
        gelir (arayüz hiç beklemez); ECU yokken satırlar anında 'ECU cevap vermiyor' gösterir ve
        ECU geri gelince değerler kendiliğinden akmaya başlar."""
        if self.ccp_client is None:
            return
        for row, e in enumerate(self.watch_tab.entries()):
            if not getattr(e, "resolved", True) or not e.datatype:
                continue
            try:
                reading = ccp_codec.read_value(self.ccp_reader, e)
            except ccp_protocol.CCPTimeoutError as exc:
                self.watch_tab.set_row_error(row, str(exc) or "ECU cevap vermedi")
                continue
            except (ccp_protocol.CCPError, ccp_codec.UnknownDatatypeError, ValueError) as exc:
                self.watch_tab.set_row_error(row, str(exc))
                continue
            except Exception as exc:
                self.watch_tab.set_row_error(row, f"Okuma hatası: {exc}")
                continue
            self.watch_tab.set_row_value(row, reading.raw_bytes, reading.phys)    # Parametre Listesi HAM BAYT bekler

    def _on_watch_write(self, rows: list):
        """Parametre Listesi: Değer hücresine Enter ile onaylanan değerleri RAM'e yazar (anında).
        Yazılamayanlarda bekleyen metin atılır (hücre canlı değere döner); yazılanlar ECU'dan geri
        okunarak doğrulanır (bkz. WatchTab.commit_written / set_row_value)."""
        def record_denied(detail: str):
            for row in rows:
                if 0 <= row < len(self.watch_tab.entries()):
                    e = self.watch_tab.entries()[row]
                    text = self.watch_tab.pending_text(row)
                    self._record_input("Kalibrasyon > Parametre Listesi", "RAM yazımı", "A2L", e.name,
                                       text, ok=False, detail=detail, unit=e.unit or "")

        if self.ccp_client is None:
            record_denied("CCP bağlı değil")
            self.watch_tab.discard_pending(rows)
            self.watch_tab.set_write_result(False, "CCP bağlı değil; değer yazılamadı (bağlantı kurulunca tekrar deneyin).")
            return
        if not can_write_calibration(self.current_role):
            record_denied("Yetki yok: Mühendis veya Yönetici rolü gerekir")
            self.watch_tab.discard_pending(rows)
            self.watch_tab.set_write_result(
                False, "Yetki yok: kalibrasyon yazmak için Mühendis veya Yönetici rolü gerekir "
                       "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
            return
        entries = self.watch_tab.entries()
        done = 0
        problems: list[str] = []
        failed_rows: list[int] = []
        todo = []                               # (satır, giriş, fiziksel değer)
        for row in rows:
            if row < 0 or row >= len(entries):
                continue
            e = entries[row]
            text = self.watch_tab.pending_text(row)
            if text is None or e.read_only or not getattr(e, "resolved", True):
                continue
            try:
                todo.append((row, e, parse_value_text(text)))
            except ValueError:
                problems.append(f"{e.name}: geçersiz sayı ({text!r})")
                failed_rows.append(row)
        client = self.ccp_client

        def work():
            out = []                            # (eski değer, hata | None)
            for _row, e, phys in todo:
                try:
                    old = ccp_codec.read_value(client, e).phys
                except _CCP_IO_ERRORS:
                    old = None
                try:
                    # doğrulama (sonlu, tür aralığı, A2L min/max, READ_ONLY) + güvenli dönüşüm
                    raw_bytes = ccp_codec.encode_for_write(e, phys)
                    client.write_memory(e.address, raw_bytes, e.address_extension or 0)
                    out.append((old, None))
                except _CCP_IO_ERRORS as exc:
                    out.append((old, exc))
            return out

        try:
            results = self._ccp_job("Parametreler yazılıyor", work) if todo else []
        except (ValueError, RuntimeError) as exc:
            results = [(None, exc)] * len(todo)
        for (row, e, phys), (old_phys, exc) in zip(todo, results):
            if isinstance(exc, ccp_protocol.CCPTimeoutError):
                problems.append(f"{e.name}: {str(exc) or 'ECU cevap vermedi'}")
                self._log_event("HATA", f"{e.name} RAM yazma: ECU cevap vermedi")
                self._record_input("Kalibrasyon > Parametre Listesi", "RAM yazımı", "A2L", e.name, phys, ok=False,
                                   detail=str(exc) or "ECU cevap vermedi", unit=e.unit or "")
                failed_rows.append(row)
                continue
            if exc is not None:
                problems.append(f"{e.name}: {exc}")
                self._log_event("HATA", f"{e.name} RAM yazma hatası: {exc}")
                self._record_input("Kalibrasyon > Parametre Listesi", "RAM yazımı", "A2L", e.name, phys, ok=False,
                                   detail=str(exc), unit=e.unit or "")
                failed_rows.append(row)
                continue
            self.watch_tab.commit_written(row, phys)
            self._log_event("KALIBRASYON", f"{e.name} = {phys} {e.unit or ''} (RAM, Parametre Listesi) yazıldı")
            self.calibration_history.add(
                self.current_user, self.current_role.value, e.name, old_phys, phys, e.unit or "",
                persistent=False,
            )
            self._record_input("Kalibrasyon > Parametre Listesi", "RAM yazımı", "A2L", e.name, phys,
                               old_value=old_phys, unit=e.unit or "")
            done += 1
        self.watch_tab.discard_pending(failed_rows)
        self.history_tab.refresh()
        if problems:
            self.watch_tab.set_write_result(
                False, f"{done} parametre yazıldı; sorunlar: " + "; ".join(problems))
        elif done:
            self.watch_tab.set_write_result(True, f"{done} parametre RAM'e yazıldı; ECU'dan doğrulanıyor…")

    # ---- Grafik (canlı Measurement çizimi) ---------------------------------
    def _iter_a2l_samples(self, names: list):
        """Verilen A2L ölçüm adlarını (önbellekten, beklemeden) okuyup ``(ad, ölçüm, Reading)``
        üretir. Okunamayanlar (A2L'de yok, adres yok, ECU cevap vermiyor, bilinmeyen veri tipi)
        sessizce atlanır; ayrıntılı hata gösterimi isteyenler (Ana Sayfa, Parametre Listesi)
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
            persistent=entry.persistent,
        )
        self._record_input("Kalibrasyon > Geçmiş", "Geri alma (FLAŞ)" if entry.persistent else "Geri alma (RAM)", "A2L",
                           obj.name, entry.old_value, old_value=entry.new_value, unit=obj.unit or "",
                           detail="Geçmişten eski değere geri yazıldı")
        self.history_tab.refresh()
        self._log_event("KALIBRASYON", f"{obj.name} eski değerine geri yazıldı: {entry.old_value}")
