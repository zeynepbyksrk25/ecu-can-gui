"""CCP master (client) - python-can uzerinden CRO gonderip DTO bekleyen
istek/cevap motoru.

Iki calisma modu var:
  1) dto_queue VERILMEDEN: kendi can.Notifier'ini acar, bus'i kendisi
     dinler. Bagimsiz kullanim / test icin uygundur (bkz. testler).
  2) dto_queue VERILEREK: kendi Notifier'ini ACMAZ, DTO mesajlarini
     disaridan (CanConnection'in tek RX thread'inden) beslenen bir
     queue.Queue'dan okur. GUI'de boyle kullanilir, cunku ayni bus
     uzerinde iki ayri thread'in bus.recv()'i yarismasi mesaj kaybina
     yol acar (bkz. app/can_worker.py ccp_queue).

Tasarim notu: SRS'in DAQ (surekli olcum akisi) gereksinimi bu katmanda
YOK - bu ilk surum sadece "polling" (STIM/DAQ degil, dogrudan
UPLOAD/SHORT_UP ile okuma) yapar. Dashboard'daki 'canli degerler'
bu yontemle, kisa araliklarla tekrar tekrar UPLOAD gonderilerek
guncellenir. Gercek DAQ (event-driven, sync/cyclic) ayri bir asama.
"""

import contextlib
import queue
import threading
import time

import can

from app.ccp import protocol as ccp


class CCPVerifyError(ValueError):
    """Yazma sonrası geri okunan bayt, yazılandan farklı."""


class CCPShortResponseError(ValueError):
    """DTO beklenenden az veri taşıdı (kısa/bozuk cevap)."""


# MTA0'ı ilerleten veya ECU'da kalıcı etki yaratan komutlar İDEMPOTENT
# DEĞİLDİR: cevabı (DTO) kaybolan bir DNLOAD/UPLOAD/PROGRAM aynı CTR ile
# yeniden gönderilirse ECU komutu ikinci kez çalıştırır (MTA ilerlediği
# için bitişik belleğe yazar / bir sonraki baytları okur). Bu yüzden bu
# komutlar OTOMATİK YENİDEN DENENMEZ; çağıran (SET_MTA ile başlayan) üst
# seviye işlem hatayı görür.
_NON_IDEMPOTENT = frozenset({
    ccp.UPLOAD, ccp.DNLOAD, ccp.DNLOAD_6, ccp.PROGRAM, ccp.PROGRAM_6, ccp.CLEAR_MEMORY,
})

# Flaş silme saniyeler sürebilir (varsayılan 0.5 s timeout çok kısa).
FLASH_CLEAR_TIMEOUT = 10.0


class _CallbackListener(can.Listener):
    """can.Listener soyut bir sınıftır (on_message_received abstract);
    basit bir callback'e sarmak için minimal somut alt sınıf."""

    def __init__(self, callback):
        self._callback = callback

    def on_message_received(self, msg: can.Message):
        self._callback(msg)


class CCPClient:
    def __init__(self, bus: can.BusABC, cro_id: int, dto_id: int,
                 station_address: int = 0, timeout: float = 0.5, retries: int = 2,
                 dto_queue: "queue.Queue[can.Message] | None" = None):
        self.bus = bus
        self.cro_id = cro_id
        self.dto_id = dto_id
        self.station_address = station_address
        self.timeout = timeout
        self.retries = retries

        self._ctr = 0
        self._connected = False
        self._lock = threading.Lock()  # CCP protokolü tek seferde tek komut bekler
        self._ctr_lock = threading.Lock()
        # MTA0'a dayanan çok komutlu diziler (SET_MTA + DNLOAD/PROGRAM) BÖLÜNEMEZ: araya başka bir iş
        # parçacığının SET_MTA'sı girerse yazma yanlış adrese gider. Uzun yazmalar arka plan iş parçacığında,
        # güvenlik komutları arayüz iş parçacığında çalıştığı için her dizi bu kilit altında yürür.
        self._seq_lock = threading.RLock()
        # Python kilitleri adil değildir: parça parça yazan uzun iş kilidi bırakıp hemen geri alabilir.
        # Acil komut bekliyorsa (urgent) uzun iş bir sonraki parçadan önce ona yol verir.
        self._urgent_waiters = 0
        self._urgent_lock = threading.Lock()
        self._tls = threading.local()      # in_urgent: bu iş parçacığı urgent bloğunun içinde mi

        # dto_queue verildiyse (GUI kullanımı) o kuyruğu okuruz; verilmediyse
        # (bağımsız/test kullanımı) kendi Notifier'ımızı açıp kendi
        # kuyruğumuza yazarız.
        self._external_queue = dto_queue
        self._response_queue: "queue.Queue[can.Message]" = (
            dto_queue if dto_queue is not None else queue.Queue()
        )
        self._notifier: can.Notifier | None = None
        self._listener = _CallbackListener(self._on_message)

        self.last_error: str | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _next_ctr(self) -> int:
        with self._ctr_lock:
            self._ctr = (self._ctr + 1) % 256
            return self._ctr

    def _on_message(self, msg: can.Message):
        if msg.arbitration_id == self.dto_id and msg.data and msg.data[0] == ccp.PID_COMMAND_RETURN:
            self._response_queue.put(msg)

    def start_listening(self):
        if self._external_queue is not None:
            return  # dışarıdan beslenen kuyruk kullanılıyor, kendi Notifier'ımız gereksiz
        if self._notifier is None:
            self._notifier = can.Notifier(self.bus, [self._listener], timeout=0.1)

    def stop_listening(self):
        if self._notifier is not None:
            self._notifier.stop()
            self._notifier = None

    def _send_and_wait(self, cro: bytes, expected_ctr: int, retries: int | None = None,
                       timeout: float | None = None) -> tuple[int, bytes]:
        """CRO gönderir, eşleşen CTR'li DTO'yu bekler. Zaman aşımında
        `retries` kez yeniden dener. Dönen: (return_code, data[5])."""
        # Aynı istasyona ait eski cevapları (retry öncesi) temizle.
        while not self._response_queue.empty():
            try:
                self._response_queue.get_nowait()
            except queue.Empty:
                break

        retries = self.retries if retries is None else retries
        timeout = self.timeout if timeout is None else timeout
        attempts = retries + 1
        last_exc = None
        for attempt in range(attempts):
            self.bus.send(can.Message(arbitration_id=self.cro_id, data=cro, is_extended_id=False))
            deadline = time.time() + timeout
            while time.time() < deadline:
                remaining = deadline - time.time()
                try:
                    msg = self._response_queue.get(timeout=max(remaining, 0))
                except queue.Empty:
                    break
                if msg.arbitration_id != self.dto_id or not msg.data or msg.data[0] != ccp.PID_COMMAND_RETURN:
                    continue  # dış kuyruk modunda başka amaçlı mesajlar da gelebilir
                try:
                    return_code, ctr, data = ccp.parse_command_response(msg.data)
                except ValueError:
                    continue
                if ctr != expected_ctr:
                    continue  # eski/başka bir isteğin cevabı, yoksay
                return return_code, data
            last_exc = ccp.CCPTimeoutError(
                f"CCP: DTO cevabı {timeout}s içinde gelmedi (deneme {attempt + 1}/{attempts})."
            )
        raise last_exc

    def _command(self, cro: bytes, ctr: int, command_code: int, timeout: float | None = None) -> bytes:
        retries = 0 if command_code in _NON_IDEMPOTENT else None
        with self._lock:
            return_code, data = self._send_and_wait(cro, ctr, retries=retries, timeout=timeout)
        if return_code != ccp.RC_OK:
            self.last_error = ccp.return_code_name(return_code)
            raise ccp.CCPError(command_code, return_code)
        self.last_error = None
        return data

    # ---- Dizi kilidi / öncelik -------------------------------------------
    @contextlib.contextmanager
    def urgent(self):
        """Bu blok içindeki yazmalar, süren uzun bir yazmanın (harita/flaş) parçaları ARASINA girer:
        uzun iş en çok bir parça (SET_MTA + DNLOAD) sonra yol verir. Acil Durdurma, override kapatma ve
        arayüz iş parçacığından yapılan kısa yazmalar için."""
        with self._urgent_lock:
            self._urgent_waiters += 1
        try:
            with self._seq_lock:
                self._tls.in_urgent = True
                try:
                    yield self
                finally:
                    self._tls.in_urgent = False
        finally:
            with self._urgent_lock:
                self._urgent_waiters -= 1

    @contextlib.contextmanager
    def _sequence(self):
        """MTA0'a dayanan bir komut dizisini bölünmez yapar; öncelikli bekleyen varsa önce ona yol verir."""
        if getattr(self._tls, "in_urgent", False):
            yield                         # urgent bloğunun içi: kilit zaten bu iş parçacığında
            return
        while self._urgent_waiters > 0:
            time.sleep(0.001)
        with self._seq_lock:
            yield

    # ---- Yüksek seviye CCP işlemleri ------------------------------------
    def connect(self):
        self.start_listening()
        ctr = self._next_ctr()
        cro = ccp.build_connect(ctr, self.station_address)
        self._command(cro, ctr, ccp.CONNECT)
        self._connected = True

    def disconnect(self, permanent: bool = False):
        if not self._connected:
            self.stop_listening()
            return
        try:
            ctr = self._next_ctr()
            cro = ccp.build_disconnect(ctr, self.station_address, permanent=permanent)
            self._command(cro, ctr, ccp.DISCONNECT)
        finally:
            self._connected = False
            self.stop_listening()

    def test_connection(self) -> bool:
        """TEST komutuyla bağlantının hâlâ ayakta olup olmadığını kontrol
        eder (SRS: bağlantı kesilirse tespit edip kullanıcıyı uyarma)."""
        try:
            ctr = self._next_ctr()
            cro = ccp.build_test(ctr, self.station_address)
            self._command(cro, ctr, ccp.TEST)
            return True
        except (ccp.CCPError, ccp.CCPTimeoutError):
            return False

    def get_ccp_version(self) -> tuple[int, int]:
        ctr = self._next_ctr()
        cro = ccp.build_get_ccp_version(ctr)
        data = self._command(cro, ctr, ccp.GET_CCP_VERSION)
        return data[0], data[1]  # major, minor

    def diag_service(self, service_number: int, params: bytes = b"") -> bytes:
        """DIAG_SERVICE (0x20) için ham geçiş (passthrough): servis
        numarası ve parametre biçimi ECU'ya özeldir, bu katman yorumlamaz
        (bkz. app/ccp/protocol.py build_diag_service docstring'i)."""
        ctr = self._next_ctr()
        cro = ccp.build_diag_service(ctr, service_number, params)
        return self._command(cro, ctr, ccp.DIAG_SERVICE)

    def set_mta(self, address: int, address_extension: int = 0, mta_number: int = 0):
        ctr = self._next_ctr()
        cro = ccp.build_set_mta(ctr, address, address_extension, mta_number)
        self._command(cro, ctr, ccp.SET_MTA)

    @staticmethod
    def _exact(data: bytes, size: int, name: str) -> bytes:
        if len(data) < size:
            raise CCPShortResponseError(f"{name}: {size} bayt beklendi, {len(data)} bayt geldi.")
        return bytes(data[:size])

    def upload(self, size: int) -> bytes:
        """Mevcut MTA0'dan `size` bayt okur (MTA0 sürücüde otomatik ilerler).
        size en fazla 5; daha büyük okumalar read_memory() ile parçalanır."""
        ctr = self._next_ctr()
        cro = ccp.build_upload(ctr, size)
        data = self._command(cro, ctr, ccp.UPLOAD)
        return self._exact(data, size, "UPLOAD")

    def short_upload(self, address: int, size: int, address_extension: int = 0) -> bytes:
        """SET_MTA'ya gerek kalmadan tek komutla (adres + boyut) okur."""
        ctr = self._next_ctr()
        cro = ccp.build_short_upload(ctr, size, address, address_extension)
        data = self._command(cro, ctr, ccp.SHORT_UP)
        return self._exact(data, size, "SHORT_UP")

    def dnload(self, data: bytes) -> bytes:
        """Mevcut MTA0'a en fazla 5 bayt yazar (önce set_mta() çağrılmalı)."""
        ctr = self._next_ctr()
        cro = ccp.build_dnload(ctr, data)
        return self._command(cro, ctr, ccp.DNLOAD)

    def dnload6(self, data: bytes) -> bytes:
        ctr = self._next_ctr()
        cro = ccp.build_dnload6(ctr, data)
        return self._command(cro, ctr, ccp.DNLOAD_6)

    def read_memory(self, address: int, length: int, address_extension: int = 0) -> bytes:
        """Herhangi bir uzunlukta veriyi, gerektiği kadar SHORT_UP/UPLOAD
        komutuna bölerek okur (her CCP komutu en fazla 5 bayt taşıyabilir)."""
        # Her parça SHORT_UP ile okunur: adres her seferinde açıkça verildiği
        # için komut İDEMPOTENT'tir (kayıp DTO'da güvenle yeniden denenir;
        # SET_MTA+UPLOAD çiftinde ise tekrar MTA'yı kaydırırdı).
        result = bytearray()
        remaining = length
        addr = address
        while remaining > 0:
            chunk = min(5, remaining)
            result += self.short_upload(addr, chunk, address_extension)
            addr += chunk
            remaining -= chunk
        return bytes(result)

    def write_memory(self, address: int, data: bytes, address_extension: int = 0,
                     verify: bool = False):
        """Herhangi bir uzunlukta veriyi SET_MTA + DNLOAD/DNLOAD_6 ile yazar.
        verify=True ise yazdıktan sonra geri okuyup karşılaştırır ve fark
        varsa CCPVerifyError fırlatır. DNLOAD otomatik yeniden denenmez."""
        offset = 0
        while offset < len(data):
            chunk = data[offset:offset + 6]
            with self._sequence():
                self.set_mta(address + offset, address_extension)
                if len(chunk) == 6:
                    self.dnload6(chunk)
                else:
                    self.dnload(chunk)
            offset += len(chunk)
        if verify:
            back = self.read_memory(address, len(data), address_extension)
            if back != bytes(data):
                raise CCPVerifyError(
                    f"Yazma doğrulaması başarısız @0x{address:08X}: yazılan {bytes(data).hex()} "
                    f"!= okunan {back.hex()}"
                )

    # ---- Kalıcı (flaş) yazma -------------------------------------------
    # DİKKAT: Bu metotlar ASAM CCP 2.1 spesifikasyonundaki standart
    # CLEAR_MEMORY/PROGRAM/PROGRAM_6 çerçeve biçimini uygular (bkz.
    # app/ccp/protocol.py). Ancak M220 ECU'sunun GERÇEK flaş programlama
    # AKIŞI (örn. CLEAR_MEMORY'nin zorunlu olup olmadığı, önceden bir
    # UNLOCK/seed-key adımı gerekip gerekmediği, flaş yazma sırasında
    # ECU'nun başka komutları reddedip reddetmediği) bu projede gerçek
    # donanımla DOĞRULANMADI. Arayüz katmanı (app/ui/ccp_tab.py,
    # app/ui/main_window.py) bu riski kullanıcıya açıkça göstermeden bu
    # metotları çağırmaz.
    def clear_memory(self, size: int):
        ctr = self._next_ctr()
        cro = ccp.build_clear_memory(ctr, size)
        self._command(cro, ctr, ccp.CLEAR_MEMORY, timeout=FLASH_CLEAR_TIMEOUT)

    def program(self, data: bytes) -> bytes:
        ctr = self._next_ctr()
        cro = ccp.build_program(ctr, data)
        return self._command(cro, ctr, ccp.PROGRAM)

    def program6(self, data: bytes) -> bytes:
        ctr = self._next_ctr()
        cro = ccp.build_program6(ctr, data)
        return self._command(cro, ctr, ccp.PROGRAM_6)

    def write_flash_memory(self, address: int, data: bytes, address_extension: int = 0,
                            clear_first: bool = True, verify: bool = False):
        """SET_MTA + (isteğe bağlı) CLEAR_MEMORY + PROGRAM/PROGRAM_6 ile
        KALICI (flaş) belleğe yazar. write_memory()'nin flaş karşılığıdır;
        aynı 5/6 baytlık parçalama mantığını kullanır."""
        offset = 0
        while offset < len(data) or offset == 0:
            chunk = data[offset:offset + 6]
            with self._sequence():
                self.set_mta(address + offset, address_extension)
                if offset == 0 and clear_first:
                    self.clear_memory(len(data))
                    self.set_mta(address, address_extension)  # bazı ECU'lar CLEAR_MEMORY sonrası MTA0'ı sıfırlayabilir
                if chunk:
                    if len(chunk) == 6:
                        self.program6(chunk)
                    else:
                        self.program(chunk)
            offset += len(chunk)
            if not chunk:
                break
        if verify:
            back = self.read_memory(address, len(data), address_extension)
            if back != bytes(data):
                raise CCPVerifyError(
                    f"Flaş doğrulaması başarısız @0x{address:08X}: yazılan {bytes(data).hex()} "
                    f"!= okunan {back.hex()}"
                )
