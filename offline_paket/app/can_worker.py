"""İletişim katmanı: python-can üzerinden bağlantı kurma ve arka planda
mesaj dinleme (Receive Thread). UI thread'i asla doğrudan bloklamaz;
gelen mesajlar thread-safe bir queue.Queue üzerinden aktarılır.
"""

import queue
import threading
import time

import can

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

# Alım döngüsünde art arda bu kadar HATA (boş-kuyruk zaman aşımı değil, gerçek
# okuma hatası) görülürse adaptör kaybolmuş sayılır.
RX_ERROR_STREAK_LIMIT = 3


class CanConnection:
    """Tek bir CAN bus bağlantısını yönetir.

    interface: 'virtual' (tek pencere içi test), 'udp_multicast' (aynı
    bilgisayarda birden fazla pencere arasında test) veya 'pcan' (Windows +
    gerçek PCAN-USB donanımı için).
    """

    def __init__(self):
        self.bus: can.BusABC | None = None
        self._recv_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self.rx_queue: "queue.Queue[can.Message]" = queue.Queue()
        # CCP/CAL katmanı aynı fiziksel bus'ı paylaşır; tek RX thread her
        # mesajı okuyup CCP DTO ID'sine uyanları da (rx_queue'ya EK olarak)
        # bu kuyruğa yazar. İki ayrı thread'in aynı bus.recv()'i yarışarak
        # çağırması mesaj kaybına yol açacağı için CCP kendi Notifier'ını
        # AÇMAZ, bu kuyruğu okur (bkz. app/ccp/client.py).
        self.ccp_dto_id: int | None = None
        self.ccp_queue: "queue.Queue[can.Message]" = queue.Queue()

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

        self.bus = can.Bus(**kwargs)
        self.rx_error_streak = 0
        self.last_rx_error = None
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
        msg = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=extended,
        )
        self.bus.send(msg)

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
                pass
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

    def is_healthy(self) -> tuple[bool, str]:
        """Geriye uyumluluk: link_state() "ok" ise True."""
        state, message = self.link_state()
        return state == "ok", message

    def _receive_loop(self):
        """Ayrı thread'de çalışır: bus.recv() bloklasa bile UI donmaz,
        çünkü bu thread UI thread'inden bağımsızdır."""
        while not self._stop_event.is_set():
            try:
                msg = self.bus.recv(timeout=0.2)
            except Exception as exc:  # CanError ve sürücü/OS düzeyindeki beklenmedik hatalar
                self.rx_error_streak += 1
                self.last_rx_error = str(exc)
                time.sleep(0.1)
                continue
            self.rx_error_streak = 0  # hatasız bir okuma (mesaj ya da temiz zaman aşımı)
            if msg is not None:
                msg.timestamp = time.time()
                self.rx_queue.put(msg)
                if self.ccp_dto_id is not None and msg.arbitration_id == self.ccp_dto_id:
                    self.ccp_queue.put(msg)
