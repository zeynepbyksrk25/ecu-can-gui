"""ASAM CCP (CAN Calibration Protocol) v2.1 - CRO/DTO cerceve kodlama/cozme.

Cerceve yapisi, klasik CAN'in 8 bayt data alanina oturur:
  CRO (Master -> Slave): [CMD, CTR, ...6 bayt komuta ozel parametre...]
  DTO (Slave -> Master): [PID, ...]
    PID = 0xFF -> Command Return Message: [0xFF, ReturnCode, CTR, ...5 bayt veri...]
    PID = 0xFE -> Event Message (bu surumde islenmiyor)
    PID = 0x00-0xFD -> DAQ verisi (bu surumde kullanilmiyor)

ONEMLI - bayt sirasi: CONNECT'teki istasyon adresi KUCUK-ENDIAN (Intel),
ama SET_MTA/SHORT_UP'taki adres BUYUK-ENDIAN (Motorola) kodlanir. Bu,
CCP spesifikasyonunun kendi ic tutarsizligidir; gercek ornek bayt
izlerinden dogrulanmistir, tahmin degildir.
"""

import struct

# ---- Komut kodlari (ASAM CCP 2.1) -------------------------------------
CONNECT = 0x01
SET_MTA = 0x02
DNLOAD = 0x03
UPLOAD = 0x04
TEST = 0x05
START_STOP = 0x06
DISCONNECT = 0x07
START_STOP_ALL = 0x08
GET_ACTIVE_CAL_PAGE = 0x09
SET_S_STATUS = 0x0C
GET_S_STATUS = 0x0D
BUILD_CHKSUM = 0x0E
SHORT_UP = 0x0F
CLEAR_MEMORY = 0x10
SELECT_CAL_PAGE = 0x11
GET_SEED = 0x12
UNLOCK = 0x13
GET_DAQ_SIZE = 0x14
SET_DAQ_PTR = 0x15
WRITE_DAQ = 0x16
EXCHANGE_ID = 0x17
PROGRAM = 0x18
MOVE = 0x19
GET_CCP_VERSION = 0x1B
DIAG_SERVICE = 0x20
ACTION_SERVICE = 0x21
PROGRAM_6 = 0x22
DNLOAD_6 = 0x23

PID_COMMAND_RETURN = 0xFF
PID_EVENT = 0xFE

COMMAND_NAMES = {
    CONNECT: "CONNECT", SET_MTA: "SET_MTA", DNLOAD: "DNLOAD", UPLOAD: "UPLOAD",
    TEST: "TEST", START_STOP: "START_STOP", DISCONNECT: "DISCONNECT",
    START_STOP_ALL: "START_STOP_ALL", GET_ACTIVE_CAL_PAGE: "GET_ACTIVE_CAL_PAGE",
    SET_S_STATUS: "SET_S_STATUS", GET_S_STATUS: "GET_S_STATUS",
    BUILD_CHKSUM: "BUILD_CHKSUM", SHORT_UP: "SHORT_UP", CLEAR_MEMORY: "CLEAR_MEMORY",
    SELECT_CAL_PAGE: "SELECT_CAL_PAGE", GET_SEED: "GET_SEED", UNLOCK: "UNLOCK",
    GET_DAQ_SIZE: "GET_DAQ_SIZE", SET_DAQ_PTR: "SET_DAQ_PTR", WRITE_DAQ: "WRITE_DAQ",
    EXCHANGE_ID: "EXCHANGE_ID", PROGRAM: "PROGRAM", MOVE: "MOVE",
    GET_CCP_VERSION: "GET_CCP_VERSION", DIAG_SERVICE: "DIAG_SERVICE",
    ACTION_SERVICE: "ACTION_SERVICE", PROGRAM_6: "PROGRAM_6", DNLOAD_6: "DNLOAD_6",
}

# ---- Command Return Code'lar (DTO byte[1]) ----------------------------
RC_OK = 0x00
RC_DNLOAD_BUSY = 0x02
RC_UPLOAD_BUSY = 0x03
RC_CMD_UNKNOWN = 0x05
RC_CMD_SYNTAX = 0x06
RC_OUT_OF_RANGE = 0x07
RC_ACCESS_DENIED = 0x08
RC_OVERLOAD = 0x09
RC_ACCESS_LOCKED = 0x0A
RC_RESOURCE_NOT_AVAILABLE = 0x0B

RETURN_CODE_NAMES = {
    RC_OK: "OK",
    RC_DNLOAD_BUSY: "DNLOAD_BUSY",
    RC_UPLOAD_BUSY: "UPLOAD_BUSY",
    RC_CMD_UNKNOWN: "CMD_UNKNOWN",
    RC_CMD_SYNTAX: "CMD_SYNTAX",
    RC_OUT_OF_RANGE: "OUT_OF_RANGE",
    RC_ACCESS_DENIED: "ACCESS_DENIED",
    RC_OVERLOAD: "OVERLOAD",
    RC_ACCESS_LOCKED: "ACCESS_LOCKED",
    RC_RESOURCE_NOT_AVAILABLE: "RESOURCE_NOT_AVAILABLE",
}


def return_code_name(code: int) -> str:
    return RETURN_CODE_NAMES.get(code, f"UNKNOWN(0x{code:02X})")


class CCPError(Exception):
    """Slave bir CRO'ya OK disinda bir return code ile cevap verdi."""

    def __init__(self, command: int, return_code: int):
        self.command = command
        self.return_code = return_code
        name = COMMAND_NAMES.get(command, f"0x{command:02X}")
        super().__init__(f"CCP hatasi: komut={name}, return_code={return_code_name(return_code)}")


class CCPTimeoutError(Exception):
    """Slave'den zamaninda (ve yeniden denemelere ragmen) DTO cevabi gelmedi."""
    pass


def _pad(data: bytes) -> bytes:
    if len(data) > 8:
        raise ValueError("CRO/DTO 8 bayttan uzun olamaz.")
    return data + b"\x00" * (8 - len(data))


# ---- CRO olusturucular --------------------------------------------------
def build_connect(ctr: int, station_address: int) -> bytes:
    return _pad(bytes([CONNECT, ctr]) + struct.pack("<H", station_address))


def build_disconnect(ctr: int, station_address: int, permanent: bool = False) -> bytes:
    flag = 0x01 if permanent else 0x00
    return _pad(bytes([DISCONNECT, ctr, flag, 0x00]) + struct.pack("<H", station_address))


def build_test(ctr: int, station_address: int) -> bytes:
    return _pad(bytes([TEST, ctr]) + struct.pack("<H", station_address))


def build_get_seed(ctr: int, resource: int = 0) -> bytes:
    return _pad(bytes([GET_SEED, ctr, resource]))


def build_unlock(ctr: int, key: bytes) -> bytes:
    if len(key) > 6:
        raise ValueError("UNLOCK anahtari en fazla 6 bayt olabilir.")
    return _pad(bytes([UNLOCK, ctr]) + key)


def build_set_mta(ctr: int, address: int, address_extension: int = 0, mta_number: int = 0) -> bytes:
    # Adres BUYUK-ENDIAN kodlanir (bkz. modul docstring'i).
    return bytes([SET_MTA, ctr, mta_number, address_extension]) + struct.pack(">I", address)


def build_upload(ctr: int, size: int) -> bytes:
    if not (1 <= size <= 5):
        raise ValueError("UPLOAD tek seferde en fazla 5 bayt okuyabilir (size 1-5).")
    return _pad(bytes([UPLOAD, ctr, size]))


def build_short_upload(ctr: int, size: int, address: int, address_extension: int = 0) -> bytes:
    if not (1 <= size <= 5):
        raise ValueError("SHORT_UP tek seferde en fazla 5 bayt okuyabilir.")
    return bytes([SHORT_UP, ctr, size, address_extension]) + struct.pack(">I", address)


def build_dnload(ctr: int, data: bytes) -> bytes:
    if not (1 <= len(data) <= 5):
        raise ValueError("DNLOAD tek seferde en fazla 5 bayt yazabilir (6 bayt icin DNLOAD_6 kullanin).")
    return _pad(bytes([DNLOAD, ctr, len(data)]) + data)


def build_dnload6(ctr: int, data: bytes) -> bytes:
    if len(data) != 6:
        raise ValueError("DNLOAD_6 tam olarak 6 bayt bekler.")
    return bytes([DNLOAD_6, ctr]) + data


def build_get_ccp_version(ctr: int, major: int = 2, minor: int = 1) -> bytes:
    return _pad(bytes([GET_CCP_VERSION, ctr, major, minor]))


def build_exchange_id(ctr: int, device_info: bytes = b"") -> bytes:
    return _pad(bytes([EXCHANGE_ID, ctr]) + device_info[:6])


def build_get_s_status(ctr: int) -> bytes:
    return _pad(bytes([GET_S_STATUS, ctr]))


def build_set_s_status(ctr: int, status_bits: int) -> bytes:
    return _pad(bytes([SET_S_STATUS, ctr, status_bits]))


def build_select_cal_page(ctr: int) -> bytes:
    return _pad(bytes([SELECT_CAL_PAGE, ctr]))


def build_get_active_cal_page(ctr: int) -> bytes:
    return _pad(bytes([GET_ACTIVE_CAL_PAGE, ctr]))


def build_build_chksum(ctr: int, size: int) -> bytes:
    return _pad(bytes([BUILD_CHKSUM, ctr]) + struct.pack(">I", size))


def build_clear_memory(ctr: int, size: int) -> bytes:
    # ASAM CCP 2.1 standardı: [CLEAR_MEMORY, CTR, rezerve, rezerve,
    # Size(4 bayt, BUYUK-ENDIAN)]. Bu, SET_MTA/UPLOAD ile aynı disiplinle
    # (bkz. modül docstring'i) spesifikasyondan uygulanmıştır; ANCAK
    # M220 ECU'sunun GERÇEK flaş programlama akışının (CLEAR_MEMORY'nin
    # ön koşul olup olmadığı, gerekli UNLOCK/seed-key adımları vb.)
    # gerçek donanımla DOĞRULANMADIĞI unutulmamalı — bkz. app/ccp/client.py
    # write_flash_memory() ve arayüzdeki "Deneysel flaş yazma" uyarıları.
    return _pad(bytes([CLEAR_MEMORY, ctr, 0x00, 0x00]) + struct.pack(">I", size))


def build_program(ctr: int, data: bytes) -> bytes:
    # DNLOAD ile aynı çerçeve yapısı: [PROGRAM, CTR, Size, ...Data (<=5 bayt)].
    # Mevcut MTA0'a yazar, sürücüde otomatik ilerler.
    if not (1 <= len(data) <= 5):
        raise ValueError("PROGRAM tek seferde en fazla 5 bayt yazabilir (6 bayt icin PROGRAM_6 kullanin).")
    return _pad(bytes([PROGRAM, ctr, len(data)]) + data)


def build_program6(ctr: int, data: bytes) -> bytes:
    if len(data) != 6:
        raise ValueError("PROGRAM_6 tam olarak 6 bayt bekler.")
    return bytes([PROGRAM_6, ctr]) + data


def build_diag_service(ctr: int, service_number: int, params: bytes = b"") -> bytes:
    # NOT: DIAG_SERVICE'in parametre yerleşimi ASAM CCP 2.1'de üreticiye
    # bırakılmıştır (servis numarasından sonraki baytların anlamı ECU'ya
    # özeldir). Burada yaygın kullanılan yerleşim uygulanmıştır: servis
    # numarası küçük-endian 2 bayt, ardından en fazla 4 parametre baytı.
    # Gerçek M220 ECU'sunun servis numaraları/parametre biçimi
    # doğrulanmadan bilinmiyor; bu fonksiyon ham bir "geçiş" (passthrough)
    # aracı olarak kullanılmalı, sonucu yorumlamak kullanıcıya kalır.
    if len(params) > 4:
        raise ValueError("DIAG_SERVICE en fazla 4 parametre baytı taşıyabilir.")
    return _pad(bytes([DIAG_SERVICE, ctr]) + struct.pack("<H", service_number) + params)


# ---- DTO cozucu ----------------------------------------------------------
def parse_command_response(dto: bytes) -> tuple[int, int, bytes]:
    """DTO'yu (return_code, ctr, data[5]) olarak ayristirir. PID komut
    cevabi (0xFF) degilse ValueError firlatir (event/DAQ mesaji farkli
    ele alinmali, bu fonksiyonun kapsaminda degil)."""
    if len(dto) < 3 or dto[0] != PID_COMMAND_RETURN:
        raise ValueError(f"Komut cevabi degil (PID=0x{dto[0]:02X})")
    return_code = dto[1]
    ctr = dto[2]
    data = bytes(dto[3:8])
    return return_code, ctr, data
