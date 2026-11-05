"""CCP okumalarını UI thread'inden ayıran tek-thread'li okuma havuzu.

Neden: CCP istek/cevap çağrıları bloklayıcıdır (timeout 0.5 s x deneme).
UI thread'inde yapıldıklarında ECU susunca arayüz donuyor ve aynı thread'deki
QTimer tabanlı periyodik CAN gönderimi (ECU'ya giden giriş çerçeveleri) de
duruyordu. Burada okumalar bir worker thread'inde yapılır; sonuçlar kuyruklu
Qt sinyaliyle UI thread'inde uygulanır.

Kurallar:
  * Worker yalnızca HAM BAYT okur. COMPU_METHOD dönüşümü (pya2l/SQLite
    nesneleri thread'e bağlı olabilir) UI thread'inde yapılır.
  * Aynı anahtarla (key) en fazla bir iş uçuşta olur; yeni tick atlanır,
    böylece yavaş ECU'da iş birikmez.
  * Zaman aşımında iş durur ve kısa bir geri çekilme (backoff) süresi boyunca
    yeni okuma gönderilmez ("ECU yanıt vermiyor" durumu).
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QObject, Signal

from app.ccp import codec as ccp_codec
from app.ccp import protocol as ccp_protocol

BACKOFF_SECONDS = 2.0


def _read_job(client, items):
    """Worker thread'inde çalışır. items: [(tag, info)]. Döner:
    ([(tag, info, raw_bytes|None, exc|None)], timed_out)."""
    out = []
    timed_out = False
    for tag, info in items:
        try:
            size = ccp_codec.datatype_size(info.datatype)
            raw = client.read_memory(info.address, size, info.address_extension or 0)
            out.append((tag, info, raw, None))
        except ccp_protocol.CCPTimeoutError as exc:
            out.append((tag, info, None, exc))
            timed_out = True
            break                      # ECU yok: kalan sinyaller için de bekleme
        except Exception as exc:  # noqa: BLE001
            out.append((tag, info, None, exc))
    return out, timed_out


class CcpReadPool(QObject):
    _finished = Signal(object)         # (key, sink, error_sink, result, exc)
    unresponsive_changed = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ccp-poll")
        self._inflight: set = set()
        self._backoff_until = 0.0
        self._unresponsive = False
        self._closed = False
        self._finished.connect(self._on_finished)

    @property
    def unresponsive(self) -> bool:
        return self._unresponsive

    def reset(self):
        """Yeni bağlantı: geri çekilmeyi sıfırla."""
        self._backoff_until = 0.0
        self._set_unresponsive(False)

    def submit(self, key, client, items, sink, error_sink=None) -> bool:
        """items: [(tag, info)]. sink(tag, physical_value) UI thread'inde çağrılır;
        error_sink(tag, exception) okuma/dönüşüm hatasında. False: atlandı."""
        if self._closed or client is None or not items:
            return False
        if key in self._inflight or time.monotonic() < self._backoff_until:
            return False
        self._inflight.add(key)
        fut = self._executor.submit(_read_job, client, list(items))

        def done(f, key=key):
            try:
                self._finished.emit((key, sink, error_sink, f.result(), None))
            except Exception as exc:  # noqa: BLE001
                self._finished.emit((key, sink, error_sink, None, exc))
        fut.add_done_callback(done)
        return True

    def _set_unresponsive(self, flag: bool):
        if flag != self._unresponsive:
            self._unresponsive = flag
            self.unresponsive_changed.emit(flag)

    def _on_finished(self, payload):
        key, sink, error_sink, result, exc = payload
        self._inflight.discard(key)
        if self._closed:
            return
        if exc is not None or result is None:
            if error_sink:
                error_sink(None, exc or RuntimeError("okuma başarısız"))
            return
        rows, timed_out = result
        any_ok = False
        for tag, info, raw, err in rows:
            if err is None:
                try:
                    value = ccp_codec.raw_to_physical(
                        info.compu_method, ccp_codec.decode_value(info.datatype, raw, info.byte_order))
                except Exception as conv_exc:  # noqa: BLE001
                    err = conv_exc
                else:
                    any_ok = True
                    sink(tag, value)
                    continue
            if error_sink:
                error_sink(tag, err)
        if timed_out:
            self._backoff_until = time.monotonic() + BACKOFF_SECONDS
            self._set_unresponsive(True)
        elif any_ok:
            self._set_unresponsive(False)

    def shutdown(self):
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)
