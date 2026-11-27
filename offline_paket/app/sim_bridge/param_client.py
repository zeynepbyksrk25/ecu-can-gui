"""MIL kalibrasyon istemcisi: ``CCPClient`` bellek arayüzünü (read_memory/write_memory) taklit eder, ama bayt yerine
UDP parametre kanalıyla Simulink modeline konuşur. Böylece Parametre Listesi, Harita Editörü, geçmiş, başlangıca dönüş
ve kayıt altyapısı DEĞİŞMEDEN MIL'de çalışır (aynı GUI, yalnızca backend farklı).

A2L adresleri yalnızca GUI içi anahtardır; model değişkenleriyle eşleme manifestten gelir (bkz. parameters.py).
"""
from __future__ import annotations

import contextlib
import threading

from app import sim_protocol as proto
from app.ccp import codec
from app.ccp import protocol as ccp
from app.sim_bridge.parameters import Manifest


class SimParamError(ccp.CCPError):
    """Model parametre işlemi reddetti / uygulanamadı (kullanıcıya gösterilecek açıklamalı)."""

    def __init__(self, message: str, return_code: int = ccp.RC_ACCESS_DENIED):
        Exception.__init__(self, message)
        self.command = 0
        self.return_code = return_code


class SimParamClient:
    cro_id = dto_id = station_address = 0
    timeout, retries = 0.5, 1

    def __init__(self, bus, manifest: Manifest, characteristics, model_state_provider=None):
        """``characteristics``: A2L Characteristic nesneleri (adres, datatype, compu_method, byte_order)."""
        self.bus = bus
        self._model_state = model_state_provider or (lambda: getattr(bus, "model_state", proto.MS_UNKNOWN))
        self._cells: dict = {}                      # adres -> (ParamMap, hücre_no, karakteristik, hücre boyutu)
        by_a2l = manifest.by_a2l()
        self.unmapped: list = []
        for c in characteristics:
            pm = by_a2l.get(c.name)
            if pm is None or getattr(c, "address", None) is None or not c.datatype:
                if pm is None:
                    self.unmapped.append(c.name)
                continue
            size = codec.datatype_size(c.datatype)
            for k in range(pm.count):
                self._cells[c.address + k * size] = (pm, k, c, size)
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return self.bus is not None

    # ---- CCPClient uyumlu yüzey -----------------------------------------------------------
    def start_listening(self):
        pass

    def stop_listening(self):
        pass

    def connect(self):
        pass

    def disconnect(self, permanent: bool = False):
        pass

    def test_connection(self) -> bool:
        return self.bus.link_state()[0] == "ok"

    @contextlib.contextmanager
    def urgent(self):
        yield

    def mapped_names(self) -> list:
        return sorted({v[2].name for v in self._cells.values()})

    def _cell(self, address: int):
        ent = self._cells.get(address)
        if ent is None:
            raise SimParamError("Bu adres için Simulink eşlemesi yok (manifestte tanımlı değil).",
                                ccp.RC_OUT_OF_RANGE)
        return ent

    def _request(self, op: int, pm, k: int, value: float = 0.0):
        try:
            return self.bus.param_request(op, pm.index + k, value, timeout=self.timeout, retries=self.retries)
        except TimeoutError as exc:
            raise ccp.CCPTimeoutError(str(exc)) from exc

    def read_memory(self, address: int, length: int, address_extension: int = 0) -> bytes:
        out = b""
        addr = address
        end = address + length
        while addr < end:
            pm, k, c, size = self._cell(addr)
            op, status, val = self._request(proto.OP_READ, pm, k)
            if op == proto.OP_NAK:
                raise SimParamError(f"{pm.simulink}: model okumayı reddetti (durum {status})")
            phys = pm.from_model(val)
            raw = codec.physical_to_raw(c.compu_method, phys)
            out += codec.encode_value(c.datatype, raw, c.byte_order)
            addr += size
        if addr != end:
            raise SimParamError("Okuma hücre sınırına hizalı değil", ccp.RC_OUT_OF_RANGE)
        return out

    def write_memory(self, address: int, data: bytes, address_extension: int = 0, verify: bool = False):
        pos, addr, end = 0, address, address + len(data)
        todo = []
        while addr < end:
            pm, k, c, size = self._cell(addr)
            if not pm.writable:
                raise SimParamError(f"{pm.a2l}: manifestte salt-okunur (access=ro)")
            if self._model_state() == proto.MS_RUNNING and not pm.tunable_running:
                raise SimParamError(f"{pm.simulink}: model ÇALIŞIRKEN yazılamaz (tunable değil). Modeli durdurun, "
                                    "yazın, yeniden başlatın.", ccp.RC_ACCESS_DENIED)
            chunk = data[pos:pos + size]
            if len(chunk) != size:
                raise SimParamError("Yazma hücre sınırına hizalı değil", ccp.RC_OUT_OF_RANGE)
            raw = codec.decode_value(c.datatype, chunk, c.byte_order)
            phys = codec.raw_to_physical(c.compu_method, raw)
            val = pm.to_model(float(phys))
            try:
                pm.check_model_value(val)
            except ValueError as exc:
                raise SimParamError(f"{pm.simulink}: {exc}", ccp.RC_OUT_OF_RANGE) from exc
            todo.append((pm, k, val))
            pos += size
            addr += size
        for pm, k, val in todo:
            op, status, applied = self._request(proto.OP_WRITE, pm, k, val)
            if op == proto.OP_NAK:
                why = {proto.ST_NOT_TUNABLE_RUNNING: "model çalışırken yazılamaz; modeli durdurun",
                       proto.ST_UNKNOWN_INDEX: "model bu indeksi tanımıyor",
                       proto.ST_OUT_OF_RANGE: "değer modelde aralık dışı"}.get(status, f"durum {status}")
                raise SimParamError(f"{pm.simulink}: model yazmayı reddetti — {why}")
            if verify and abs(applied - val) > 1e-9 * max(1.0, abs(val)):
                raise SimParamError(f"{pm.simulink}: modelde uygulanan değer {applied:g}, gönderilen {val:g} "
                                    "(doğrulama başarısız)", ccp.RC_OUT_OF_RANGE)

    def write_flash_memory(self, *_a, **_kw):
        raise SimParamError("MIL'de kalıcı (flaş) yazma yoktur; yalnızca model parametresi (RAM benzeri) yazılır.")
