"""DBC dosyasından mesaj/sinyal tanımlarını okuyan ve mühendislik
birimindeki değerleri (örn. 2.5 bar) doğru CAN ID + data byte'larına
kodlayan katman. Bit paketleme/factor/offset/byteorder işini cantools
kütüphanesi üstlenir; biz sadece UI ile bu kütüphane arasında köprüyüz.
"""

import cantools
from cantools.database.can.message import Message
from cantools.database.can.signal import Signal


def signal_limits(signal) -> tuple[float, float]:
    """Sinyalin fiziksel (ölçekli) alt/üst sınırı. DBC'de [min|max] yoksa ya da
    0|0 ise ham bit genişliğinden (uzunluk, işaret, çarpan, ofset) hesaplanır."""
    mn, mx = signal.minimum, signal.maximum
    if mn is not None and mx is not None and mn != mx:
        return float(mn), float(mx)
    length = max(1, int(signal.length))
    if getattr(signal, "is_float", False):
        return -3.4e38, 3.4e38
    if signal.is_signed:
        lo_raw, hi_raw = -(1 << (length - 1)), (1 << (length - 1)) - 1
    else:
        lo_raw, hi_raw = 0, (1 << length) - 1
    scale = signal.scale if signal.scale else 1.0
    a, b = lo_raw * scale + signal.offset, hi_raw * scale + signal.offset
    return (min(a, b), max(a, b))


def signal_default(signal) -> float:
    """Girilmeyen sinyalin güvenli varsayılanı: DBC başlangıç değeri (GenSigStartValue/
    initial) varsa o, yoksa 0; her durumda sinyalin geçerli aralığına kırpılır.
    (Eskiden 'minimum' kullanılıyordu: -40 °C gibi güvensiz bir değer gidebiliyordu.)"""
    lo, hi = signal_limits(signal)
    init = getattr(signal, "initial", None)
    try:
        v = float(init) if init is not None else 0.0
    except (TypeError, ValueError):
        v = 0.0
    return min(max(v, lo), hi)


class DbcDatabase:
    def __init__(self):
        self._db = None
        self.path: str | None = None

    @property
    def is_loaded(self) -> bool:
        return self._db is not None

    def load(self, path: str):
        self._db = cantools.database.load_file(path)
        self.path = path

    def message_names(self) -> list[str]:
        if not self.is_loaded:
            return []
        return sorted(m.name for m in self._db.messages)

    def get_message(self, name: str) -> Message | None:
        if not self.is_loaded:
            return None
        try:
            return self._db.get_message_by_name(name)
        except KeyError:
            return None

    def signals_of(self, name: str) -> list[Signal]:
        msg = self.get_message(name)
        return list(msg.signals) if msg is not None else []

    def get_message_by_frame_id(self, frame_id: int) -> Message | None:
        """Gelen bir CAN mesajının ID'sinden (izleme sekmesi için) DBC
        tanımını bulur. Bulunamazsa None döner (DBC'de tanımsız ID)."""
        if not self.is_loaded:
            return None
        try:
            return self._db.get_message_by_frame_id(frame_id)
        except KeyError:
            return None

    def decode_frame(self, frame_id: int, data: bytes) -> tuple[str, dict] | None:
        """(mesaj_adı, {sinyal_adı: değer}) döner; ID DBC'de tanımlı değilse
        veya decode başarısızsa None döner (izleme ekranı ham veriyi gösterir)."""
        msg = self.get_message_by_frame_id(frame_id)
        if msg is None:
            return None
        try:
            decoded = msg.decode(bytes(data))
        except (ValueError, KeyError, TypeError, cantools.database.errors.Error):
            return None
        return msg.name, decoded

    def encode(self, name: str, signal_values: dict) -> tuple[int, bytes, bool]:
        """Sinyal ismi -> mühendislik değeri sözlüğünü, doğru CAN ID,
        data byte'ları ve frame type (extended?) üçlüsüne çevirir.
        Kullanıcı mesajdaki TÜM sinyalleri girmek zorunda değildir;
        girilmeyen sinyaller mesajın tanımlı minimumuna (yoksa 0'a)
        varsayılan olarak ayarlanır."""
        msg = self.get_message(name)
        if msg is None:
            raise ValueError(f"'{name}' yüklü DBC dosyasında bulunamadı.")

        complete_values = dict(signal_values)
        known = {s.name for s in msg.signals}
        unknown = [k for k in complete_values if k not in known]
        if unknown:
            raise ValueError(f"{name}: DBC'de olmayan sinyal(ler): {', '.join(unknown)}")
        for signal in msg.signals:
            if signal.name not in complete_values:
                complete_values[signal.name] = signal_default(signal)

        # cantools aralık dışı değerde OverflowError/EncodeError (ValueError DEĞİL)
        # fırlatır; arayüzün tek bir hata türüyle çalışması için ValueError'a çevrilir.
        try:
            data = msg.encode(complete_values)
        except (ValueError, OverflowError, KeyError, TypeError, cantools.database.errors.Error) as exc:
            raise ValueError(f"{name} kodlanamadı: {exc}") from exc
        return msg.frame_id, bytes(data), msg.is_extended_frame
