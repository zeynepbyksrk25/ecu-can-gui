"""Kullanıcı girdilerinin (CAN ID, data byte'ları) doğrulanması.

Tüm fonksiyonlar geçersiz girdide ValueError fırlatır; UI katmanı bunu
yakalayıp kullanıcıya uyarı mesajı gösterir.
"""

STANDARD_ID_MAX = 0x7FF
EXTENDED_ID_MAX = 0x1FFFFFFF


def validate_can_id(text: str, extended: bool) -> int:
    """'1A0' veya '0x1A0' gibi bir metni tam sayıya çevirir ve aralığını
    seçilen frame type'a (Standard/Extended) göre kontrol eder."""
    text = text.strip().lower().replace("0x", "")
    if not text:
        raise ValueError("CAN ID boş olamaz.")
    try:
        value = int(text, 16)
    except ValueError:
        raise ValueError(f"'{text}' geçerli bir hexadecimal CAN ID değil.")

    limit = EXTENDED_ID_MAX if extended else STANDARD_ID_MAX
    if value < 0 or value > limit:
        kind = "Extended (29-bit)" if extended else "Standard (11-bit)"
        raise ValueError(
            f"CAN ID 0x{value:X}, {kind} aralığının (0x0 - 0x{limit:X}) dışında."
        )
    return value


def validate_data_bytes(text: str, max_len: int = 8) -> bytes:
    """'01 02 03' veya '010203' gibi bir metni byte dizisine çevirir.
    Boşluk/virgül ile ayrılmış ya da bitişik hex çiftleri kabul edilir."""
    cleaned = text.strip().replace(",", " ")
    tokens = cleaned.split() if " " in cleaned else _split_pairs(cleaned)

    if not tokens or tokens == [""]:
        return b""

    try:
        data = bytes(int(t, 16) for t in tokens)
    except ValueError:
        raise ValueError(f"'{text}' içinde geçersiz hex karakter var.")

    if len(data) > max_len:
        raise ValueError(f"Veri en fazla {max_len} byte olabilir (girilen: {len(data)}).")
    return data


def _split_pairs(text: str):
    if len(text) % 2 != 0:
        raise ValueError(f"'{text}' çift sayıda hex karakter içermiyor.")
    return [text[i:i + 2] for i in range(0, len(text), 2)]


def validate_can_id_decimal(text: str, extended: bool) -> int:
    """Decimal (onluk) CAN ID doğrulaması (geriye dönük uyumluluk için)."""
    text = text.strip()
    if not text:
        raise ValueError("CAN ID boş olamaz.")
    if not text.isdigit():
        raise ValueError(f"'{text}' geçerli bir onluk (decimal) sayı değil.")

    value = int(text)
    limit = EXTENDED_ID_MAX if extended else STANDARD_ID_MAX
    if value > limit:
        kind = "Extended (29-bit)" if extended else "Standard (11-bit)"
        raise ValueError(
            f"CAN ID {value}, {kind} aralığının (0 - {limit}) dışında."
        )
    return value


def validate_data_bytes_decimal(text: str, max_len: int = 8) -> bytes:
    """'1,2,3,4' veya '1 2 3 4' gibi onluk byte listesini bytes'a çevirir."""
    cleaned = text.strip().replace(",", " ")
    if not cleaned:
        return b""

    tokens = cleaned.split()
    values = []
    for token in tokens:
        if not token.isdigit():
            raise ValueError(f"'{token}' geçerli bir onluk (decimal) byte değeri değil.")
        value = int(token)
        if value > 255:
            raise ValueError(f"'{value}' bir byte'a sığmaz (0-255 aralığında olmalı).")
        values.append(value)

    if len(values) > max_len:
        raise ValueError(f"Veri en fazla {max_len} byte olabilir (girilen: {len(values)}).")
    return bytes(values)
