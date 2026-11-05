"""Gelen CAN trafiğini zaman damgalı bir CSV dosyasına kaydeden modül."""

import csv
import datetime
from pathlib import Path


class CanLogger:
    FLUSH_EVERY = 200      # satır; çökmede en çok bu kadar satır kaybolur

    def __init__(self):
        self._file = None
        self._writer = None
        self._since_flush = 0
        self.error: str | None = None   # yazma hatası olduysa mesaj (kayıt durdurulur)

    @property
    def is_active(self) -> bool:
        return self._file is not None

    def start(self, directory: str) -> str:
        directory = (directory or "").strip()
        if not directory:
            raise OSError("Kayıt klasörü boş.")
        self.stop()                                  # ikinci start() ilk dosyayı sızdırmasın
        self.error = None
        Path(directory).mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = Path(directory) / f"can_log_{stamp}.csv"
        n = 1
        while path.exists():                         # aynı saniyede başlatılsa da üzerine yazma
            path = Path(directory) / f"can_log_{stamp}_{n}.csv"
            n += 1
        path = str(path)
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._since_flush = 0
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp_ms", "can_id_hex", "dlc", "data_hex", "extended"])
        return path

    def write(self, timestamp: float, arbitration_id: int, dlc: int,
              data: bytes, extended: bool):
        if self._writer is None:
            return
        try:
            self._writer.writerow([
                f"{timestamp * 1000:.3f}",
                f"{arbitration_id:X}",
                dlc,
                data.hex(sep=" ").upper(),
                "1" if extended else "0",
            ])
            self._since_flush += 1
            if self._since_flush >= self.FLUSH_EVERY:
                self._file.flush()
                self._since_flush = 0
        except OSError as exc:               # disk dolu / sürücü çıkarıldı
            self.error = str(exc)
            self.stop()

    def stop(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError as exc:
                self.error = self.error or str(exc)
            self._file = None
            self._writer = None
