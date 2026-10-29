"""DBC dosyasından mesaj/sinyal tanımlarını okuyan ve mühendislik
birimindeki değerleri (örn. 2.5 bar) doğru CAN ID + data byte'larına
kodlayan katman. Bit paketleme/factor/offset/byteorder işini cantools
kütüphanesi üstlenir; biz sadece UI ile bu kütüphane arasında köprüyüz.
"""

import cantools
from cantools.database.can.message import Message
from cantools.database.can.signal import Signal


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
        except Exception:
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
        for signal in msg.signals:
            if signal.name not in complete_values:
                complete_values[signal.name] = signal.minimum if signal.minimum is not None else 0

        data = msg.encode(complete_values)
        return msg.frame_id, bytes(data), msg.is_extended_frame
