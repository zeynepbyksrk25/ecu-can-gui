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
        self.params = {}
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
            elif p.type == proto.T_CONTROL:
                self.received_cmds.append((p.command, p.arg))
                self.state = {proto.CMD_START: proto.MS_RUNNING, proto.CMD_PAUSE: proto.MS_PAUSED,
                              proto.CMD_RESUME: proto.MS_RUNNING, proto.CMD_STOP: proto.MS_STOPPED,
                              proto.CMD_RESET: proto.MS_READY}.get(p.command, self.state)

    def close(self):
        self._stop.set()
        self.thread.join(timeout=1)
        self.sock.close()
