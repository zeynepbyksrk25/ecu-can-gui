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
import os
import queue
import re
import threading
import time
from pathlib import Path

HEADER = ["time", "signal", "value", "unix_time"]
EVENT_HEADER = ["time", "unix_time", "kind", "text"]
FLUSH_EVERY_S = 1.0          # çökmede en çok bu kadar saniyelik veri kaybolur
SIM_TIME_EVERY_S = 0.05     # MIL: simülasyon zamanı eşlemesi en fazla bu sıklıkta (wall-clock) yazılır
RECORD_QUEUE_MAX = 500_000   # yazma iş parçacığının kuyruğu (taşarsa düşen sayılır; sessiz kayıp yok)
META_VERSION = 1

_SAMPLE, _EVENT, _FRAME, _STOP = "s", "e", "f", "x"


def file_fingerprint(path: str | None) -> dict:
    """Üst veri için dosya "sürümü": ad, boyut, değişiklik zamanı ve SHA-256 (ilk 16 hane). Dosya yoksa boş."""
    if not path:
        return {}
    try:
        import hashlib
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        st = os.stat(path)
        return {"file": os.path.basename(path), "path": os.path.abspath(path), "size": st.st_size,
                "mtime": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec="seconds"),
                "sha256": h.hexdigest()[:16]}
    except OSError:
        return {"file": os.path.basename(path), "path": path, "error": "okunamadı"}


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", (name or "").strip(), flags=re.UNICODE).strip("_")
    return name[:40] or "oturum"


class SessionRecorder:
    """Oturum kaydı: HER kaynaktan (CAN çözülmüş sinyaller, A2L/CCP, girişler, MIL, olaylar, ham CAN kareleri) gelen
    veri, çağıranı BLOKLAMADAN sınırlı bir kuyruğa konur; ayrı bir yazma iş parçacığı diske yazar (arayüz iş parçacığı
    disk gecikmesinden etkilenmez).

    Dosyalar (aynı ``<ad>_<tarih>`` kökü):
      * ``.csv``        – uzun biçim: time,signal,value,unix_time (bkz. modül başı)
      * ``.events.csv`` – olaylar/işaretler: time,unix_time,kind,text (bağlantı kopması, hata, marker, test başı/sonu…)
      * ``.asc``        – ham CAN kareleri (Vector ASCII; ilk kare gelince oluşur)
      * ``.meta.json``  – oturum üst verisi (kullanıcı, DBC/A2L, kaynak/birim tablosu, istatistik); durum
                          ``recording`` iken program çökerse sonradan ``recovered`` olarak işaretlenir.

    Veri kaybı denetimi: kuyruk dolarsa ``dropped`` artar; yazma hatası ``error``'a yazılır ve kayıt durur (görünür).
    ``stop()`` kuyruğu boşaltır, dosyaları kapatır, üst veriyi yazar."""

    def __init__(self, queue_max: int = RECORD_QUEUE_MAX):
        self._lock = threading.Lock()
        self._queue_max = queue_max
        self._q: "queue.Queue" = queue.Queue(maxsize=queue_max)
        self._thread: threading.Thread | None = None
        self._file = None
        self._writer = None
        self._events_file = None
        self._events_writer = None
        self._asc = None
        self._asc_path: str | None = None
        self._base: str | None = None
        self._t0 = 0.0
        self._started_mono = 0.0
        self._ended_mono = 0.0
        self._last_sim_rec = 0.0
        self._paused = False
        self._paused_total = 0.0
        self._paused_at: float | None = None
        self._last: dict[str, tuple[float, float]] = {}
        self._signals: dict[str, dict] = {}       # sid -> {unit, source, timebase}
        self.meta: dict = {}
        self.path: str | None = None
        self.events_path: str | None = None
        self.meta_path: str | None = None
        self.rows = 0
        self.frames = 0                            # diske yazılan ham CAN karesi
        self.event_rows = 0
        self.dropped = 0                           # kuyruk dolduğu için YAZILAMAYAN öğe sayısı
        self.paused_skipped = 0                    # duraklatıldığı için alınmayan örnek sayısı
        self.error: str | None = None              # yazma hatası (kayıt durdurulur)

    # ---- durum ---------------------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._file is not None

    @property
    def is_paused(self) -> bool:
        return self._paused and self.is_active

    @property
    def state(self) -> str:
        if self.error:
            return "HATA"
        if not self.is_active:
            return "DURDU"
        return "DURAKLATILDI" if self._paused else "KAYITTA"

    def elapsed_s(self) -> float:
        """Kayıt süresi (duraklatılan süre hariç)."""
        if not self._started_mono:
            return 0.0
        end = time.monotonic() if self.is_active or not self._ended_mono else self._ended_mono
        paused = self._paused_total + (end - self._paused_at if self._paused_at is not None else 0.0)
        return max(0.0, end - self._started_mono - paused)

    def file_bytes(self) -> int:
        total = 0
        for p in (self.path, self.events_path, self._asc_path):
            if p:
                try:
                    total += os.path.getsize(p)
                except OSError:
                    pass
        return total

    def stats(self) -> dict:
        return {"state": self.state, "elapsed_s": self.elapsed_s(), "rows": self.rows, "frames": self.frames,
                "events": self.event_rows, "bytes": self.file_bytes(), "dropped": self.dropped,
                "queue": self._q.qsize(), "error": self.error, "path": self.path}

    # ---- yaşam döngüsü ---------------------------------------------------------------------
    def start(self, directory: str, session_name: str = "", meta: dict | None = None) -> str:
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
            base = f"{_safe_name(session_name)}_{stamp}_{n}"
            path = Path(directory) / f"{base}.csv"
            n += 1
        root = str(Path(directory) / base)
        with self._lock:
            self._q = queue.Queue(maxsize=self._queue_max)
            self._file = open(path, "w", newline="", encoding="utf-8")
            self._writer = csv.writer(self._file)
            self._writer.writerow(HEADER)
            self._file.flush()
            self.events_path = root + ".events.csv"
            self._events_file = open(self.events_path, "w", newline="", encoding="utf-8")
            self._events_writer = csv.writer(self._events_file)
            self._events_writer.writerow(EVENT_HEADER)
            self._events_file.flush()
            self._asc = None
            self._asc_path = root + ".asc"
            self._base = root
            self._t0 = time.time()
            self._started_mono = time.monotonic()
            self._ended_mono = 0.0
            self._paused, self._paused_total, self._paused_at = False, 0.0, None
            self._last = {}
            self._signals = {}
            self.rows = self.frames = self.event_rows = self.dropped = self.paused_skipped = 0
            self.error = None
            self.path = str(path)
            self.meta_path = root + ".meta.json"
            self.meta = {"version": META_VERSION, "name": session_name, "status": "recording",
                         "start_unix": self._t0,
                         "start_text": datetime.datetime.fromtimestamp(self._t0).isoformat(timespec="seconds"),
                         "files": {"csv": os.path.basename(self.path),
                                   "events": os.path.basename(self.events_path),
                                   "asc": os.path.basename(self._asc_path)}}
            if meta:
                self.meta.update(meta)
            self._thread = threading.Thread(target=self._run, name="session-recorder", daemon=True)
            self._thread.start()
        self._write_meta()
        self.record_event("BASLANGIC", f"Kayıt başladı: {session_name or '(adsız)'}", self._t0)
        return self.path

    def pause(self):
        """Duraklat: yeni örnekler alınmaz (kaynaklar çalışmaya devam eder); olay olarak işaretlenir."""
        if self.is_active and not self._paused:
            self.record_event("DURAKLATMA", "Kayıt duraklatıldı")
            self._paused = True
            self._paused_at = time.monotonic()

    def resume(self):
        if self.is_active and self._paused:
            self._paused = False
            if self._paused_at is not None:
                self._paused_total += time.monotonic() - self._paused_at
            self._paused_at = None
            self.record_event("DEVAM", "Kayıt sürdürüldü")

    def stop(self):
        th = self._thread
        if th is None and self._file is None:
            return
        if th is not None:
            try:
                self._q.put(( _STOP,), timeout=5.0)        # kuyruğun SONUNA: önceki her öğe yazılsın
            except queue.Full:
                pass
            th.join(timeout=30.0)
        self._ended_mono = time.monotonic()
        with self._lock:
            self._close_locked()
        self._thread = None
        self._finish_meta()

    def _close_locked(self):
        for attr in ("_file", "_events_file"):
            f = getattr(self, attr)
            if f is not None:
                try:
                    f.close()
                except OSError as exc:
                    self.error = self.error or str(exc)
            setattr(self, attr, None)
        self._writer = None
        self._events_writer = None
        if self._asc is not None:
            try:
                self._asc.stop()
            except Exception as exc:  # noqa: BLE001 - python-can yazıcısı: kapanış hatası kaydı bozmaz
                self.error = self.error or str(exc)
            self._asc = None

    # ---- üst veri ------------------------------------------------------------------------
    def register_signal(self, sid: str, unit: str = "", source: str = "", timebase: str = ""):
        """Sinyalin birimi/kaynağı/zaman tabanı (üst veriye yazılır; MDF4 dışa aktarımında kullanılır)."""
        self._signals[sid] = {"unit": unit or "", "source": source or "", "timebase": timebase or ""}

    def update_meta(self, **kw):
        self.meta.update(kw)
        if self.is_active:
            self._write_meta()

    def _write_meta(self):
        if not self.meta_path:
            return
        from app.persist import atomic_write_json
        data = dict(self.meta)
        data["signals"] = dict(self._signals)
        atomic_write_json(self.meta_path, data)

    def _finish_meta(self):
        if not self.meta_path:
            return
        self.meta.update({
            "status": "error" if self.error else "complete",
            "end_unix": time.time(), "duration_s": round(self.elapsed_s(), 3),
            "rows": self.rows, "frames": self.frames, "events": self.event_rows, "dropped": self.dropped,
            "paused_skipped": self.paused_skipped, "error": self.error,
        })
        self._write_meta()

    # ---- veri girişi (hızlı, bloklamaz) -------------------------------------------------------
    def _put(self, item) -> bool:
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def record_change(self, sid: str, value, t_unix: float | None = None) -> bool:
        """Değer son yazılandan FARKLIYSA (ya da ilkse) yazar. Sorgulanarak (poll) okunan değerler için: ECU'daki
        değişkenin gerçek güncellenme anları kaydolur, aynı değer tekrar tekrar yazılmaz. Yazıldıysa True."""
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if v != v or v in (float("inf"), float("-inf")):
            return False
        prev = self._last.get(sid)
        if prev is not None and prev[1] == v:
            return False
        return self.record(sid, v, t_unix)

    def record(self, sid: str, value, t_unix: float | None = None) -> bool:
        """Bir örnek (her çağrı bir satır). Kayıt kapalıysa / değer sayısal-sonlu değilse yok sayılır."""
        if self._writer is None:
            return False
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if v != v or v in (float("inf"), float("-inf")):   # NaN / ±Inf dosyaya taşınmaz
            return False
        if self._paused:
            self.paused_skipped += 1
            return False
        now = time.time() if t_unix is None else t_unix
        self._last[sid] = (now, v)
        return self._put((_SAMPLE, sid, v, now))

    def record_event(self, kind: str, text: str, t_unix: float | None = None) -> bool:
        """Olay/işaret: BAGLANTI_KOPTU, HATA, MARKER, KALIBRASYON, MODEL… Duraklatılmışken de yazılır."""
        if self._events_writer is None:
            return False
        return self._put((_EVENT, str(kind), str(text), time.time() if t_unix is None else t_unix))

    def add_marker(self, label: str, t_unix: float | None = None) -> bool:
        """Elle işaret (Motor start, Ignition ON, Shutdown…); olay dosyasında ve ASC'de yer alır."""
        return self.record_event("MARKER", label, t_unix)

    def record_frame(self, msg, rx: bool = True) -> bool:
        """Ham CAN karesi (``can.Message``) → ``.asc``; kare kendi geliş zamanıyla yazılır."""
        if self._writer is None or self._paused:
            if self._paused:
                self.paused_skipped += 1
            return False
        sim_t = getattr(msg, "sim_time", None)          # MIL: simülasyon zamanı AYRI sinyal (wall-clock ile karışmaz)
        if sim_t is not None and rx:
            now = getattr(msg, "timestamp", None) or time.time()
            if now - self._last_sim_rec >= SIM_TIME_EVERY_S:
                self._last_sim_rec = now
                self.register_signal("mil:sim_time", "s", "Simulink MIL", "simulation_time")
                self.record("mil:sim_time", sim_t, now)
        return self._put((_FRAME, msg, bool(rx)))

    # ---- yazma iş parçacığı --------------------------------------------------------------------
    def _run(self):
        last_flush = time.monotonic()
        while True:
            try:
                item = self._q.get(timeout=0.1)
            except queue.Empty:
                item = None
            if item is not None:
                if item[0] == _STOP:
                    self._flush()
                    return
                try:
                    self._write(item)
                except OSError as exc:               # disk dolu / sürücü çıkarıldı: görünür, kayıt durur
                    self.error = str(exc)
                    self._fail()
                    return
                except Exception as exc:  # noqa: BLE001 - tek bozuk öğe kaydı durdurmasın
                    log.exception("Kayıt öğesi yazılamadı: %s", exc)
            if time.monotonic() - last_flush >= FLUSH_EVERY_S:
                try:
                    self._flush()
                except OSError as exc:
                    self.error = str(exc)
                    self._fail()
                    return
                last_flush = time.monotonic()

    def _write(self, item):
        kind = item[0]
        if kind == _SAMPLE:
            _k, sid, v, now = item
            self._writer.writerow([f"{now - self._t0:.4f}", sid, f"{v:.9g}", f"{now:.3f}"])
            self.rows += 1
        elif kind == _EVENT:
            _k, ev, text, now = item
            self._events_writer.writerow([f"{now - self._t0:.4f}", f"{now:.3f}", ev, text])
            self.event_rows += 1
            if self._asc is not None:
                self._asc.log_event(f"{ev}: {text}", now)
        elif kind == _FRAME:
            _k, msg, rx = item
            if self._asc is None:
                import can
                self._asc = can.ASCWriter(self._asc_path)
            try:
                msg.is_rx = rx
            except AttributeError:
                pass
            self._asc.on_message_received(msg)
            self.frames += 1

    def _flush(self):
        if self._file is not None:
            self._file.flush()
        if self._events_file is not None:
            self._events_file.flush()
        if self._asc is not None:
            self._asc.file.flush()

    def _fail(self):
        """Yazma hatası: dosyalar kapatılır, kayıt durur; ``error`` görünür kalır. Kuyruk boşaltılıp düşenler sayılır."""
        with self._lock:
            self._close_locked()
        while True:
            try:
                self._q.get_nowait()
                self.dropped += 1
            except queue.Empty:
                break


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
        self._rec.record_frame(msg, rx=True)       # ham kare (ASC): çözümlemeden bağımsız, DBC yüklü olmasa da
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
