"""Uygulamanın kalıcı dosyalarının (denetim günlüğü, kalibrasyon geçmişi,
profiller, Ana Sayfa ayarları, parametre listesi...) YAZILDIĞI klasörü tek
yerden belirler.

Eskiden bu dosyalar göreli yola ("audit_log.txt" gibi) yazılıyordu; yani
uygulamanın hangi klasörden BAŞLATILDIĞINA bağlıydı (kısayol / komut satırı
farkı dosyaların başka yerlere dağılmasına yol açabiliyordu). Artık:

  - Paketlenmiş .exe: exe'nin YANINDAKİ klasör (taşınabilir uygulama
    mantığı). Orası yazılamazsa (ör. Program Files) kullanıcının
    "Belgelerim\\OpenECU_M220_Veri" klasörü.
  - Geliştirme (python main.py): çalışma klasörü (eski davranış).
"""

import os
import sys
from pathlib import Path

_FALLBACK_NAME = "OpenECU_M220_Veri"
_cached: str | None = None


def _is_writable_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".yazma_testi")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def data_dir() -> str:
    """Kalıcı dosyaların klasörü (mutlak yol). Süreç boyunca sabittir."""
    global _cached
    if _cached is not None:
        return _cached
    override = os.environ.get("OPENECU_VERI_KLASORU")
    if override and _is_writable_dir(override):
        _cached = os.path.abspath(override)
        return _cached
    if getattr(sys, "frozen", False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.abspath(os.getcwd())
    if not _is_writable_dir(base):
        base = str(Path.home() / "Documents" / _FALLBACK_NAME)
        if not _is_writable_dir(base):
            base = str(Path.home() / _FALLBACK_NAME)
            os.makedirs(base, exist_ok=True)
    _cached = base
    return _cached


def data_path(filename: str) -> str:
    """data_dir() içindeki bir dosyanın mutlak yolu."""
    return os.path.join(data_dir(), filename)
