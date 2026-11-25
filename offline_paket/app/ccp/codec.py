"""A2L veri tipleri <-> CAN baytları kodlama/çözme (CCP UPLOAD/DNLOAD için)
ve A2L COMPU_METHOD üzerinden ham (internal)<->fiziksel değer dönüşümü.

Bu modül, bir Measurement/Characteristic'in ECU belleğindeki ham baytlarını
Python sayısına (ve tersine) çevirir. Fiziksel<->ham dönüşümü pya2l'in
kendi COMPU_METHOD evaluator'ına (LINEAR: f(x)=ax+b, IDENTICAL: f(x)=x)
devredilir; desteklenmeyen/karmaşık bir dönüşüm (TAB_INTP, RAT_FUNC vb.) OKUMADA
ham değere düşer (uyarı loglanır); YAZMADA ise ASLA sessizce ham değere
düşmez: UnsupportedConversionError (ValueError alt sınıfı) fırlatılır ve
ECU'ya hiçbir şey yazılmaz.
"""

import logging
import math
import struct
from typing import NamedTuple

log = logging.getLogger(__name__)

_STRUCT_CODES = {
    "UBYTE": "B", "SBYTE": "b",
    "UWORD": "H", "SWORD": "h",
    "ULONG": "L", "SLONG": "l",
    "A_UINT64": "Q", "A_INT64": "q",
    "FLOAT16_IEEE": "e", "FLOAT32_IEEE": "f", "FLOAT64_IEEE": "d",
}


class UnknownDatatypeError(ValueError):
    pass


class UnsupportedConversionError(ValueError):
    """COMPU_METHOD ters çevrilemedi: yazma güvenli değil."""


class ConversionError(ValueError):
    """COMPU_METHOD ham -> fiziksel dönüşümü başarısız: ham değer fiziksel değer gibi GÖSTERİLMEZ."""


class WriteValidationError(ValueError):
    """Yazılmak istenen değer güvenlik kontrolünden geçemedi."""


_INT_RANGES = {
    "UBYTE": (0, 2**8 - 1), "SBYTE": (-2**7, 2**7 - 1),
    "UWORD": (0, 2**16 - 1), "SWORD": (-2**15, 2**15 - 1),
    "ULONG": (0, 2**32 - 1), "SLONG": (-2**31, 2**31 - 1),
    "A_UINT64": (0, 2**64 - 1), "A_INT64": (-2**63, 2**63 - 1),
}
_FLOAT_MAX = {"FLOAT16_IEEE": 65504.0, "FLOAT32_IEEE": 3.4028234663852886e38,
              "FLOAT64_IEEE": 1.7976931348623157e308}


def datatype_size(datatype: str) -> int:
    code = _STRUCT_CODES.get((datatype or "").upper())
    if code is None:
        raise UnknownDatatypeError(f"Bilinmeyen A2L veri tipi: {datatype!r}")
    # Standart boyut (önek ile): "L" öneksiz native 8 bayt olabilir (Linux/macOS), A2L ULONG her zaman 4 bayttır.
    return struct.calcsize("<" + code)


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
    dt = datatype.upper()
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise WriteValidationError(f"Sayısal olmayan değer: {value!r}")
    if not math.isfinite(value):
        raise WriteValidationError(f"Sonlu olmayan değer yazılamaz: {value}")
    if code in ("f", "d", "e"):
        if abs(value) > _FLOAT_MAX[dt]:
            raise WriteValidationError(f"{value:g}, {dt} aralığının dışında.")
    else:
        # round() banker's rounding yapar (2.5 -> 2); ECU'ya yazarken açık
        # "yarıyı yukarı" yuvarlama kullanılır.
        value = int(math.floor(value + 0.5))
        lo, hi = _INT_RANGES[dt]
        if not lo <= value <= hi:
            raise WriteValidationError(f"{value}, {dt} aralığının ({lo}..{hi}) dışında.")
    try:
        return struct.pack(_endian_char(byte_order) + code, value)
    except (struct.error, OverflowError) as exc:
        raise WriteValidationError(f"{dt} için kodlanamadı: {exc}")


def decode_value(datatype: str, data: bytes, byte_order: str | None = None):
    code = _STRUCT_CODES.get((datatype or "").upper())
    if code is None:
        raise UnknownDatatypeError(f"Bilinmeyen A2L veri tipi: {datatype!r}")
    size = struct.calcsize("<" + code)
    if len(data) < size:
        raise ValueError(f"{datatype} için {size} bayt gerekir, {len(data)} bayt geldi.")
    return struct.unpack(_endian_char(byte_order) + code, bytes(data[:size]))[0]


class Reading(NamedTuple):
    """``read_value`` sonucu. Alanlar İSİMLE kullanılmalıdır (demet açma yapılmaz): ``raw_bytes`` ECU'dan
    gelen baytlar, ``raw`` bunların çözülmüş sayısı, ``phys`` COMPU_METHOD uygulanmış fiziksel değer."""
    raw_bytes: bytes
    raw: object
    phys: object


def read_value(reader, info) -> Reading:
    """A2L nesnesinin (Measurement/Characteristic) ECU'daki değerini okur (bayt, ham sayı, fiziksel).

    ``reader`` ``read_memory(adres, uzunluk, adres_uzantısı)`` sunan herhangi bir nesnedir (açık
    CCPClient ya da arayüz zamanlayıcıları için önbellek okuyucu). Hatalar (CCPError,
    CCPTimeoutError, UnknownDatatypeError, ValueError) çağıran tarafa aynen yükselir; her çağıran
    kendi hata gösterimini seçer (satıra yaz, göstergeye neden yaz, sessizce atla)."""
    size = datatype_size(info.datatype)
    byte_order = getattr(info, "byte_order", None)
    raw_bytes = reader.read_memory(info.address, size, getattr(info, "address_extension", 0) or 0)
    raw = decode_value(info.datatype, raw_bytes, byte_order)
    return Reading(raw_bytes, raw, raw_to_physical(getattr(info, "compu_method", None), raw))


def _converter(compu_method):
    """pya2l sürümlerine göre dönüştürücü nesne: CompuMethod.evaluator; NoCompuMethod
    (NO_COMPU_METHOD) için nesnenin kendisi birebir (identity) int_to_physical/physical_to_int sunar."""
    return getattr(compu_method, "evaluator", compu_method)


def raw_to_physical(compu_method, raw):
    """Ham (ECU'dan okunan) değeri COMPU_METHOD ile fiziksel değere çevirir.
    compu_method None ise (NO_COMPU_METHOD) ham değer aynen döner. TAB_VERB (sayı -> metin) tablolarında
    sayısal karşılık yoktur; ham durum kodu aynen döner (Motor Modu gibi sayılar bu kodla yorumlanır).
    Diğer dönüşüm türlerinde (LINEAR, RAT_FUNC, TAB_INTP...) dönüşüm başarısız olursa ConversionError fırlar:
    ham sayı birimiyle birlikte fiziksel değer gibi gösterilirse (örn. 2500 yerine 2,5 bar) yanıltır."""
    if compu_method is None:
        return raw
    try:
        return float(_converter(compu_method).int_to_physical(raw))
    except Exception as exc:
        if str(getattr(compu_method, "conversionType", "")).upper() == "TAB_VERB":
            return raw
        log.warning("COMPU_METHOD ham->fiziksel dönüşümü başarısız (%s)", exc)
        raise ConversionError(f"COMPU_METHOD dönüşümü başarısız (ham değer {raw}): {exc}") from exc


def physical_to_raw(compu_method, phys):
    """Kullanıcının girdiği fiziksel değeri COMPU_METHOD ile ham (ECU'ya
    yazılacak) değere çevirir. Dönüşüm yoksa/desteklenmiyorsa fiziksel
    değeri aynen (yuvarlanarak) ham değer olarak kullanır."""
    if compu_method is None:
        return phys
    try:
        return float(_converter(compu_method).physical_to_int(phys))
    except Exception as exc:
        raise UnsupportedConversionError(
            f"COMPU_METHOD ters dönüşümü desteklenmiyor veya değer aralık dışı ({exc}); yazma yapılmadı."
        )


def validate_write(info, phys, check_read_only: bool = True) -> float:
    """ECU'ya yazmadan ÖNCE fiziksel değeri doğrular: sayısal ve sonlu mu,
    nesne READ_ONLY mi, A2L alt/üst sınırları içinde mi. Geçerli değeri
    (float) döndürür; aksi halde WriteValidationError fırlatır."""
    name = getattr(info, "name", "?")
    if check_read_only and getattr(info, "read_only", False):
        raise WriteValidationError(f"{name}: A2L'de READ_ONLY olarak işaretli, yazılamaz.")
    try:
        v = float(phys)
    except (TypeError, ValueError):
        raise WriteValidationError(f"{name}: sayısal olmayan değer {phys!r}.")
    if not math.isfinite(v):
        raise WriteValidationError(f"{name}: sonlu olmayan değer ({v}) yazılamaz.")
    lo, hi = getattr(info, "minimum", None), getattr(info, "maximum", None)
    # lowerLimit == upperLimit (çoğunlukla 0/0) "sınır tanımsız" anlamına gelir.
    if lo is not None and hi is not None and lo != hi:
        if v < lo or v > hi:
            raise WriteValidationError(f"{name}: {v:g}, izinli aralığın ({lo:g} .. {hi:g}) dışında.")
    return v


def encode_for_write(info, phys, check_read_only: bool = True) -> bytes:
    """Kullanıcının fiziksel değerini doğrulayıp ECU'ya yazılacak ham
    baytlara çevirir. Tüm yazma yolları bunu kullanmalıdır."""
    v = validate_write(info, phys, check_read_only)
    raw = physical_to_raw(getattr(info, "compu_method", None), v)
    return encode_value(info.datatype, raw, getattr(info, "byte_order", None))
