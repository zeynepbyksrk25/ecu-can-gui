"""Kullanıcının yazdığı değer metnini sayıya çevirme (Worksheets değer / test girişi pencereleri ve yazma yolları ortak kullanır)."""
import math
import re

_HEX_RE = re.compile(r"[+-]?0[xX][0-9a-fA-F]+")


def parse_value_text(text: str) -> float:
    """Kullanıcının girdiği değer metnini sayıya çevirir. Ondalık virgül ('1,5') ve onaltılık tam sayı ('0x1F') kabul
    edilir. Hata -> ValueError."""
    t = (text or "").strip()
    if not t:
        raise ValueError("Değer boş.")
    if _HEX_RE.fullmatch(t):
        return float(int(t, 16))
    try:
        value = float(t.replace(",", "."))
    except ValueError:
        raise ValueError(f"Geçerli bir sayı değil: {text!r}")
    if not math.isfinite(value):
        raise ValueError(f"Sonlu bir sayı olmalı: {text!r}")
    return value
