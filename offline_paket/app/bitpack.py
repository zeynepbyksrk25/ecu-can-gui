"""DBC olmadan, kullanıcının 'start bit / uzunluk / değer' şeklinde
tanımladığı alanları (bit field) tek bir CAN data byte dizisine paketler.

Bit numaralandırması DBC'nin 'Intel' (little-endian) kuralıyla aynıdır:
bit 0 = ilk byte'ın en düşük anlamlı biti (LSB), bit numarası arttıkça
sırayla üst byte'lara doğru ilerler.
"""


class BitFieldError(ValueError):
    pass


def pack_fields(fields, byte_count: int = 8) -> bytes:
    """fields: [{"name": str, "start": int, "length": int, "signed": bool,
    "value": int}, ...] -> byte_count uzunluğunda bytes döner."""
    total_bits = byte_count * 8
    accumulator = 0

    for field in fields:
        label = field.get("name") or f"bit{field['start']}"
        start = field["start"]
        length = field["length"]
        value = field["value"]
        signed = field.get("signed", False)

        if length <= 0 or length > total_bits:
            raise BitFieldError(f"'{label}': uzunluk 1-{total_bits} arasında olmalı.")
        if start < 0 or start + length > total_bits:
            raise BitFieldError(
                f"'{label}': start({start})+length({length}), {byte_count} byte'a (yani "
                f"{total_bits} bite) sığmıyor."
            )

        mask = (1 << length) - 1
        if signed:
            minimum = -(1 << (length - 1))
            maximum = (1 << (length - 1)) - 1
            if not (minimum <= value <= maximum):
                raise BitFieldError(
                    f"'{label}': değer {value}, {length}-bit işaretli aralığına "
                    f"({minimum}..{maximum}) sığmıyor."
                )
        else:
            if not (0 <= value <= mask):
                raise BitFieldError(
                    f"'{label}': değer {value}, {length}-bit işaretsiz aralığına "
                    f"(0..{mask}) sığmıyor."
                )

        raw = value & mask  # negatif değer de iki's complement olarak maskeleniyor
        accumulator |= raw << start

    return accumulator.to_bytes(byte_count, byteorder="little")
