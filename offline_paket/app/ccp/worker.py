"""CCP oturumu: arka plan iş parçacığı + ECU sağlık durum makinesi.

NEDEN: Eskiden tüm CCP okumaları arayüz iş parçacığında eşzamanlı yapılıyordu. ECU kapalıyken her
okuma 1,5 sn bekliyor, onlarca okuma üst üste binince program donuyordu; ECU güç döngüsünden
sonra CCP oturumu da yeniden kurulmuyordu.

NASIL:
  * Gerçek CAN/CCP giriş-çıkışı YALNIZCA bu modüldeki tek iş parçacığında yapılır.
  * Arayüz zamanlayıcıları (Ana Sayfa, Parametre Listesi, Grafik, Çalışma Alanı...) ``reader``
    üzerinden ÖNBELLEKTEN okur; hiçbir zaman beklemez. Okunmak istenen adresler ``reader``a ilk
    kez sorulunca iş parçacığının okuma listesine girer (3 sn istenmeyen adres düşer).
  * Durum makinesi:  BAĞLI DEĞİL(idle) → BAĞLANIYOR(connecting) → ÇEVRİMİÇİ(online)
                     → ECU YOK(lost) → (her 1 sn CONNECT denemesi) → ÇEVRİMİÇİ
    ECU art arda cevap vermezse ``lost``a geçilir, okuma durur (devre kesici); ECU geri gelince
    (güç döngüsü sonrası dahil) CCP oturumu KENDİLİĞİNDEN yeniden CONNECT edilir.
  * Otomatik bağlanma: sabit gecikme + tek deneme yerine geri çekilmeli (0,5→1→2→5 sn) sonsuz deneme.
  * ``GuardedClient``: arayüzden yapılan açık işlemler (yazma, harita, tanılama) için aynı CCPClient
    API'si; ECU yokken anında hata verir (bekletmez).
"""
import logging
import queue
import threading
import time

from app.ccp import protocol as ccp
from app.ccp.client import CCPClient

log = logging.getLogger(__name__)

IDLE, CONNECTING, ONLINE, LOST = "idle", "connecting", "online", "lost"

SHORT_TIMEOUT_S = 0.3        # tek CCP komutu için bekleme (ECU sağlıklıyken ms mertebesinde cevap verir)
SHORT_RETRIES = 1
FAIL_LIMIT = 2               # art arda bu kadar başarısız tur/komut → ECU YOK
WANT_TTL_S = 3.0             # bu süredir istenmeyen adres okuma listesinden düşer
LOST_PROBE_S = 1.0           # ECU yokken yeniden CONNECT deneme aralığı
BACKOFF = (0.5, 1.0, 2.0, 5.0)
MIN_ROUND_S = 0.03           # tur arası en az bekleme (hattı boğma)
STALE_MIN_S = 1.0


class ReadPending(ccp.CCPTimeoutError):
    """Bu adres henüz arka planda okunmadı (ilk tur)."""


class EcuSilent(ccp.CCPTimeoutError):
    """ECU cevap vermiyor / CCP oturumu yok."""


class CachedReader:
    """``read_memory(address, length, ext)`` önbellekten döner; beklemez."""

    def __init__(self, session: "CcpSession"):
        self._s = session

    def read_memory(self, address: int, length: int, address_extension: int = 0) -> bytes:
        return self._s.read_cached(address, length, address_extension)


class GuardedClient:
    """CCPClient ile aynı API; ECU 'yok' iken anında EcuSilent verir, zaman aşımını oturuma bildirir."""

    def __init__(self, session: "CcpSession"):
        self._s = session

    def __getattr__(self, name):
        client = self._s._client
        if client is None:
            # Oturum, süren bir işlemin ortasında kapatıldı (bağlantı kesildi): AttributeError yerine
            # çağıranların zaten ele aldığı "ECU yok" hatası.
            def gone(*_a, **_kw):
                raise EcuSilent("CCP bağlı değil")
            return gone
        target = getattr(client, name)
        if not callable(target):
            return target
        if name == "test_connection":
            def test():
                if self._s.state != ONLINE:
                    return False
                return target()
            return test

        def guarded(*a, **kw):
            if self._s.state != ONLINE:
                raise EcuSilent(self._s.not_ready_reason())
            try:
                return target(*a, **kw)
            except ccp.CCPTimeoutError:
                self._s.note_failure()
                raise
        return guarded

    @property
    def is_connected(self) -> bool:
        return self._s.state == ONLINE


class CcpSession:
    def __init__(self, connection):
        self._conn = connection                       # CanConnection
        self._client: CCPClient | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._events: "queue.Queue[tuple]" = queue.Queue()
        self._cache: dict = {}                        # (adres, ext, boyut) -> (bytes|None, hata|None, t)
        self._wanted: dict = {}                       # (adres, ext, boyut) -> son istenme zamanı
        self._params: tuple | None = None
        self._adopted = False                         # hazır istemci (kendi bus'ı var): test/özel kullanım
        self.state = IDLE
        self.info = ""                                # durum açıklaması ("deneme 3: ECU cevap vermedi"...)
        self.version = ""
        self.attempts = 0
        self.last_error = ""
        self._consec_fail = 0
        self.round_ms = 0.0
        self.items = 0
        self.reconnects = 0
        # Her BAŞARILI okuma için (CCP iş parçacığında) çağrılır: on_read((adres, uzantı, boyut), bayt, okuma_zamanı).
        # Oturum kaydı değişkenleri arayüz zamanlayıcısıyla değil, okumanın gerçek anında yazar.
        self.on_read = None
        self.reader = CachedReader(self)
        self.guarded = GuardedClient(self)

    # ------------------------------------------------------------------ yaşam döngüsü
    @property
    def client(self):
        """Arayüzün kullanacağı istemci: oturum varsa (çevrimiçi ya da ECU yok) GuardedClient, yoksa None."""
        return self.guarded if self.state in (ONLINE, LOST) else None

    def start(self, cro_id: int, dto_id: int, station: int):
        """Bağlanmayı (geri çekilmeli sonsuz denemeyle) arka planda başlatır; zaten çalışıyorsa
        yalnızca parametreleri günceller."""
        self._params = (cro_id, dto_id, station)
        if self._thread is not None and self._thread.is_alive():
            return
        self._adopted = False
        self._stop = threading.Event()      # HER oturum iş parçacığının KENDİ bayrağı (bkz. stop())
        self._conn.ccp_dto_id = dto_id
        self._client = CCPClient(self._conn.bus, cro_id, dto_id, station_address=station,
                                 timeout=SHORT_TIMEOUT_S, retries=SHORT_RETRIES,
                                 dto_queue=self._conn.ccp_queue)
        self._set_state(CONNECTING, "başlatılıyor")
        self._thread = threading.Thread(target=self._run, args=(self._stop, self._client),
                                        name="ccp-session", daemon=True)
        self._thread.start()

    def adopt(self, client: CCPClient):
        """Hazır (bağlı) bir CCPClient'ı çevrimiçi oturum olarak benimser (test/özel kullanım)."""
        self.stop(graceful=False)
        self._adopted = True
        self._client = client
        client.timeout, client.retries = SHORT_TIMEOUT_S, SHORT_RETRIES
        self._params = (client.cro_id, client.dto_id, client.station_address)
        self._stop = threading.Event()
        self._consec_fail = 0
        self._set_state(ONLINE, "")
        self._thread = threading.Thread(target=self._run, args=(self._stop, self._client),
                                        name="ccp-session", daemon=True)
        self._thread.start()

    def stop(self, graceful: bool = True):
        """İş parçacığını durdurur; graceful ve çevrimiçiyse ECU'ya DISCONNECT gönderir.

        Her iş parçacığı kendi ``Event``'ini taşır: ``join`` zaman aşımına uğrasa (takılmış adaptör) bile
        o iş parçacığının bayrağı bir daha SIFIRLANMAZ; sonradan ``start()`` ile açılan yeni oturum eskisini
        "diriltemez" (iki iş parçacığı aynı hatta komut göndermesin)."""
        self._stop.set()
        th = self._thread
        if th is not None and th is not threading.current_thread():
            th.join(timeout=2.0)
            if th.is_alive():
                log.warning("CCP oturum iş parçacığı 2 sn içinde durmadı; bayrağı set kalır, kendiliğinden çıkacak")
        self._thread = None
        client = self._client
        if graceful and client is not None and self.state == ONLINE:
            try:
                client.disconnect()
            except Exception:
                log.debug("CCP DISCONNECT gönderilemedi (ECU yok olabilir)", exc_info=True)
        self._client = None
        self._conn.ccp_dto_id = None
        with self._lock:
            self._cache.clear()
            self._wanted.clear()
        if self.state != IDLE:
            self._set_state(IDLE, "")

    def refresh_bus(self):
        """CAN adaptörü yeniden açılınca istemci yeni bus'ı kullansın."""
        if self._client is not None and not self._adopted:
            self._client.bus = self._conn.bus

    # ------------------------------------------------------------------ arayüz tarafı
    def poll_events(self) -> list:
        out = []
        while True:
            try:
                out.append(self._events.get_nowait())
            except queue.Empty:
                return out

    def not_ready_reason(self) -> str:
        if self.state == LOST:
            return "ECU cevap vermiyor (CCP yeniden bağlanmayı deniyor)"
        if self.state == CONNECTING:
            return f"CCP bağlanıyor… {self.info}".strip()
        return "CCP bağlı değil"

    def read_cached(self, address: int, length: int, ext: int = 0) -> bytes:
        key = (address, ext or 0, length)
        now = time.monotonic()
        with self._lock:
            self._wanted[key] = now
            entry = self._cache.get(key)
        if self.state == LOST:
            raise EcuSilent("ECU cevap vermiyor")
        if self.state != ONLINE:
            raise EcuSilent(self.not_ready_reason())
        if entry is None:
            raise ReadPending("ilk okuma bekleniyor")
        data, err, t = entry
        if err is not None:
            raise err
        if now - t > max(STALE_MIN_S, 4 * self.round_ms / 1000.0):
            raise ReadPending("veri bayat (okuma turu yetişemiyor)")
        return data

    def note_failure(self):
        """Arayüzden yapılan açık bir işlem zaman aşımına uğradı: ECU yoksa devre kesiciyi çalıştır."""
        self._consec_fail += 1
        if self._consec_fail >= FAIL_LIMIT and self.state == ONLINE:
            self._to_lost("açık işlem zaman aşımı")

    def status_text(self) -> str:
        names = {IDLE: "CCP bağlı değil", CONNECTING: "CCP bağlanıyor", ONLINE: "CCP çevrimiçi",
                 LOST: "ECU YOK — CCP yeniden bağlanıyor"}
        extra = f" · {self.info}" if self.info and self.state in (CONNECTING, LOST) else ""
        if self.state == ONLINE and self.items:
            extra = f" · {self.items} değişken · {self.round_ms:.0f} ms/tur"
        return names[self.state] + extra

    # ------------------------------------------------------------------ iç
    def _emit(self, *event):
        self._events.put(event)

    def _set_state(self, state: str, info: str = ""):
        changed = state != self.state or info != self.info
        self.state, self.info = state, info
        if changed:
            self._emit("state", state, info)

    def _to_lost(self, why: str):
        self._set_state(LOST, why)
        self._emit("log", "HATA", f"ECU cevap vermiyor ({why}); CCP oturumu ECU gelince otomatik yeniden kurulacak")
        with self._lock:
            self._cache.clear()

    def _bus_ready(self) -> bool:
        has_bus = self._adopted or self._conn.bus is not None
        return has_bus and not self._conn.recovering

    def _try_connect(self, c: CCPClient) -> tuple:
        """(başarılı mı, hata metni). CONNECT + sürüm sorgusu; kısa zaman aşımlarıyla."""
        if not self._adopted:
            c.bus = self._conn.bus
        try:
            c.connect()
            major, minor = c.get_ccp_version()
            self.version = f"v{major}.{minor}"
            return True, ""
        except ccp.CCPTimeoutError:
            return False, "ECU cevap vermedi"
        except ccp.CCPError as exc:
            return False, str(exc)
        except Exception as exc:        # bus yazma hatası (adaptör toparlanıyor olabilir)
            return False, f"bus: {exc}"

    def _run(self, stop: threading.Event, client: CCPClient):
        """``stop``/``client``: bu iş parçacığının KENDİ bayrağı ve istemcisi (oturum yeniden başlatılsa
        da eski iş parçacığı yenisinin nesnelerine dokunmaz)."""
        backoff_i = 0
        while not stop.is_set():
            try:
                if self.state == ONLINE:
                    self._poll_round(stop, client)
                elif self.state == LOST:
                    self._recover_step(stop, client)
                else:
                    backoff_i = self._connect_step(stop, client, backoff_i)
            except Exception as exc:    # iş parçacığı hiçbir koşulda ölmesin
                if stop.is_set():
                    break
                self.last_error = f"iç hata: {exc}"
                self._emit("log", "HATA", f"CCP oturum iş parçacığı: {exc}")
                stop.wait(0.5)

    def _connect_step(self, stop: threading.Event, client: CCPClient, backoff_i: int) -> int:
        if not self._bus_ready():
            self._set_state(CONNECTING, "hat hazır değil")
            stop.wait(0.2)
            return backoff_i
        self.attempts += 1
        ok, err = self._try_connect(client)
        if stop.is_set():                 # bekleme sırasında durduruldu: durumu/ECU'yu değiştirme
            return backoff_i
        if ok:
            self._consec_fail = 0
            self.attempts = 0
            self.last_error = ""
            self._set_state(ONLINE, "")
            self._emit("log", "CCP", f"CCP bağlandı ({self.version})")
            return 0
        self.last_error = err
        self._set_state(CONNECTING, f"deneme {self.attempts}: {err}")
        if self.attempts in (1, 5, 20):
            self._emit("log", "HATA", f"CCP bağlantı denemesi {self.attempts}: {err}")
        stop.wait(BACKOFF[min(backoff_i, len(BACKOFF) - 1)])
        return backoff_i + 1

    def _recover_step(self, stop: threading.Event, client: CCPClient):
        stop.wait(LOST_PROBE_S)
        if stop.is_set() or not self._bus_ready():
            return
        ok, err = self._try_connect(client)
        if stop.is_set():
            return
        if ok:
            self._consec_fail = 0
            self.reconnects += 1
            self._set_state(ONLINE, "")
            self._emit("log", "CCP", f"ECU geri geldi, CCP oturumu yeniden kuruldu ({self.version})")
        else:
            self.last_error = err
            self._set_state(LOST, err)

    # CCP dönüş kodları: oturumun GEÇERSİZ olduğunu gösterenler (ECU açılışta oturumu unutur).
    _SESSION_INVALID_RC = (ccp.RC_ACCESS_DENIED, ccp.RC_CMD_UNKNOWN)

    def _poll_round(self, stop: threading.Event, client: CCPClient):
        if not self._bus_ready():
            stop.wait(0.2)
            return
        now = time.monotonic()
        with self._lock:
            for k in [k for k, t in self._wanted.items() if now - t > WANT_TTL_S]:
                del self._wanted[k]
            wanted = list(self._wanted)
        self.items = len(wanted)
        if not wanted:
            stop.wait(0.05)
            return
        t0 = time.monotonic()
        successes = 0
        dead = False                 # ECU/hat yok ya da oturum geçersiz (okumayı kes)
        for key in wanted:
            if stop.is_set():
                return
            address, ext, size = key
            data, err = None, None
            try:
                data = client.read_memory(address, size, ext)
                successes += 1
                cb = self.on_read
                if cb is not None:
                    try:
                        cb(key, data, time.time())
                    except Exception:  # noqa: BLE001 - kayıt hatası okuma turunu bozmasın
                        log.debug("on_read hata verdi", exc_info=True)
            except ccp.CCPTimeoutError as exc:
                err, dead = exc, True
            except ccp.CCPError as exc:
                err = exc            # tek bir adres hatası (örn. OUT_OF_RANGE) oturumu düşürmez
                if exc.return_code in self._SESSION_INVALID_RC:
                    dead = True
            except Exception as exc:
                err, dead = exc, True        # bus yazma hatası
            if stop.is_set():             # oturum kapatıldı/yeniden başlatıldı: eski sonucu önbelleğe yazma
                return
            with self._lock:
                self._cache[key] = (data, err, time.monotonic())
            if dead:
                self.last_error = str(err) or type(err).__name__
                break                         # ECU yokken kalanları bekletme
        if dead and successes == 0:
            self._consec_fail += 1
            if self._consec_fail >= FAIL_LIMIT:
                self._to_lost(self.last_error or "okuma turu başarısız")
                return
        elif successes:
            self._consec_fail = 0
        spent = (time.monotonic() - t0) * 1000.0
        self.round_ms = 0.7 * self.round_ms + 0.3 * spent if self.round_ms else spent
        stop.wait(MIN_ROUND_S)
