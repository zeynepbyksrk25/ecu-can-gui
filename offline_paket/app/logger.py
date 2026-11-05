"""CAN trafiğini (RX VE TX) zaman damgalı bir CSV dosyasına kaydeden modül.

Sütunlar: timestamp_ms, direction (RX/TX), can_id_hex, message (DBC mesaj adı, varsa),
dlc, data_hex, extended.
"""

import csv
import datetime
from pathlib import Path

HEADER = ["timestamp_ms", "direction", "can_id_hex", "message", "dlc", "data_hex", "extended"]


class CanLogger:
    def __init__(self):
        self._file = None
        self._writer = None

    @property
    def is_active(self) -> bool:
        return self._file is not None

    def start(self, directory: str) -> str:
        Path(directory).mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = str(Path(directory) / f"can_log_{stamp}.csv")
        self._file = open(path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(HEADER)
        return path

    def write(self, timestamp: float, arbitration_id: int, dlc: int,
              data: bytes, extended: bool, direction: str = "RX", name: str = ""):
        if self._writer is None:
            return
        self._writer.writerow([
            f"{timestamp * 1000:.3f}",
            direction,
            f"{arbitration_id:X}",
            name,
            dlc,
            bytes(data).hex(sep=" ").upper(),
            "1" if extended else "0",
        ])

    def stop(self):
        if self._file is not None:
            self._file.close()
            self._file = None
            self._writer = None
