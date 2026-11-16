"""CAN bağlantısı: bağlan/kes, sağlık izleme, kopma ve otomatik yeniden bağlanma, alım/gönderim
kuyrukları, elle ve periyodik gönderim, CAN kaydı."""
import logging
import queue
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QMessageBox,
)

from app.ccp.worker import IDLE
from app.scheduler import PeriodicManager
from app.user_roles import (
    can_transmit_frames,
)
from app.ui.mainwin.common import (
    CONNECTION_LOSS_CONFIRM_S, SILENT_NOTICE_S,
)


class ConnectionMixin:

    # ---- Bağlantı ----------------------------------------------------
    def _on_connect(self, interface: str, channel: str, bitrate: int):
        # Kullanıcı elle bağlanıyorsa bekleyen otomatik yeniden bağlanma iptal.
        self._cancel_reconnect()
        try:
            self.connection.connect(interface, channel, bitrate)
        except Exception as exc:  # python-can farklı arka uçlarda farklı hata tipleri fırlatabilir
            QMessageBox.critical(self, "Bağlantı hatası", str(exc))
            return
        self._after_connected(interface, channel, bitrate)

    def _after_connected(self, interface: str, channel: str, bitrate: int, reconnected: bool = False):
        """connect() başarılı olduktan sonraki ortak kurulum (hem elle
        bağlanma hem de koptuktan sonra otomatik yeniden bağlanma)."""
        self._last_connect_params = (interface, channel, bitrate)
        self._unhealthy_since = None
        self._last_health_state = "ok"
        self._conn_lost = False
        self._dismiss_loss_box()
        self.periodic_manager = PeriodicManager(lambda: self.connection.bus, on_sent=self.connection.note_tx)
        self.connection_tab.set_connected(True)
        self.monitor_tab.set_bitrate(bitrate if interface != "virtual" else None)
        self.rx_timer.start()
        self._panel_conn_state()
        self._log_event(
            "BAGLANTI",
            f"CAN hattına {'yeniden ' if reconnected else ''}bağlanıldı ({interface}, {channel}, {bitrate} bps)"
        )
        self._conn_state.update(connected=True, lost=False, interface=f"{interface}/{channel}",
                                version=f"{bitrate} bps")
        self._update_connection_display()

        # can.Bus() hata firlatmamis olmasi, donanimin GERCEKTEN saglikli
        # oldugu anlamina gelmez (ozellikle pcan'de) - hemen bir kere,
        # sonra da SUREKLI olarak (her HEALTH_CHECK_INTERVAL_MS) gercek
        # durumu sorguluyoruz.
        self._check_connection_health()
        self.health_timer.start()

        # CAN'a bağlanınca CCP'yi de otomatik bağla (kutu işaretliyse; ya da
        # bağlantı koptuğunda CCP açıktıysa yeniden kurulumda). Manuel
        # CCP Bağlan / Kes düğmeleri ayrıca çalışmaya devam eder.
        if self.ccp_tab.auto_connect_enabled() or self._resume_ccp_after_reconnect:
            self._resume_ccp_after_reconnect = False
            self._auto_ccp_connect()

    def _release_overrides_on_teardown(self, graceful: bool):
        """Bağlantı kapanırken ECU'da AÇIK kalmış eyleyici override'larını (kilit açık) bırakmayı
        dener (graceful) ve her durumda arayüzü 'bilinmiyor/kilitli'ye çeker. Bırakılamayanlar
        HATA olarak loglanır ve kullanıcıya gösterilir."""
        try:
            unconfirmed = self.dashboard_tab.release_all_actuators(write=graceful)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("override bırakma hatası")
            return
        if unconfirmed:
            names = ", ".join(unconfirmed)
            self._log_event("HATA", f"Bağlantı kapandı; ECU'da şu override'lar AÇIK kalmış olabilir: {names}")
            self.statusBar().showMessage(f"UYARI: override açık kalmış olabilir: {names}", 15000)

    def _teardown_connection(self, graceful: bool = True):
        """CAN bağlantısına bağlı her şeyi kapatır. graceful=False: adaptör
        gitmiş olduğu için CCP DISCONNECT gibi bus'a yazan adımlar ATLANIR
        (aksi halde zaman aşımlarında arayüz bloklanırdı)."""
        self._release_overrides_on_teardown(graceful)   # CCP/CAN hâlâ açıkken: override'ları bırakmayı dene
        if self.ccp_session.state != IDLE:
            if graceful:
                self._on_ccp_disconnect()
            else:
                self._drop_ccp_client()
        if self.periodic_manager is not None:
            try:
                self.periodic_manager.stop_all()
            except Exception:
                pass
            self.periodic_manager = None
        self.transmit_tab.stop_all_rows()
        self.tx_scheduler.stop_all()
        self._drain_tx_queue()               # son gönderilen kareler de izleme/kayıtta görünsün
        self.rx_timer.stop()
        self.health_timer.stop()
        self.connection.disconnect()
        self.connection_tab.set_connected(False)
        self._panel_conn_state()

    def _on_disconnect(self):
        self._cancel_reconnect()
        self._conn_lost = False
        self._dismiss_loss_box()
        self._unhealthy_since = None
        self._teardown_connection(graceful=True)
        self.errors_tab.set_health(False, "Bağlı değil")
        self._log_event("BAGLANTI", "CAN bağlantısı kesildi")
        self._conn_state.update(connected=False, lost=False, interface="—", version="—")
        self._update_connection_display()

    # ---- Bağlantı SÜREKLİ izleme + kopma tespiti + otomatik yeniden bağlanma
    def _check_connection_health(self):
        """Her HEALTH_CHECK_INTERVAL_MS'de sürücüden gerçek bağlantı durumunu
        sorar. Adaptör/sürücü sorunu CONNECTION_LOSS_CONFIRM_S saniye
        KESİNTİSİZ sürerse "bağlantı koptu" der (anlık hatada yanlış alarm
        yok). Hat düzeyi sorunlar (ECU kapalı, bus-off...) kopma sayılmaz,
        yalnızca uyarı olarak gösterilir."""
        if not self.connection.is_connected:
            return
        # Bus-off/ağır hata + sessizlikte reset → gerekirse adaptörü yeniden aç (otomatik kurtarma);
        # PCAN durum kodu geçişleri donanım testinde teşhis için günlüğe yazılır.
        for event in self.connection.watchdog():
            self._log_event("BAGLANTI", event)
        state, message = self.connection.link_state()
        now = time.monotonic()

        if state == "lost":
            if self._unhealthy_since is None:
                self._unhealthy_since = now
                self._log_event("HATA", f"CAN bağlantı sorunu algılandı, doğrulanıyor: {message}")
            elapsed = now - self._unhealthy_since
            if elapsed >= CONNECTION_LOSS_CONFIRM_S:
                self._handle_connection_lost(message, elapsed)
                return
            shown = f"Bağlantı sorunu algılandı, doğrulanıyor… ({elapsed:.0f}/{CONNECTION_LOSS_CONFIRM_S:.0f} sn): {message}"
            self.connection_tab.set_health(False, shown)
            self.errors_tab.set_health(False, shown)
            self._update_connection_display(health_message=shown)
            return

        if self._unhealthy_since is not None:
            lasted = now - self._unhealthy_since
            self._log_event("BAGLANTI", f"CAN bağlantı sorunu kendiliğinden geçti ({lasted:.1f} sn sürdü)")
            self._unhealthy_since = None

        ok = state == "ok"
        silent = self.connection.silent_for()
        if state == "bus_warning" and self.connection.recovering:
            message = f"Hat hatalı, kurtarılıyor: {message} (son mesaj {silent:.0f} sn önce)"
        elif ok and silent > SILENT_NOTICE_S:
            ok = False
            message = f"Hat sessiz ({silent:.0f} sn): ECU kapalı olabilir; hat dönünce otomatik sürer"
        self.connection_tab.set_health(ok, message)
        self.errors_tab.set_health(ok, message)
        if not ok and getattr(self, "_last_health_state", "ok") == "ok":
            self._log_event("HATA", f"CAN hat durumu uyarısı: {message}")
        self._last_health_state = state
        self._update_connection_display(health_message=message)

    def _handle_connection_lost(self, reason: str, elapsed: float):
        """Bağlantı KOPTU: her şeyi temizle, kullanıcıya açıkça bildir ve
        adaptör geri gelirse otomatik yeniden bağlanmak için denemeye başla."""
        self._resume_ccp_after_reconnect = self.ccp_session.state != IDLE or self._resume_ccp_after_reconnect
        self._conn_lost = True
        self._unhealthy_since = None
        self._teardown_connection(graceful=False)  # adaptör yok: bus'a yazan adımlar atlanır
        self.watch_tab.stop_polling()
        self.connection_tab.set_lost(True)
        self._panel_conn_state()
        lost_text = f"Bağlantı koptu: {reason}"
        self.errors_tab.set_health(False, lost_text)
        self._log_event(
            "HATA",
            f"CAN BAĞLANTISI KOPTU ({elapsed:.1f} sn boyunca adaptör yanıt vermedi): {reason}. "
            "Otomatik yeniden bağlanma deneniyor."
        )
        self._conn_state.update(connected=False, lost=True, version="—")
        self._update_connection_display(health_message=lost_text)
        self._show_loss_box(reason)
        self.reconnect_timer.start()

    def _show_loss_box(self, reason: str):
        self._dismiss_loss_box()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Warning)
        box.setWindowTitle("CAN bağlantısı koptu")
        box.setText(
            "CAN adaptörüyle bağlantı koptu (adaptör çıkarılmış veya sürücü yanıt vermiyor olabilir)."
        )
        box.setInformativeText(
            f"Ayrıntı: {reason}\n\nAdaptörü tekrar taktığınızda uygulama otomatik "
            "olarak yeniden bağlanmayı dener. İsterseniz CAN Monitor sekmesinden "
            "elle de bağlanabilirsiniz."
        )
        box.setStandardButtons(QMessageBox.Ok)
        box.setWindowModality(Qt.NonModal)  # arayüzü kilitlemesin
        box.setAttribute(Qt.WA_DeleteOnClose, True)
        box.show()
        self._loss_box = box

    def _dismiss_loss_box(self):
        if self._loss_box is not None:
            try:
                self._loss_box.close()
            except RuntimeError:
                pass  # zaten silinmiş
            self._loss_box = None

    def _cancel_reconnect(self):
        self.reconnect_timer.stop()

    def _on_bus_reopened(self):
        """Bekçi adaptörü yeniden açınca: CCP istemcisi ve periyodik görevler yeni bus'a geçer
        (periyodik görevler bus'ı çağrılabilirle aldığı için kendiliğinden geçer)."""
        self.ccp_session.refresh_bus()
        self._log_event("BAGLANTI", "Adaptör yeniden açıldı; CCP ve periyodik gönderim yeni bus'a geçti")

    def _try_reconnect(self):
        if not self._conn_lost or self._last_connect_params is None:
            self._cancel_reconnect()
            return
        interface, channel, bitrate = self._last_connect_params
        try:
            self.connection.connect(interface, channel, bitrate)
        except Exception:
            return  # adaptör hâlâ yok; sonraki turda tekrar dene
        state, _msg = self.connection.link_state()
        if state == "lost":
            self.connection.disconnect()  # açıldı ama sağlıksız: vazgeç, sonra tekrar dene
            return
        self._cancel_reconnect()
        self._log_event("BAGLANTI", "CAN adaptörü geri geldi, bağlantı otomatik yeniden kuruldu")
        self._after_connected(interface, channel, bitrate, reconnected=True)

    # ---- Alım (Receive) -----------------------------------------------
    RX_DRAIN_MAX_FRAMES = 400     # tek tick'te işlenecek en çok kare
    RX_DRAIN_MAX_SECONDS = 0.015  # ... ve en çok bu kadar süre (UI donmasın)

    def _drain_rx_queue(self):
        deadline = time.monotonic() + self.RX_DRAIN_MAX_SECONDS
        n = 0
        while n < self.RX_DRAIN_MAX_FRAMES and time.monotonic() < deadline:
            try:
                msg = self.connection.rx_queue.get_nowait()
            except queue.Empty:
                break
            n += 1
            self.monitor_tab.add_message(msg, direction="RX")
            self.control_panel_tab.on_can_frame(msg.arbitration_id, bytes(msg.data))
            self.performance_tab.on_can_frame(msg.arbitration_id, bytes(msg.data))
            self.workspace_tab.on_can_frame(msg.arbitration_id, bytes(msg.data))
            self._dash_on_can_frame(msg.arbitration_id, bytes(msg.data))
        self._drain_tx_queue()

    def _drain_tx_queue(self):
        """Gönderilen kareleri (elle, periyodik, Kontrol Paneli, güvenlik tekrarları; hangi iş parçacığı
        gönderdiyse) izleme tablosuna ve açık CSV kaydına aktarır."""
        for _ in range(self.RX_DRAIN_MAX_FRAMES):
            try:
                msg = self.connection.tx_queue.get_nowait()
            except queue.Empty:
                break
            self.monitor_tab.add_message(msg, direction="TX")

    def _on_monitor_frame(self, msg, direction: str):
        """İzleme sekmesi her RX/TX mesajı için çağırır (duraklatılmış olsa da): kayıt açıksa
        CSV'ye yön ve (DBC varsa) mesaj adıyla yazar."""
        if not self.can_logger.is_active:
            return
        name = ""
        dbc = self.transmit_tab.dbc
        if dbc.is_loaded:
            m = dbc.get_message_by_frame_id(msg.arbitration_id)
            name = m.name if m is not None else ""
        self.can_logger.write(msg.timestamp, msg.arbitration_id, msg.dlc, msg.data,
                              msg.is_extended_id, direction=direction, name=name)
        self._logged_count += 1
        self.log_tab.set_count(self._logged_count)
        if self.can_logger.error and not self.can_logger.is_active:
            self.log_tab.set_active(False, "")
            err = self.can_logger.error
            self.can_logger.error = None
            self._log_event("HATA", f"CAN kaydı yazma hatasıyla DURDU: {err}")
            QMessageBox.warning(self, "CAN kaydı durdu", f"Yazma hatası: {err}")

    def _startup_auto_connect(self):
        """"Açılışta otomatik bağlan" seçiliyse sessizce bağlanır; hata iletişim kutusu açmaz."""
        if self.connection.is_connected or not self.connection_tab.auto_connect_enabled():
            return
        interface = self.connection_tab.current_interface()
        channel = self.connection_tab.current_channel()
        bitrate = self.connection_tab.current_bitrate()
        try:
            self.connection.connect(interface, channel, bitrate)
        except Exception as exc:
            self.connection_tab.set_health(False, f"Otomatik bağlanma başarısız: {exc}")
            self._log_event("HATA", f"Otomatik bağlanma başarısız: {exc}")
            return
        self._after_connected(interface, channel, bitrate)

    # ---- Gönderim -------------------------------------------------------
    @staticmethod
    def _frame_text(can_id: int, data: bytes, extended: bool) -> str:
        return f"ID=0x{can_id:X}{' (ext)' if extended else ''} DLC={len(data)} DATA={data.hex(' ').upper()}"

    def _on_manual_send(self, can_id: int, data: bytes, extended: bool):
        if not can_transmit_frames(self.current_role):
            QMessageBox.warning(self, "Yetki yok",
                                "CAN çerçevesi göndermek için Mühendis veya Yönetici rolü gerekir "
                                "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
            return
        try:
            self.connection.send(can_id, data, extended)
        except Exception as exc:
            QMessageBox.critical(self, "Gönderim hatası", str(exc))
            self._log_event("HATA", f"Manuel gönderim başarısız: {exc}")
            return
        self._log_event("GÖNDERİM", "Manuel çerçeve gönderildi: " + self._frame_text(can_id, data, extended))
        self._drain_tx_queue()

    def _on_periodic_start(self, row_key: str, can_id: int, data: bytes,
                            extended: bool, period_ms: int):
        if not can_transmit_frames(self.current_role):
            self.transmit_tab.mark_start_failed(row_key)
            QMessageBox.warning(self, "Yetki yok",
                                "Periyodik gönderim için Mühendis veya Yönetici rolü gerekir "
                                "(sağ üstteki ⚙ Ayarlar penceresinden rol seçin).")
            return
        if self.periodic_manager is None:
            self.transmit_tab.mark_start_failed(row_key)
            QMessageBox.warning(self, "Bağlantı yok", "Önce CAN hattına bağlanın.")
            return
        try:
            self.periodic_manager.start(row_key, can_id, data, extended, period_ms)
        except Exception as exc:
            self.transmit_tab.mark_start_failed(row_key)
            QMessageBox.critical(self, "Periyodik gönderim hatası", str(exc))
            self._log_event("HATA", f"Periyodik gönderim başlatılamadı: {exc}")
            return
        self._log_event("GÖNDERİM", f"Periyodik gönderim BAŞLADI [{period_ms} ms]: "
                                    + self._frame_text(can_id, data, extended))

    def _on_periodic_stop(self, row_key: str):
        if self.periodic_manager is not None:
            try:
                self.periodic_manager.stop(row_key)
            except Exception as exc:  # noqa: BLE001
                self._log_event("HATA", f"Periyodik gönderim durdurulamadı: {exc}")
                return
            self._log_event("GÖNDERİM", "Periyodik gönderim durduruldu")

    # ---- Log --------------------------------------------------------------
    def _on_log_start(self, directory: str):
        try:
            path = self.can_logger.start(directory)
        except OSError as exc:
            QMessageBox.warning(self, "Kayıt başlatılamadı", f"Klasöre yazılamıyor: {exc}")
            self._log_event("HATA", f"CAN kaydı başlatılamadı: {exc}")
            return
        self._logged_count = 0
        self.log_tab.set_active(True, path)
        self.log_tab.set_count(0)

    def _on_log_stop(self):
        self.can_logger.stop()
        self.log_tab.set_active(False)
