"""Sahte Simulink modeli (test/geliştirme): UDP'de gerçek modelin konuştuğu protokolü konuşur. MATLAB gerektirmez.
GERÇEK Simulink ile doğrulanmış DEĞİLDİR."""
import socket
import threading
import time

from app import sim_protocol as proto


class FakeSimulink:
    def __init__(self, model_port: int, gui_port: int, dbc=None, host="127.0.0.1"):
        self.host, self.gui_port = host, gui_port
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, model_port))
        self.sock.settimeout(0.05)
        self.port = self.sock.getsockname()[1]
        self.dbc = dbc
        self.state = proto.MS_READY
        self.sim_time = 0.0
        self.seq = 0
        self.received_frames = []     # GUI'den gelen (id, data, extended)
        self.received_cmds = []
        self.params = {}               # indeks -> model değeri (parametre kanalı)
        self.tunable_running = set()   # çalışırken yazılabilen indeksler
        self.reject_range = {}         # indeks -> (min, max): dışındaki değer NAK
        self.ignore_params = False     # True: parametre isteklerine yanıt verme (zaman aşımı testi)
        self.clamp = {}                # indeks -> değer: yazılan ne olursa olsun bu uygulanır (doğrulama testi)
        self._stop = threading.Event()
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _next(self):
        self.seq += 1
        return self.seq

    def send_raw(self, pkt: bytes):
        self.sock.sendto(pkt, (self.host, self.gui_port))

    def send_frame(self, can_id: int, data: bytes, extended=False, sim_time=None, seq=None):
        self.send_raw(proto.encode_can(self._next() if seq is None else seq,
                                       self.sim_time if sim_time is None else sim_time, can_id, data, extended))

    def send_heartbeat(self):
        self.send_raw(proto.encode_heartbeat(self._next(), self.sim_time, self.state))

    def _loop(self):
        while not self._stop.is_set():
            try:
                buf, _ = self.sock.recvfrom(2048)
            except (socket.timeout, OSError):
                continue
            try:
                p = proto.decode(buf)
            except proto.ProtocolError:
                continue
            if p.type == proto.T_CAN:
                self.received_frames.append((p.can_id, p.data, p.extended))
            elif p.type == proto.T_PARAM and not self.ignore_params:
                self._on_param(p)
            elif p.type == proto.T_CONTROL:
                self.received_cmds.append((p.command, p.arg))
                self.state = {proto.CMD_START: proto.MS_RUNNING, proto.CMD_PAUSE: proto.MS_PAUSED,
                              proto.CMD_RESUME: proto.MS_RUNNING, proto.CMD_STOP: proto.MS_STOPPED,
                              proto.CMD_RESET: proto.MS_READY}.get(p.command, self.state)

    def _on_param(self, p):
        if p.index not in self.params:
            self.send_raw(proto.encode_param(self._next(), proto.OP_NAK, p.index, 0.0, proto.ST_UNKNOWN_INDEX))
            return
        if p.op == proto.OP_READ:
            self.send_raw(proto.encode_param(self._next(), proto.OP_VALUE, p.index, self.params[p.index]))
            return
        if self.state == proto.MS_RUNNING and p.index not in self.tunable_running:
            self.send_raw(proto.encode_param(self._next(), proto.OP_NAK, p.index, 0.0, proto.ST_NOT_TUNABLE_RUNNING))
            return
        lo, hi = self.reject_range.get(p.index, (float("-inf"), float("inf")))
        if not lo <= p.value <= hi:
            self.send_raw(proto.encode_param(self._next(), proto.OP_NAK, p.index, 0.0, proto.ST_OUT_OF_RANGE))
            return
        self.params[p.index] = self.clamp.get(p.index, p.value)
        self.send_raw(proto.encode_param(self._next(), proto.OP_VALUE, p.index, self.params[p.index]))

    def close(self):
        self._stop.set()
        self.thread.join(timeout=1)
        self.sock.close()
