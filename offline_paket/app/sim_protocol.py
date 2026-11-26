"""Simulink MIL UDP paket protokolü (GUI <-> Simulink modeli). Küçük-endian, sabit boyutlu paketler.

Başlık (16 bayt):
    ofs  boyut  alan
     0    2     magic = 0x4543 ("EC")
     2    1     sürüm = 1
     3    1     tür   (1=CAN kare, 2=heartbeat, 3=kontrol komutu)
     4    4     sıra no (uint32; gönderen artırır; kayıp tespiti için)
     8    8     simülasyon zamanı (double, sn)  -> MIL zaman tabanı; GUI alım zamanıyla KARIŞTIRILMAZ

CAN kare yükü (14 bayt; toplam 30):
    16   4     CAN ID (uint32; düşük 29 bit)
    20   1     bayrak: bit0=extended ID, bit1=RTR
    21   1     DLC (0..8)
    22   8     veri (DLC'den sonrası 0)

Heartbeat yükü (4 bayt; toplam 20):
    16   1     model durumu (0=bilinmiyor,1=hazır,2=çalışıyor,3=duraklatıldı,4=durdu,5=hata)
    17   3     ayrılmış (0)

Kontrol yükü (8 bayt; toplam 24) GUI -> model:
    16   1     komut (1=start,2=pause,3=resume,4=stop,5=reset,6=hız ayarla)
    17   3     ayrılmış
    20   4     argüman (float32; hız çarpanı, 0 = en hızlı)

Alıcı HATALI paketi (boyut/magic/sürüm/tür/DLC>8/ID aralığı) reddeder ve sayar; paket asla "yarım" yorumlanmaz.
CAN çerçevesi fiziksel bir hat DEĞİLDİR: bitrate/bus durumu yoktur.
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass

MAGIC = 0x4543
VERSION = 1
T_CAN, T_HEARTBEAT, T_CONTROL = 1, 2, 3
HEADER = struct.Struct("<HBBId")            # 16 bayt
CAN_BODY = struct.Struct("<IBB8s")          # 14 bayt
HB_BODY = struct.Struct("<B3x")             # 4 bayt
CTRL_BODY = struct.Struct("<B3xf")          # 8 bayt
SIZES = {T_CAN: HEADER.size + CAN_BODY.size, T_HEARTBEAT: HEADER.size + HB_BODY.size,
         T_CONTROL: HEADER.size + CTRL_BODY.size}

(MS_UNKNOWN, MS_READY, MS_RUNNING, MS_PAUSED, MS_STOPPED, MS_ERROR) = range(6)
MODEL_STATE_NAMES = {MS_UNKNOWN: "UNKNOWN", MS_READY: "READY", MS_RUNNING: "RUNNING", MS_PAUSED: "PAUSED",
                     MS_STOPPED: "STOPPED", MS_ERROR: "ERROR"}
(CMD_START, CMD_PAUSE, CMD_RESUME, CMD_STOP, CMD_RESET, CMD_SPEED) = range(1, 7)
FLAG_EXT, FLAG_RTR = 1, 2


class ProtocolError(ValueError):
    """Geçersiz paket (neden mesajda)."""


@dataclass
class Packet:
    type: int
    seq: int
    sim_time: float
    can_id: int = 0
    extended: bool = False
    rtr: bool = False
    data: bytes = b""
    model_state: int = MS_UNKNOWN
    command: int = 0
    arg: float = 0.0


def encode_can(seq: int, sim_time: float, can_id: int, data: bytes, extended: bool = False, rtr: bool = False) -> bytes:
    if len(data) > 8:
        raise ProtocolError(f"DLC {len(data)} > 8")
    max_id = 0x1FFFFFFF if extended else 0x7FF
    if not 0 <= can_id <= max_id:
        raise ProtocolError(f"CAN ID aralık dışı: 0x{can_id:X}")
    flags = (FLAG_EXT if extended else 0) | (FLAG_RTR if rtr else 0)
    return (HEADER.pack(MAGIC, VERSION, T_CAN, seq & 0xFFFFFFFF, float(sim_time))
            + CAN_BODY.pack(can_id, flags, len(data), bytes(data).ljust(8, b"\0")))


def encode_heartbeat(seq: int, sim_time: float, model_state: int) -> bytes:
    return HEADER.pack(MAGIC, VERSION, T_HEARTBEAT, seq & 0xFFFFFFFF, float(sim_time)) + HB_BODY.pack(model_state)


def encode_control(seq: int, command: int, arg: float = 0.0) -> bytes:
    return HEADER.pack(MAGIC, VERSION, T_CONTROL, seq & 0xFFFFFFFF, 0.0) + CTRL_BODY.pack(command, float(arg))


def decode(buf: bytes) -> Packet:
    if len(buf) < HEADER.size:
        raise ProtocolError(f"paket çok kısa ({len(buf)} bayt)")
    magic, ver, typ, seq, sim_time = HEADER.unpack_from(buf, 0)
    if magic != MAGIC:
        raise ProtocolError(f"magic hatalı: 0x{magic:04X}")
    if ver != VERSION:
        raise ProtocolError(f"desteklenmeyen sürüm {ver}")
    if typ not in SIZES:
        raise ProtocolError(f"bilinmeyen tür {typ}")
    if len(buf) != SIZES[typ]:
        raise ProtocolError(f"tür {typ} için boyut {len(buf)} (beklenen {SIZES[typ]})")
    if not math.isfinite(sim_time):
        raise ProtocolError("simülasyon zamanı sonlu değil")
    if typ == T_CAN:
        cid, flags, dlc, data = CAN_BODY.unpack_from(buf, HEADER.size)
        if dlc > 8:
            raise ProtocolError(f"DLC {dlc} > 8")
        ext = bool(flags & FLAG_EXT)
        if cid > (0x1FFFFFFF if ext else 0x7FF):
            raise ProtocolError(f"CAN ID aralık dışı: 0x{cid:X}")
        return Packet(typ, seq, sim_time, can_id=cid, extended=ext, rtr=bool(flags & FLAG_RTR), data=data[:dlc])
    if typ == T_HEARTBEAT:
        (state,) = HB_BODY.unpack_from(buf, HEADER.size)
        return Packet(typ, seq, sim_time, model_state=state if state in MODEL_STATE_NAMES else MS_UNKNOWN)
    cmd, arg = CTRL_BODY.unpack_from(buf, HEADER.size)
    if cmd < CMD_START or cmd > CMD_SPEED or not math.isfinite(arg):
        raise ProtocolError(f"geçersiz komut {cmd}")
    return Packet(typ, seq, sim_time, command=cmd, arg=arg)
