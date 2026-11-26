"""İletişim katmanı: python-can üzerinden bağlantı kurma ve arka planda
mesaj dinleme (Receive Thread). UI thread'i asla doğrudan bloklamaz;
gelen mesajlar thread-safe bir queue.Queue üzerinden aktarılır.
"""

import logging
import queue
import threading
import time

import can

log = logging.getLogger(__name__)

# PCAN-Basic durum kodlarından "hat (bus) düzeyi" olanlar: kablo/ECU/sonlandırma
# kaynaklı geçici durumlardır, ADAPTÖR gitmiş demek DEĞİLDİR (ör. ECU kapalıyken
# hiçbir düğüm ACK vermediği için BUSHEAVY/BUSOFF görülür). Bunların DIŞINDAKİ
# her hata kodu (ILLHW, NODRIVER, INITIALIZE...) adaptörün/sürücünün
# kaybolduğu anlamına gelir. Değerler PEAK PCAN-Basic başlığındandır.
_PCAN_BUS_LEVEL_BITS = (
    0x1        # XMTFULL
    | 0x2      # OVERRUN
    | 0x4      # BUSLIGHT
    | 0x8      # BUSHEAVY / BUSWARNING
    | 0x10     # BUSOFF
    | 0x20     # QRCVEMPTY
    | 0x80     # QXMTFULL
    | 0x40000  # BUSPASSIVE
)

# Hat toparlama (bus-off kurtarma) zamanlamaları
SILENT_S = 1.5                  # bu kadar süre hiç mesaj gelmediyse hat "sessiz" sayılır
RESET_INTERVAL_S = 2.0          # kurtarma denemeleri arası en az süre
MAX_RESETS_BEFORE_REOPEN = 3    # bu kadar reset işe yaramazsa adaptör yeniden açılır
RECOVERY_PROBE_S = 1.0          # toparlanırken en çok saniyede 1 kare gönderilir (hattı boğma)

# Alım döngüsünde art arda bu kadar HATA (boş-kuyruk zaman aşımı değil, gerçek
# okuma hatası) görülürse adaptör kaybolmuş sayılır.
RX_ERROR_STREAK_LIMIT = 3


RX_QUEUE_MAX = 50000
TX_QUEUE_MAX = 20000
CCP_QUEUE_MAX = 2000


class BusRecovering(RuntimeError):
    """Hat bus-off/hata durumundan toparlanırken gönderim geçici olarak yavaşlatıldı."""


class CanConnection:
    """Tek bir CAN bus bağlantısını yönetir.

    interface: 'virtual' (tek pencere içi test), 'udp_multicast' (aynı
    bilgisayarda birden fazla pencere arasında test) veya 'pcan' (Windows +
    gerçek PCAN-USB donanımı için).
    """

    def __init__(self, bus_factory=None):
        self._bus_factory = bus_factory or can.Bus     # testlerde sahte bus enjekte edilir
        self._params: dict | None = None
        self.on_reopen: list = []                      # bus yeniden açılınca çağrılacak geri çağrılar
        self.last_rx_mono = time.monotonic()           # son alınan mesajın zamanı (hat sessiz tespiti)
        self.recovering = False
        self._last_status_code: int | None = None
        self._last_recovery = 0.0
        self._last_probe_send = 0.0
        self._reset_attempts = 0
        self.reset_count = 0
        self.reopen_count = 0
        self.bus: can.BusABC | None = None
        self._recv_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        # Sınırlı kuyruk: UI takılırsa bellek sonsuz büyümesin. Taşan kareler
        # düşürülür ve sayılır (dropped_frames) — sessiz kayıp olmasın.
        self.rx_queue: "queue.Queue[can.Message]" = queue.Queue(maxsize=RX_QUEUE_MAX)
        self.dropped_frames = 0
        # Gönderilen kareler (elle, periyodik, Kontrol Paneli, güvenlik tekrarları): hangi iş parçacığı
        # gönderirse göndersin buraya düşer; arayüz izleme tablosuna ve CSV kaydına buradan aktarır.
        self.tx_queue: "queue.Queue[can.Message]" = queue.Queue(maxsize=TX_QUEUE_MAX)
        self.dropped_tx = 0
        # Alınan HER kare için (alım iş parçacığında, bloklamadan) çağrılır: oturum kaydı karenin GERÇEK geliş zamanında
        # yazabilsin diye (arayüz zamanlayıcısından bağımsız). Hatası alım döngüsünü durdurmaz.
        self.frame_tap = None
        self.tx_tap = None            # gönderilen her kare için (oturum kaydı ASC'ye Tx olarak yazar); bloklamaz
        # CCP/CAL katmanı aynı fiziksel bus'ı paylaşır; tek RX thread her
        # mesajı okuyup CCP DTO ID'sine uyanları da (rx_queue'ya EK olarak)
        # bu kuyruğa yazar. İki ayrı thread'in aynı bus.recv()'i yarışarak
        # çağırması mesaj kaybına yol açacağı için CCP kendi Notifier'ını
        # AÇMAZ, bu kuyruğu okur (bkz. app/ccp/client.py).
        self.ccp_dto_id: int | None = None
        self.ccp_queue: "queue.Queue[can.Message]" = queue.Queue(maxsize=CCP_QUEUE_MAX)

        # Bağlantı kopması tespiti için alım döngüsünün hata sayaçları.
        self.rx_error_streak = 0
        self.last_rx_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self.bus is not None

    def connect(self, interface: str, channel: str, bitrate: int):
        if self.is_connected:
            raise RuntimeError("Zaten bağlı; önce disconnect() çağırın.")

        kwargs = {"interface": interface, "channel": channel}
        if interface not in ("virtual", "udp_multicast"):
            kwargs["bitrate"] = bitrate
        elif interface == "udp_multicast":
            kwargs["bitrate"] = bitrate  # udp_multicast bitrate kabul eder (bilgi amaçlı)
        if interface == "pcan":
            # ECU kapalıyken hattı kimse ACK'lemez; kontrolcü BUS-OFF'a düşer ve PCAN-USB
            # kendiliğinden çıkmaz. Sürücünün otomatik bus-off kurtarmasını aç.
            kwargs["auto_reset"] = True
        self._params = dict(kwargs)
        self._open_bus_and_thread()

    def _open_bus_and_thread(self):
        self.bus = self._bus_factory(**self._params)
        self.rx_error_streak = 0
        self.last_rx_error = None
        self.last_rx_mono = time.monotonic()
        self.recovering = False
        self._last_status_code = None
        self._reset_attempts = 0
        self._stop_event.clear()
        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()

    def disconnect(self):
        self._stop_event.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=1.0)
            self._recv_thread = None
        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                # Adaptör fiziksel olarak çıkarılmışsa shutdown() hata
                # verebilir; yine de bağlantıyı temizlemeliyiz.
                pass
            self.bus = None

    def send(self, arbitration_id: int, data: bytes, extended: bool):
        if not self.is_connected:
            raise RuntimeError("Bağlantı yok.")
        if self.recovering:
            # Hat toparlanırken gönderimi saniyede 1 kareye indir (hattı daha da hataya sokma);
            # hat dönünce (alım başlayınca) otomatik tam hıza çıkılır.
            now = time.monotonic()
            if now - self._last_probe_send < RECOVERY_PROBE_S:
                raise BusRecovering("Hat toparlanıyor (bus-off kurtarma); gönderim geçici olarak bekletildi.")
            self._last_probe_send = now
        msg = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=extended,
        )
        self.bus.send(msg)
        self.note_tx(msg)

    def note_tx(self, msg: "can.Message"):
        """Başarıyla gönderilmiş bir kareyi TX kuyruğuna yazar (her iş parçacığından çağrılabilir)."""
        # Kopya: periyodik görev aynı Message nesnesini yeniden kullanır; zaman damgası paylaşılmasın.
        copy = can.Message(timestamp=time.time(), arbitration_id=msg.arbitration_id, data=msg.data,
                           is_extended_id=msg.is_extended_id)
        try:
            self.tx_queue.put_nowait(copy)
        except queue.Full:
            self.dropped_tx += 1
        tap = self.tx_tap
        if tap is not None:
            try:
                tap(copy)
            except Exception:  # noqa: BLE001
                log.debug("tx_tap hata verdi", exc_info=True)

    def link_state(self) -> tuple[str, str]:
        """Bağlantının GERÇEK durumunu sürücüden sorgular ve üç durumdan
        birini döner:

          ("ok", mesaj)           -> sağlıklı
          ("bus_warning", mesaj)  -> adaptör var ama hat sorunlu (ECU kapalı,
                                     sonlandırma eksik, bus-off vb.); bağlantı
                                     KOPMUŞ sayılmaz
          ("lost", mesaj)         -> adaptör/sürücü yanıt vermiyor (USB çıkarıldı,
                                     sürücü gitti...) — bağlantı kopmuştur

        Sadece can.Bus() çağrısının hata fırlatmamış olmasına güvenilmez;
        ayrıca alım thread'inin art arda okuma hatası verip vermediğine de
        bakılır (pcan USB çıkarılınca okuma hata fırlatmaya başlar).
        virtual/udp_multicast gibi donanımsız arayüzlerde sorgulanacak
        gerçek bir durum yoktur, sabit "ok" döner."""
        if not self.is_connected:
            return "lost", "Bağlı değil"
        if self.rx_error_streak >= RX_ERROR_STREAK_LIMIT:
            return "lost", f"Okuma hatası: {self.last_rx_error or 'adaptör yanıt vermiyor'}"
        if hasattr(self.bus, "status"):
            try:
                status = self.bus.status()
            except Exception as exc:
                return "lost", f"Durum sorgulanamadı: {exc}"
            if status == 0:
                return "ok", "OK"
            status_text = ""
            try:
                status_text = getattr(self.bus, "status_string", lambda: None)() or ""
            except Exception:
                log.debug("durum metni okunamadı", exc_info=True)
            status_text = status_text or f"Durum kodu 0x{status:X}"
            if status & ~_PCAN_BUS_LEVEL_BITS:
                return "lost", status_text
            return "bus_warning", status_text
        if hasattr(self.bus, "status_is_ok"):
            try:
                ok = self.bus.status_is_ok()
            except Exception as exc:
                return "lost", f"Durum sorgulanamadı: {exc}"
            if ok:
                return "ok", "OK"
            return "bus_warning", getattr(self.bus, "status_string", lambda: None)() or "Bilinmeyen hata"
        return "ok", "OK (bu arayüzde donanım durum sorgusu yok)"

    # ---- Bus-off kurtarma bekçisi ------------------------------------------------
    def silent_for(self) -> float:
        """Son mesajdan bu yana geçen süre (sn)."""
        return time.monotonic() - self.last_rx_mono

    def _status_code(self):
        if self.bus is not None and hasattr(self.bus, "status"):
            try:
                return int(self.bus.status())
            except Exception:
                return None
        return None

    def watchdog(self) -> list:
        """MainWindow tarafından ~500 ms'de bir çağrılır. Hat hatalı (bus-off/ağır hata) VE
        sessizse önce ``bus.reset()`` dener, işe yaramazsa adaptörü AYNI parametrelerle yeniden
        açar (Bağlantıyı kes + Bağlan'ın otomatiği). Günlüğe yazılacak olayların listesini döner
        (PCAN durum kodu geçişleri dahil — gerçek donanımda teşhis içindir)."""
        events: list = []
        if not self.is_connected:
            return events
        now = time.monotonic()
        state, message = self.link_state()
        code = self._status_code()
        if code is not None and code != self._last_status_code:
            if self._last_status_code is not None or code != 0:
                events.append(f"PCAN durum kodu 0x{code:X} ({message}); son mesaj {self.silent_for():.1f} sn önce")
            self._last_status_code = code

        self.recovering = state == "bus_warning" and self.silent_for() > SILENT_S
        if not self.recovering:
            return events
        if self.last_rx_mono > self._last_recovery:
            self._reset_attempts = 0          # son denemeden sonra mesaj geldi: hat düzeldi
        if now - self._last_recovery < RESET_INTERVAL_S:
            return events
        self._last_recovery = now
        if self._reset_attempts < MAX_RESETS_BEFORE_REOPEN:
            self._reset_attempts += 1
            ok = False
            if hasattr(self.bus, "reset"):
                try:
                    ok = bool(self.bus.reset())
                except Exception as exc:
                    events.append(f"Bus-off kurtarma: reset() hata verdi: {exc}")
            self.reset_count += 1
            events.append(f"Bus-off kurtarma: reset() {'tamam' if ok else 'başarısız'} "
                          f"({self._reset_attempts}/{MAX_RESETS_BEFORE_REOPEN})")
        else:
            self._reset_attempts = 0
            try:
                self.reopen()
                events.append("Bus-off kurtarma: reset işe yaramadı, adaptör yeniden açıldı")
            except Exception as exc:
                events.append(f"Bus-off kurtarma: adaptör yeniden açılamadı: {exc}")
        return events

    def reopen(self):
        """Bus'ı aynı parametrelerle kapatıp yeniden açar; dinleyicilere (periyodik gönderim,
        CCP) yeni bus'a geçmeleri için haber verir."""
        if self._params is None:
            raise RuntimeError("Önce connect() çağrılmalı.")
        self._stop_event.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=1.0)
            self._recv_thread = None
        if self.bus is not None:
            try:
                self.bus.shutdown()
            except Exception:
                log.warning("bus kapatılamadı (yeniden açılıyor)", exc_info=True)
            self.bus = None
        self._open_bus_and_thread()
        self.reopen_count += 1
        for cb in list(self.on_reopen):
            try:
                cb()
            except Exception:
                log.exception("bus yeniden açma geri çağrısı hata verdi")

    def is_healthy(self) -> tuple[bool, str]:
        """Geriye uyumluluk: link_state() "ok" ise True."""
        state, message = self.link_state()
        return state == "ok", message

    def _receive_loop(self):
        """Ayrı thread'de çalışır: bus.recv() bloklasa bile UI donmaz,
        çünkü bu thread UI thread'inden bağımsızdır."""
        while not self._stop_event.is_set():
            bus = self.bus
            if bus is None:
                time.sleep(0.05)
                continue
            try:
                msg = bus.recv(timeout=0.2)
            except Exception as exc:  # CanError ve sürücü/OS düzeyindeki beklenmedik hatalar
                self.rx_error_streak += 1
                self.last_rx_error = str(exc)
                time.sleep(0.1)
                continue
            self.rx_error_streak = 0  # hatasız bir okuma (mesaj ya da temiz zaman aşımı)
            if msg is not None:
                self.last_rx_mono = time.monotonic()
                msg.timestamp = time.time()
                try:
                    self.rx_queue.put_nowait(msg)
                except queue.Full:
                    self.dropped_frames += 1
                tap = self.frame_tap
                if tap is not None:
                    try:
                        tap(msg)
                    except Exception:  # noqa: BLE001
                        log.debug("frame_tap hata verdi", exc_info=True)
                if self.ccp_dto_id is not None and msg.arbitration_id == self.ccp_dto_id:
                    try:
                        self.ccp_queue.put_nowait(msg)
                    except queue.Full:
                        self.dropped_frames += 1
