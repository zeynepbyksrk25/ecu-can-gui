"""Uygulamanın kalıcı dosyalarının (denetim günlüğü, kalibrasyon geçmişi,
profiller, Ana Sayfa ayarları, parametre listesi...) YAZILDIĞI klasörü tek
yerden belirler.

Eskiden bu dosyalar göreli yola ("audit_log.txt" gibi) yazılıyordu; yani
uygulamanın hangi klasörden BAŞLATILDIĞINA bağlıydı (kısayol / komut satırı
farkı dosyaların başka yerlere dağılmasına yol açabiliyordu). Artık:

  - Her zaman kullanıcının "Belgelerim\\OpenECU_M220_Veri" klasörü (yazılamazsa ana
    klasör, o da olmazsa eski konum). Eski konumdaki dosyalar ilk açılışta oraya kopyalanır.
"""

import os
import shutil
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


def _legacy_base() -> str:
    """Eski sürümlerin verisini yazdığı klasör (exe'nin yanı / çalışma klasörü)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.abspath(os.getcwd())


def _migrate_legacy(dest: str):
    """Eski konumdaki kullanıcı dosyalarını (*.json, audit_log.txt) yeni klasöre BİR KEZ kopyalar.
    Yeni klasörde zaten olan dosyaya dokunmaz; eski dosyalar silinmez."""
    src = _legacy_base()
    if os.path.abspath(src) == os.path.abspath(dest):
        return
    try:
        for name in os.listdir(src):
            if not (name.endswith(".json") or name == "audit_log.txt"):
                continue
            target = os.path.join(dest, name)
            if os.path.exists(target):
                continue
            try:
                shutil.copy2(os.path.join(src, name), target)
            except OSError:
                pass
    except OSError:
        pass


def data_dir() -> str:
    """Kalıcı dosyaların klasörü (mutlak yol). Süreç boyunca sabittir.

    Konum, programın nereden başlatıldığına/hangi exe kopyasından açıldığına BAĞLI DEĞİLDİR:
    her zaman kullanıcının Belgelerim\\OpenECU_M220_Veri klasörüdür; böylece eşleşmeler ve
    diğer ayarlar program kapansa, güç kesilse, exe yeniden derlense/taşınsa da korunur."""
    global _cached
    if _cached is not None:
        return _cached
    override = os.environ.get("OPENECU_VERI_KLASORU")
    if override and _is_writable_dir(override):
        _cached = os.path.abspath(override)
        return _cached
    base = str(Path.home() / "Documents" / _FALLBACK_NAME)
    if not _is_writable_dir(base):
        base = str(Path.home() / _FALLBACK_NAME)
        if not _is_writable_dir(base):
            base = _legacy_base()
    _migrate_legacy(base)
    _cached = base
    return _cached


def data_path(filename: str) -> str:
    """data_dir() içindeki bir dosyanın mutlak yolu."""
    return os.path.join(data_dir(), filename)
