"""Test oturumu boyunca izlenen parametrelerin (A2L/CCP, DBC, gösterge, giriş) değerlerini
sürekli bir CSV dosyasına yazan modül.

Amaç: oturum bittikten (hatta program kapandıktan/çöktükten) sonra değerleri inceleyebilmek.
Bellekteki grafik geçmişi sınırlıdır ve program kapanınca kaybolur; bu kayıt diske yazılır.

KAYIT İLKESİ (veri kaybetmemek için): her değer KENDİ GELİŞ ZAMANINDA ve kendi periyoduyla yazılır; arayüz
zamanlayıcısına (100-500 ms) bağlı örnekleme YOKTUR.
  * CAN (DBC): mesajın HER gelişinde, o mesajdaki TÜM sinyaller, karenin geliş zamanıyla. 10 ms'de bir gelen mesaj
    10 ms'de bir, 100 sn'de bir gelen 100 sn'de bir yazılır (``FrameRecorder``; ayrı iş parçacığı).
  * CCP (A2L): arka plan CCP iş parçacığının her okumasında değer DEĞİŞMİŞSE, okuma zamanıyla (``record_change``).
    ECU'daki bir değişken 10 sn'de bir güncelleniyorsa 10 sn'de bir satır oluşur; değişmeyen değer tekrar tekrar
    yazılmaz (Excel'in "Geniş tablo" sayfası son değeri korur).
  * Kullanıcı girişleri (input:): girildikleri anda.

Biçim ("uzun" CSV; Çalışma Alanı > "CSV aç" ile geri yüklenip grafikte çizilebilir):
    time,signal,value,unix_time
    time      : oturum başlangıcından itibaren saniye
    signal    : sinyal kimliği (a2l:<ölçüm>, dbc:<MESAJ>.<SİNYAL>, gauge:<anahtar>, input:<anahtar>)
    value     : fiziksel değer
    unix_time : mutlak zaman (epoch saniye)
Dosya yolu: <veri klasörü>/oturum_kayitlari/<oturum_adı>_<tarih_saat>.csv
"""
from __future__ import annotations

import csv
import datetime
import logging
import queue
import re
import threading
import time
from pathlib import Path

HEADER = ["time", "signal", "value", "unix_time"]
FLUSH_EVERY_S = 1.0          # çökmede en çok bu kadar saniyelik veri kaybolur


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", (name or "").strip(), flags=re.UNICODE).strip("_")
    return name[:40] or "oturum"


class SessionRecorder:
    def __init__(self):
        self._lock = threading.Lock()
        self._file = None
        self._writer = None
        self._t0 = 0.0
        self._last_flush = 0.0
        self._last: dict[str, tuple[float, float]] = {}
        self.path: str | None = None
        self.rows = 0
        self.error: str | None = None      # yazma hatası olduysa mesaj (kayıt durdurulur)

    @property
    def is_active(self) -> bool:
        return self._file is not None

    def start(self, directory: str, session_name: str = "") -> str:
        self.stop()
        directory = (directory or "").strip()
        if not directory:
            raise OSError("Kayıt klasörü boş.")
        Path(directory).mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{_safe_name(session_name)}_{stamp}"
        path = Path(directory) / f"{base}.csv"
        n = 1
        while path.exists():                 # aynı saniyede başlatılsa da üzerine yazma
            path = Path(directory) / f"{base}_{n}.csv"
            n += 1
        with self._lock:
            self._file = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(HEADER)
            self._file.flush()
            self._t0 = time.time()
            self._last_flush = self._t0
            self._last = {}
            self.rows = 0
            self.error = None
            self.path = str(path)
        return self.path

    def record_change(self, sid: str, value, t_unix: float | None = None) -> bool:
        """Değer son yazılandan FARKLIYSA (ya da ilkse) yazar. Sorgulanarak (poll) okunan değerler için: ECU'daki
        değişkenin gerçek güncellenme anları kaydolur, aynı değer tekrar tekrar yazılmaz. Yazıldıysa True."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if v != v:
            return False
        prev = self._last.get(sid)
        if prev is not None and prev[1] == v:
            return False
        self.record(sid, v, t_unix)
        return True

    def record(self, sid: str, value, t_unix: float | None = None):
        """Bir örnek yazar (her çağrı bir satır). Kayıt açık değilse ya da değer sayısal değilse sessizce yok sayılır."""
        if self._writer is None:
            return
        try:
            v = float(value)
        except (TypeError, ValueError):
            return
        if v != v:                           # NaN
            return
        now = time.time() if t_unix is None else t_unix
        with self._lock:
            if self._writer is None:
                return
            self._last[sid] = (now, v)
            try:
                self._writer.writerow([f"{now - self._t0:.4f}", sid, f"{v:.9g}", f"{now:.3f}"])
                self.rows += 1
                if now - self._last_flush >= FLUSH_EVERY_S:
                    self._file.flush()
                    self._last_flush = now
            except OSError as exc:           # disk dolu / sürücü çıkarıldı
                self.error = str(exc)
                self._close_locked()

    def stop(self):
        with self._lock:
            self._close_locked()

    def _close_locked(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError as exc:
                self.error = self.error or str(exc)
        self._file = None
        self._writer = None


log = logging.getLogger(__name__)
FRAME_QUEUE_MAX = 200_000


class FrameRecorder:
    """CAN karelerini (DBC'deki TÜM mesajlar) geliş zamanlarıyla oturum kaydına yazar.

    ``submit(msg)`` CAN alım iş parçacığından çağrılır ve BLOKLAMAZ (kuyruğa koyar); çözümleme ve yazma ayrı bir iş
    parçacığındadır, böylece arayüz takılsa da kare kaybolmaz. Kuyruk dolarsa düşen kare sayısı ``dropped``'da tutulur
    (sessiz kayıp olmasın). ``dbc_provider()``: yüklü DbcDatabase'i (ya da None) döner; DBC sonradan yüklense de çalışır."""

    def __init__(self, recorder: "SessionRecorder", dbc_provider):
        self._rec = recorder
        self._dbc_provider = dbc_provider
        self._q: "queue.Queue" = queue.Queue(maxsize=FRAME_QUEUE_MAX)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.dropped = 0
        self.frames = 0
        self._cache: dict = {}                    # (dbc nesnesi, frame_id) -> message | None

    def start(self):
        self.stop()
        self._stop.clear()
        self.dropped = self.frames = 0
        self._cache = {}
        self._thread = threading.Thread(target=self._run, name="frame-recorder", daemon=True)
        self._thread.start()

    def stop(self):
        th = self._thread
        if th is not None:
            self._stop.set()
            th.join(timeout=5.0)                  # kuyruktaki kareler yazılsın
        self._thread = None

    def submit(self, msg):
        try:
            self._q.put_nowait(msg)
        except queue.Full:
            self.dropped += 1

    def _message_for(self, dbc, frame_id: int):
        key = (id(getattr(dbc, "_db", None)), frame_id)
        if key not in self._cache:
            self._cache[key] = dbc.get_message_by_frame_id(frame_id)
        return self._cache[key]

    def _handle(self, msg):
        dbc = self._dbc_provider()
        if dbc is None or not getattr(dbc, "is_loaded", False):
            return
        m = self._message_for(dbc, msg.arbitration_id)
        if m is None:
            return
        try:
            decoded = m.decode(bytes(msg.data), decode_choices=False)
        except Exception:  # noqa: BLE001 - bozuk/kısa kare: yok say
            return
        t = getattr(msg, "timestamp", None) or time.time()
        for name, value in decoded.items():
            if isinstance(value, (int, float)):
                self._rec.record(f"dbc:{m.name}.{name}", value, t)
        self.frames += 1

    def _run(self):
        while True:
            try:
                msg = self._q.get(timeout=0.1)
            except queue.Empty:
                if self._stop.is_set():
                    return
                continue
            try:
                self._handle(msg)
            except Exception:  # noqa: BLE001
                log.exception("CAN kaydı kare işlenemedi")
