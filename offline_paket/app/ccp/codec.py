"""A2L veri tipleri <-> CAN baytları kodlama/çözme (CCP UPLOAD/DNLOAD için)
ve A2L COMPU_METHOD üzerinden ham (internal)<->fiziksel değer dönüşümü.

Bu modül, bir Measurement/Characteristic'in ECU belleğindeki ham baytlarını
Python sayısına (ve tersine) çevirir. Fiziksel<->ham dönüşümü pya2l'in
kendi COMPU_METHOD evaluator'ına (LINEAR: f(x)=ax+b, IDENTICAL: f(x)=x)
devredilir; desteklenmeyen/karmaşık bir dönüşüm (TAB_INTP, RAT_FUNC vb.)
için sessizce ham değere düşer (yaklaşık gösterim), hata fırlatmaz.
"""

import struct

_STRUCT_CODES = {
    "UBYTE": "B", "SBYTE": "b",
    "UWORD": "H", "SWORD": "h",
    "ULONG": "L", "SLONG": "l",
    "A_UINT64": "Q", "A_INT64": "q",
    "FLOAT16_IEEE": "e", "FLOAT32_IEEE": "f", "FLOAT64_IEEE": "d",
}


class UnknownDatatypeError(ValueError):
    pass


def datatype_size(datatype: str) -> int:
    code = _STRUCT_CODES.get((datatype or "").upper())
    if code is None:
        raise UnknownDatatypeError(f"Bilinmeyen A2L veri tipi: {datatype!r}")
    return struct.calcsize(code)


def _endian_char(byte_order: str | None) -> str:
    if byte_order and byte_order.upper() in ("LITTLE_ENDIAN", "MSB_LAST"):
        return "<"
    # A2L byteOrder tanımsızsa ya da MSB_FIRST/BIG_ENDIAN ise: Motorola.
    # (CCP'nin adres alanlarıyla da tutarlı bir varsayılan.)
    return ">"


def encode_value(datatype: str, value, byte_order: str | None = None) -> bytes:
    code = _STRUCT_CODES.get((datatype or "").upper())
    if code is None:
        raise UnknownDatatypeError(f"Bilinmeyen A2L veri tipi: {datatype!r}")
    if code in ("f", "d", "e"):
        value = float(value)
    else:
        value = int(round(value))
    return struct.pack(_endian_char(byte_order) + code, value)


def decode_value(datatype: str, data: bytes, byte_order: str | None = None):
    code = _STRUCT_CODES.get((datatype or "").upper())
    if code is None:
        raise UnknownDatatypeError(f"Bilinmeyen A2L veri tipi: {datatype!r}")
    size = struct.calcsize(code)
    if len(data) < size:
        raise ValueError(f"{datatype} için {size} bayt gerekir, {len(data)} bayt geldi.")
    return struct.unpack(_endian_char(byte_order) + code, bytes(data[:size]))[0]


def raw_to_physical(compu_method, raw):
    """Ham (ECU'dan okunan) değeri COMPU_METHOD ile fiziksel değere çevirir.
    compu_method None ise (NO_COMPU_METHOD) ya da dönüşüm desteklenmiyorsa
    ham değeri aynen döndürür."""
    if compu_method is None:
        return raw
    try:
        return float(compu_method.evaluator.int_to_physical(raw))
    except Exception:
        return raw


def physical_to_raw(compu_method, phys):
    """Kullanıcının girdiği fiziksel değeri COMPU_METHOD ile ham (ECU'ya
    yazılacak) değere çevirir. Dönüşüm yoksa/desteklenmiyorsa fiziksel
    değeri aynen (yuvarlanarak) ham değer olarak kullanır."""
    if compu_method is None:
        return phys
    try:
        return float(compu_method.evaluator.physical_to_int(phys))
    except Exception:
        return phys
