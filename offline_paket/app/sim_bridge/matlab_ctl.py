"""Simulink model yaşam döngüsü denetimi (Start/Pause/Resume/Stop/Reset, hız).

İki ayrı durum izlenir ve KARIŞTIRILMAZ:
  * model durumu  – ``ModelController.state`` (NOT CONNECTED, CONNECTING, READY, RUNNING, PAUSED, STOPPED, ERROR),
  * UDP bağlantı  – ``SimulinkUdpBus.link_state()`` (waiting/ok/timeout).

Komutlar ayrı bir iş parçacığındaki kuyrukta yürütülür: MATLAB Engine takılsa/kopsa GUI donmaz. Arka uçlar:
  * ``MatlabEngineBackend`` – MATLAB Engine API (``matlab.engine``; zorunlu bağımlılık DEĞİL, yoksa ``BackendUnavailable``).
                              GERÇEK MATLAB/Simulink ile doğrulanmadı.
  * ``UdpControlBackend``   – model UDP kontrol paketlerini işliyorsa (MATLAB gerektirmez); durum heartbeat'ten.
Hız: 0.25x/0.5x/1x/2x/5x/Fastest — yalnızca GUI zamanlayıcısı değil, Simulink pacing (``EnablePacing``/``PacingRate``)
ya da modelin ``CMD_SPEED`` işlemesiyle uygulanır.
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from app import sim_protocol as proto

log = logging.getLogger(__name__)

(NOT_CONNECTED, CONNECTING, READY, RUNNING, PAUSED, STOPPED, ERROR) = (
    "NOT CONNECTED", "CONNECTING", "READY", "RUNNING", "PAUSED", "STOPPED", "ERROR")
SPEEDS = [("0.25x", 0.25), ("0.5x", 0.5), ("1x", 1.0), ("2x", 2.0), ("5x", 5.0), ("Fastest", 0.0)]
_HB_TO_STATE = {proto.MS_READY: READY, proto.MS_RUNNING: RUNNING, proto.MS_PAUSED: PAUSED,
                proto.MS_STOPPED: STOPPED, proto.MS_ERROR: ERROR}
CMD_TIMEOUT_S = 15.0


class BackendUnavailable(RuntimeError):
    """MATLAB Engine yok / başlatılamadı."""


class ModelBackend:
    name = "?"

    def connect(self, model: str) -> None: ...
    def command(self, cmd: str, arg: float = 0.0) -> None: ...      # start|pause|resume|stop|reset|speed
    def status(self) -> str | None: ...                              # backend'in bildirdiği durum (varsa)
    def close(self) -> None: ...


class MatlabEngineBackend(ModelBackend):
    name = "MATLAB Engine"

    def __init__(self, engine_factory=None):
        self._factory = engine_factory
        self._eng = None
        self._model = ""

    def connect(self, model: str) -> None:
        if self._factory is None:
            try:
                import matlab.engine as me          # noqa: PLC0415 - isteğe bağlı bağımlılık
            except ImportError as exc:
                raise BackendUnavailable("MATLAB Engine API for Python kurulu değil") from exc
            self._factory = me.start_matlab
        try:
            self._eng = self._factory()
            self._model = model
            self._eng.load_system(model, nargout=0)
        except Exception as exc:  # noqa: BLE001 - MATLAB tarafı her tür hata verebilir
            raise BackendUnavailable(f"MATLAB/model açılamadı: {exc}") from exc

    def command(self, cmd: str, arg: float = 0.0) -> None:
        e, m = self._eng, self._model
        if e is None:
            raise BackendUnavailable("MATLAB bağlı değil")
        if cmd == "speed":
            e.set_param(m, "EnablePacing", "off" if arg == 0 else "on", nargout=0)
            if arg:
                e.set_param(m, "PacingRate", str(float(arg)), nargout=0)
            return
        sim_cmd = {"start": "start", "pause": "pause", "resume": "continue", "stop": "stop", "reset": "stop"}[cmd]
        e.set_param(m, "SimulationCommand", sim_cmd, nargout=0)

    def status(self) -> str | None:
        if self._eng is None:
            return None
        try:
            return str(self._eng.get_param(self._model, "SimulationStatus"))
        except Exception as exc:  # noqa: BLE001
            raise BackendUnavailable(f"MATLAB yanıt vermiyor: {exc}") from exc

    def close(self) -> None:
        eng, self._eng = self._eng, None
        if eng is not None:
            try:
                eng.quit()
            except Exception:  # noqa: BLE001
                log.debug("MATLAB kapatılamadı", exc_info=True)


class UdpControlBackend(ModelBackend):
    name = "UDP kontrol"
    _CODES = {"start": proto.CMD_START, "pause": proto.CMD_PAUSE, "resume": proto.CMD_RESUME, "stop": proto.CMD_STOP,
              "reset": proto.CMD_RESET, "speed": proto.CMD_SPEED}

    def __init__(self, bus):
        self.bus = bus

    def connect(self, model: str) -> None:
        if self.bus is None:
            raise BackendUnavailable("MIL bus açık değil")

    def command(self, cmd: str, arg: float = 0.0) -> None:
        self.bus.send_control(self._CODES[cmd], arg)

    def status(self) -> str | None:
        return None

    def close(self) -> None:
        pass


class ModelController:
    """Durum makinesi + komut iş parçacığı. ``bus`` (opsiyonel): heartbeat'ten model durumu ve simülasyon zamanı."""

    def __init__(self, backend: ModelBackend | None = None, bus=None, on_change=None):
        self.backend = backend
        self.bus = bus
        self.on_change = on_change
        self.state = NOT_CONNECTED
        self.error = ""
        self.speed = 1.0
        self.sim_time = 0.0
        self.events: list = []                   # (wall_time, metin): Start/Pause/Stop vb. (kayıt olayları için)
        self._q: "queue.Queue" = queue.Queue()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._busy = False
        self._expected: str | None = None        # komut sonrası beklenen durum (backend durum bildirmiyorsa)

    # ---- yaşam ---------------------------------------------------------------------------------
    def start_worker(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="model-ctl", daemon=True)
            self._thread.start()

    def close(self):
        self._stop.set()
        self._q.put(None)
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self.backend is not None:
            self.backend.close()
        self._set(NOT_CONNECTED)

    def connect(self, model: str = ""):
        """Arka uç bağlantısı (ayrı iş parçacığında; GUI bloke olmaz)."""
        self.start_worker()
        self._set(CONNECTING)
        self._q.put(("connect", model, 0.0))

    def command(self, cmd: str, arg: float = 0.0) -> bool:
        """start|pause|resume|stop|reset|speed. Geçersiz geçiş reddedilir (False)."""
        if cmd != "speed" and not self.allowed(cmd):
            return False
        self.start_worker()
        self._q.put(("cmd", cmd, arg))
        return True

    def allowed(self, cmd: str) -> bool:
        s = self.state
        table = {"start": (READY, STOPPED), "pause": (RUNNING,), "resume": (PAUSED,), "stop": (RUNNING, PAUSED),
                 "reset": (READY, RUNNING, PAUSED, STOPPED, ERROR)}
        return s in table.get(cmd, ())

    def set_speed(self, factor: float):
        self.speed = float(factor)
        return self.command("speed", factor)

    # ---- iş parçacığı ---------------------------------------------------------------------------
    def _run(self):
        while not self._stop.is_set():
            try:
                item = self._q.get(timeout=0.2)
            except queue.Empty:
                self._poll()
                continue
            if item is None:
                return
            kind, a, b = item
            self._busy = True
            try:
                if kind == "connect":
                    self.backend.connect(a)
                    self._set(READY if self.state == CONNECTING else self.state)
                else:
                    self.backend.command(a, b)
                    self._after_command(a)
            except BackendUnavailable as exc:
                self.error = str(exc)
                self._set(ERROR if kind == "cmd" or self.state != NOT_CONNECTED else NOT_CONNECTED)
                if kind == "connect":
                    self._set(NOT_CONNECTED)
            except Exception as exc:  # noqa: BLE001
                self.error = f"{type(exc).__name__}: {exc}"
                self._set(ERROR)
            finally:
                self._busy = False
            self._poll()

    def _after_command(self, cmd: str):
        self.events.append((time.time(), f"Model {cmd}"))
        nxt = {"start": RUNNING, "pause": PAUSED, "resume": RUNNING, "stop": STOPPED, "reset": READY}.get(cmd)
        if nxt:
            self._expected = nxt
            self._set(nxt)

    def _poll(self):
        """Heartbeat'ten sim zamanı/durum, backend'den (varsa) durum. Heartbeat gelmiyorsa model durumu tahmini kalır."""
        if self.bus is not None:
            self.sim_time = getattr(self.bus, "sim_time", 0.0)
            link = self.bus.link_state()[0]
            hb = _HB_TO_STATE.get(getattr(self.bus, "model_state", proto.MS_UNKNOWN))
            if link == "ok" and hb is not None and self.state not in (NOT_CONNECTED, CONNECTING) and hb != self.state:
                self._set(hb)
        if self.backend is not None and self.state not in (NOT_CONNECTED, CONNECTING):
            try:
                st = self.backend.status()
            except BackendUnavailable as exc:
                self.error = str(exc)
                self._set(ERROR)
                return
            if st:
                mapped = {"running": RUNNING, "paused": PAUSED, "stopped": STOPPED, "initializing": READY,
                          "compiled": READY, "terminating": STOPPED}.get(st.lower())
                if mapped == STOPPED and self.state in (READY, ERROR):
                    mapped = None                  # hiç başlatılmamış/sıfırlanmış model Simulink'te de "stopped" görünür
                if mapped and mapped != self.state and not self._busy:
                    self._set(mapped)

    def _set(self, state: str):
        with self._lock:
            changed = state != self.state
            self.state = state
        if changed and self.on_change:
            try:
                self.on_change(state)
            except Exception:  # noqa: BLE001
                log.debug("on_change hata verdi", exc_info=True)

    def snapshot(self) -> dict:
        link = self.bus.link_state() if self.bus is not None else ("n/a", "")
        return {"state": self.state, "error": self.error, "sim_time": self.sim_time, "speed": self.speed,
                "udp": link[0], "udp_text": link[1], "backend": getattr(self.backend, "name", "-")}
