"""``SimulinkUdpBus``: UDP üzerinden CAN kareleri taşıyan python-can ``BusABC`` uyumlu backend (MIL).

GUI ile Simulink aynı bilgisayarda; DBC iki tarafta ortak olduğundan Python'da mevcut DBC kodlama/çözme aynen kullanılır.
Bu bir fiziksel CAN hattı DEĞİLDİR: bitrate / bus-off / PCAN durumu yoktur; bağlantı sağlığı heartbeat'e bağlıdır:
  * ``waiting``  – henüz paket gelmedi (model başlamadı);
  * ``ok``       – son paket/heartbeat ``timeout_s`` içinde;
  * ``timeout``  – daha önce veri vardı, ``timeout_s`` boyunca hiçbir şey gelmedi (model durdu / UDP kaybı).
Model sonradan başlarsa/yeniden başlarsa bağlantı kendiliğinden ``ok``'a döner (soket açık kalır).

Zaman tabanları ayrı: ``msg.timestamp`` = GUI'nin alım anı (wall-clock); ``msg.sim_time`` = paketteki simülasyon zamanı.
"""
from __future__ import annotations

import logging
import queue
import socket
import threading
import time

import can

from app import sim_protocol as proto

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 2.0
HEARTBEAT_TX_S = 0.5


class SimMessage(can.Message):
    """``can.Message`` + paketteki simülasyon zamanı (``sim_time``); ``timestamp`` GUI alım zamanı kalır."""
    __slots__ = ("sim_time",)


def parse_channel(channel: str) -> tuple[int, str, int]:
    """``"yerel_port:uzak_host:uzak_port"`` (ör. ``"25000:127.0.0.1:25001"``); boş → varsayılan."""
    if not channel:
        return 25001, "127.0.0.1", 25000
    parts = str(channel).split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]), parts[1], int(parts[2])
        if len(parts) == 2:
            return int(parts[0]), "127.0.0.1", int(parts[1])
    except ValueError:
        pass
    raise ValueError(f"Geçersiz MIL kanalı {channel!r}; biçim: yerel_port:uzak_host:uzak_port")


class SimulinkUdpBus(can.BusABC):
    def __init__(self, channel: str = "", timeout_s: float = DEFAULT_TIMEOUT_S, heartbeat: bool = True,
                 bind_host: str = "127.0.0.1", **kwargs):
        self.local_port, self.remote_host, self.remote_port = parse_channel(channel)
        self.channel_info = f"Simulink UDP {bind_host}:{self.local_port} -> {self.remote_host}:{self.remote_port}"
        super().__init__(channel=channel, **kwargs)
        self.timeout_s = timeout_s
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((bind_host, self.local_port))
        self._sock.settimeout(0.1)
        self.local_port = self._sock.getsockname()[1]            # 0 verildiyse atanan port
        self._q: "queue.Queue[can.Message]" = queue.Queue(maxsize=50_000)
        self._stop = threading.Event()
        self._tx_seq = 0
        self._last_rx_seq: int | None = None
        self._lock = threading.Lock()
        # sağlık / istatistik
        self.rx_packets = 0
        self.rx_frames = 0
        self.bad_packets = 0
        self.last_bad_reason = ""
        self.lost_packets = 0                    # sıra numarasından çıkarılan (UDP kaybı)
        self.dropped_frames = 0                  # kuyruk doldu
        self.sim_time = 0.0
        self.model_state = proto.MS_UNKNOWN
        self._last_rx_mono: float | None = None
        self.last_rx_gap = 0.0
        self._thread = threading.Thread(target=self._rx_loop, name="sim-udp-rx", daemon=True)
        self._thread.start()
        self._param_lock = threading.Lock()            # aynı anda tek parametre işlemi
        self._param_wait: dict = {}                    # indeks -> [Event, sonuç]
        self._hb_thread = None
        if heartbeat:
            self._hb_thread = threading.Thread(target=self._hb_loop, name="sim-udp-hb", daemon=True)
            self._hb_thread.start()

    # ---- python-can API -----------------------------------------------------------------
    def send(self, msg: can.Message, timeout=None) -> None:
        if msg.is_error_frame:
            raise can.CanOperationError("Hata karesi MIL'de gönderilemez")
        data = bytes(msg.data)
        pkt = proto.encode_can(self._next_seq(), self.sim_time, msg.arbitration_id, data,
                               bool(msg.is_extended_id), bool(msg.is_remote_frame))
        self._send_raw(pkt)

    def _recv_internal(self, timeout):
        try:
            return self._q.get(timeout=timeout if timeout is not None else 0.1), False
        except queue.Empty:
            return None, False

    def shutdown(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for th in (self._thread, self._hb_thread):
            if th is not None:
                th.join(timeout=1.0)
        try:
            self._sock.close()
        except OSError:
            pass
        super().shutdown()

    # ---- kontrol / durum ------------------------------------------------------------------
    def send_control(self, command: int, arg: float = 0.0):
        self._send_raw(proto.encode_control(self._next_seq(), command, arg))

    def param_request(self, op: int, index: int, value: float = 0.0, timeout: float = 0.5, retries: int = 1):
        """Parametre yaz/oku; modelden (op, durum, değer) yanıtını bekler. Yanıt gelmezse ``TimeoutError``.
        Yazmada dönen değer modelde UYGULANAN değerdir (ACK)."""
        with self._param_lock:
            ev = threading.Event()
            slot = [ev, None]
            self._param_wait[index] = slot
            try:
                for _ in range(retries + 1):
                    ev.clear()
                    self._send_raw(proto.encode_param(self._next_seq(), op, index, value))
                    if ev.wait(timeout):
                        return slot[1]
                raise TimeoutError(f"Model parametre {index} için yanıt vermedi")
            finally:
                self._param_wait.pop(index, None)

    def link_state(self) -> tuple[str, str]:
        """("waiting"|"ok"|"timeout", açıklama). Fiziksel bus durumu YOKTUR."""
        if self._last_rx_mono is None:
            return "waiting", "Model bekleniyor (henüz paket yok)"
        age = time.monotonic() - self._last_rx_mono
        if age > self.timeout_s:
            return "timeout", f"Modelden {age:.1f} sn'dir veri yok (model durdu veya UDP kaybı)"
        return "ok", f"Model verisi akıyor (simülasyon zamanı {self.sim_time:.3f} s)"

    def stats(self) -> dict:
        state, text = self.link_state()
        return {"link": state, "text": text, "rx_packets": self.rx_packets, "rx_frames": self.rx_frames,
                "bad_packets": self.bad_packets, "lost_packets": self.lost_packets,
                "dropped_frames": self.dropped_frames, "sim_time": self.sim_time,
                "model_state": proto.MODEL_STATE_NAMES.get(self.model_state, "UNKNOWN")}

    # ---- iç ---------------------------------------------------------------------------------
    def _next_seq(self) -> int:
        with self._lock:
            self._tx_seq = (self._tx_seq + 1) & 0xFFFFFFFF
            return self._tx_seq

    def _send_raw(self, pkt: bytes):
        try:
            self._sock.sendto(pkt, (self.remote_host, self.remote_port))
        except OSError as exc:
            raise can.CanOperationError(f"UDP gönderilemedi: {exc}") from exc

    def _hb_loop(self):
        while not self._stop.wait(HEARTBEAT_TX_S):
            try:
                self._send_raw(proto.encode_heartbeat(self._next_seq(), self.sim_time, proto.MS_UNKNOWN))
            except can.CanError:
                pass

    def _rx_loop(self):
        while not self._stop.is_set():
            try:
                buf, _addr = self._sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                if self._stop.is_set():
                    return
                time.sleep(0.05)
                continue
            now = time.time()
            try:
                p = proto.decode(buf)
            except proto.ProtocolError as exc:
                self.bad_packets += 1
                self.last_bad_reason = str(exc)
                continue
            if p.type == proto.T_CONTROL:
                continue                                     # GUI'ye kontrol komutu gelmez; yok say
            if self._last_rx_seq is not None:
                gap = (p.seq - self._last_rx_seq) & 0xFFFFFFFF
                if 1 < gap < 0x80000000:
                    self.lost_packets += gap - 1
            self._last_rx_seq = p.seq
            mono = time.monotonic()
            if self._last_rx_mono is not None:
                self.last_rx_gap = mono - self._last_rx_mono
            self._last_rx_mono = mono
            self.rx_packets += 1
            self.sim_time = p.sim_time
            if p.type == proto.T_PARAM:
                w = self._param_wait.get(p.index)
                if w is not None and p.op in (proto.OP_VALUE, proto.OP_NAK):
                    w[1] = (p.op, p.status, p.value)
                    w[0].set()
                continue
            if p.type == proto.T_HEARTBEAT:
                self.model_state = p.model_state
                continue
            msg = SimMessage(timestamp=now, arbitration_id=p.can_id, is_extended_id=p.extended,
                             is_remote_frame=p.rtr, dlc=len(p.data), data=p.data, is_rx=True)
            msg.sim_time = p.sim_time
            try:
                self._q.put_nowait(msg)
                self.rx_frames += 1
            except queue.Full:
                self.dropped_frames += 1
