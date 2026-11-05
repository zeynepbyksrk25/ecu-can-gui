"""Test amaçlı minimal bir CCP SLAVE simülatörü. Gerçek donanım olmadan,
CCPClient'ın CRO gönderip doğru DTO alıp almadığını uçtan uca test etmek
için kullanılır. Sahte bir bellek alanı (dict: address -> byte) tutar,
CONNECT/DISCONNECT/TEST/SET_MTA/UPLOAD/SHORT_UP/DNLOAD/DNLOAD_6/
GET_CCP_VERSION komutlarını destekler.

Bu, ürünün bir parçası DEĞİL — sadece test altyapısıdır.
"""

import threading

import can

from app.ccp import protocol as ccp


class _CallbackListener(can.Listener):
    def __init__(self, callback):
        self._callback = callback

    def on_message_received(self, msg: can.Message):
        self._callback(msg)


class CCPSlaveSimulator:
    def __init__(self, bus: can.BusABC, cro_id: int, dto_id: int, station_address: int = 0):
        self.bus = bus
        self.cro_id = cro_id
        self.dto_id = dto_id
        self.station_address = station_address

        self.memory: dict[int, int] = {}  # address -> byte değeri (sahte ECU RAM'i)
        self.flash: dict[int, int] = {}   # address -> byte değeri (sahte ECU FLAŞ'ı, PROGRAM/CLEAR_MEMORY hedefi)
        self._mta_address = 0
        self._mta_extension = 0
        self._connected = False

        self._notifier: can.Notifier | None = None
        self._listener = _CallbackListener(self._on_message)

        # Test edebilmek için istenirse belirli komutları reddetmeyi
        # simüle etmeye yarayan hook (örn. ACCESS_DENIED senaryosu).
        self.force_error_on: dict[int, int] = {}  # command_code -> return_code

        # Güç döngüsü simülasyonu: kapalıyken hiçbir komuta cevap verilmez; açılışta CCP oturumu
        # unutulur. strict_session=True iken CONNECT'ten önceki komutlar ACCESS_DENIED alır
        # (gerçek ECU davranışı).
        self.online = True
        self.strict_session = False
        self.response_delay_s = 0.0
        self.requests_seen = 0

    def power_off(self):
        """ECU gücü kesildi: komutlara cevap yok."""
        self.online = False

    def power_on(self):
        """ECU güç geldi: bellek korunur ama CCP oturumu unutulur (yeniden CONNECT gerekir)."""
        self._connected = False
        self._mta_address = 0
        self.online = True

    def start(self):
        self._notifier = can.Notifier(self.bus, [self._listener], timeout=0.1)

    def stop(self):
        if self._notifier is not None:
            self._notifier.stop()
            self._notifier = None

    def write_memory_bytes(self, address: int, data: bytes):
        for i, b in enumerate(data):
            self.memory[address + i] = b

    def read_memory_bytes(self, address: int, length: int) -> bytes:
        return bytes(self.memory.get(address + i, 0) for i in range(length))

    def _reply(self, return_code: int, ctr: int, data: bytes = b""):
        payload = bytes([ccp.PID_COMMAND_RETURN, return_code, ctr]) + data
        payload = payload + b"\x00" * (8 - len(payload))
        self.bus.send(can.Message(arbitration_id=self.dto_id, data=payload, is_extended_id=False))

    def _on_message(self, msg: can.Message):
        if msg.arbitration_id != self.cro_id or not msg.data:
            return
        if not self.online:
            return
        self.requests_seen += 1
        if self.response_delay_s:
            import time as _t
            _t.sleep(self.response_delay_s)
        cmd = msg.data[0]
        ctr = msg.data[1] if len(msg.data) > 1 else 0
        if self.strict_session and not self._connected and cmd not in (ccp.CONNECT, ccp.GET_CCP_VERSION):
            self._reply(ccp.RC_ACCESS_DENIED, ctr)
            return

        if cmd in self.force_error_on:
            self._reply(self.force_error_on[cmd], ctr)
            return

        handler = {
            ccp.CONNECT: self._handle_connect,
            ccp.DISCONNECT: self._handle_disconnect,
            ccp.TEST: self._handle_test,
            ccp.GET_CCP_VERSION: self._handle_get_ccp_version,
            ccp.SET_MTA: self._handle_set_mta,
            ccp.UPLOAD: self._handle_upload,
            ccp.SHORT_UP: self._handle_short_upload,
            ccp.DNLOAD: self._handle_dnload,
            ccp.DNLOAD_6: self._handle_dnload6,
            ccp.DIAG_SERVICE: self._handle_diag_service,
            ccp.CLEAR_MEMORY: self._handle_clear_memory,
            ccp.PROGRAM: self._handle_program,
            ccp.PROGRAM_6: self._handle_program6,
        }.get(cmd)

        if handler is None:
            self._reply(ccp.RC_CMD_UNKNOWN, ctr)
            return
        handler(msg.data, ctr)

    def _handle_connect(self, data, ctr):
        self._connected = True
        self._reply(ccp.RC_OK, ctr)

    def _handle_disconnect(self, data, ctr):
        self._connected = False
        self._reply(ccp.RC_OK, ctr)

    def _handle_test(self, data, ctr):
        if not self._connected:
            self._reply(ccp.RC_ACCESS_DENIED, ctr)
            return
        self._reply(ccp.RC_OK, ctr)

    def _handle_get_ccp_version(self, data, ctr):
        self._reply(ccp.RC_OK, ctr, bytes([2, 1]))  # v2.1

    def _handle_set_mta(self, data, ctr):
        # [CMD, CTR, MTA#, EXT, ADDR(4, big-endian)]
        self._mta_extension = data[3]
        self._mta_address = int.from_bytes(data[4:8], "big")
        self._reply(ccp.RC_OK, ctr)

    def _handle_upload(self, data, ctr):
        size = data[2]
        chunk = self.read_memory_bytes(self._mta_address, size)
        self._mta_address += size
        self._reply(ccp.RC_OK, ctr, chunk)

    def _handle_short_upload(self, data, ctr):
        size = data[2]
        ext = data[3]
        address = int.from_bytes(data[4:8], "big")
        chunk = self.read_memory_bytes(address, size)
        self._reply(ccp.RC_OK, ctr, chunk)

    def _handle_dnload(self, data, ctr):
        size = data[2]
        payload = data[3:3 + size]
        self.write_memory_bytes(self._mta_address, payload)
        self._mta_address += size
        self._reply(ccp.RC_OK, ctr, bytes([size]) + self.read_memory_bytes(self._mta_address - size, min(size, 4)))

    def _handle_diag_service(self, data, ctr):
        # Test/simülasyon amaçlı basit yankı (echo): servis numarasını ve
        # ilk parametre baytını geri döner, böylece Diagnostics ekranının
        # uçtan uca çalıştığı doğrulanabilir. Gerçek ECU'nun servisleri
        # farklı davranacaktır (bkz. protocol.py build_diag_service notu).
        service_lo, service_hi = data[2], data[3]
        param0 = data[4] if len(data) > 4 else 0
        self._reply(ccp.RC_OK, ctr, bytes([service_lo, service_hi, param0]))

    def _handle_dnload6(self, data, ctr):
        payload = data[2:8]
        self.write_memory_bytes(self._mta_address, payload)
        self._mta_address += 6
        self._reply(ccp.RC_OK, ctr)

    # ---- Kalıcı (flaş) yazma - test amaçlı, ayrı bir "flash" dict'i hedefler ----
    def _handle_clear_memory(self, data, ctr):
        size = int.from_bytes(data[4:8], "big")
        for i in range(size):
            self.flash.pop(self._mta_address + i, None)
        self._reply(ccp.RC_OK, ctr)

    def _handle_program(self, data, ctr):
        size = data[2]
        payload = data[3:3 + size]
        for i, b in enumerate(payload):
            self.flash[self._mta_address + i] = b
        self._mta_address += size
        self._reply(ccp.RC_OK, ctr)

    def _handle_program6(self, data, ctr):
        payload = data[2:8]
        for i, b in enumerate(payload):
            self.flash[self._mta_address + i] = b
        self._mta_address += 6
        self._reply(ccp.RC_OK, ctr)

    def read_flash_bytes(self, address: int, length: int) -> bytes:
        return bytes(self.flash.get(address + i, 0) for i in range(length))
