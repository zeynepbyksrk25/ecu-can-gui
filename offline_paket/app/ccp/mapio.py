"""1D (curve) / 2D (map) kalibrasyon tablolarını CCP üzerinden ECU
belleğinden okuma/yazma.

VARSAYIM (henüz gerçek donanımla doğrulanmadı): fonksiyon değerlerinin
characteristic'in A2L ADDRESS'inden itibaren satır-majör (row-major)
sırada, ardışık olarak dizili olduğu varsayılır. FIX_AXIS eksenler için
bu doğrudur (eksen noktaları A2L'de sabit tanımlıdır, ECU belleğinde
ekstra yer kaplamaz). STD_AXIS/COM_AXIS gibi eksen türlerinde gerçek
RECORD_LAYOUT genelde eksen noktalarını da bu bloğun İÇİNE, fonksiyon
değerlerinden ÖNCE yerleştirir; bu modül o durumu hesaba katmıyor, yani
STD_AXIS eksenli bir harita için okunan/yazılan ofset kayabilir. Gerçek
ECU'ya karşı kullanmadan önce PCAN-View trace'iyle doğrulanmalı — bkz.
CCPTab/MapEditorTab'daki uyarı etiketleri.
"""

from app.ccp import codec as ccp_codec


def grid_shape(characteristic) -> tuple[int, int]:
    """(satır, sütun) döner. SCALAR: (1,1). CURVE (1 eksen): (1, N).
    MAP (2 eksen): axes[0]=X (sütun), axes[1]=Y (satır).
    ARRAY (VAL_BLK, eksensiz): dims=(N,) -> (1, N); dims=(R, C) -> (R, C)
    (satır-majör bellek düzeni varsayılır)."""
    if getattr(characteristic, "kind", "") == "ARRAY":
        dims = getattr(characteristic, "dims", None) or (1,)
        if len(dims) == 1:
            return 1, dims[0]
        return dims[0], dims[1]
    axes = characteristic.axes
    if not axes:
        return 1, 1
    if len(axes) == 1:
        return 1, axes[0].count
    return axes[1].count, axes[0].count


def read_grid(ccp_client, characteristic) -> list:
    rows, cols = grid_shape(characteristic)
    size = ccp_codec.datatype_size(characteristic.datatype)
    total_bytes = size * rows * cols
    raw_bytes = ccp_client.read_memory(
        characteristic.address, total_bytes, characteristic.address_extension or 0
    )
    grid = []
    for r in range(rows):
        row_vals = []
        for c in range(cols):
            offset = (r * cols + c) * size
            raw = ccp_codec.decode_value(
                characteristic.datatype, raw_bytes[offset:offset + size], characteristic.byte_order
            )
            row_vals.append(ccp_codec.raw_to_physical(characteristic.compu_method, raw))
        grid.append(row_vals)
    return grid


def write_grid(ccp_client, characteristic, grid: list):
    rows, cols = grid_shape(characteristic)
    size = ccp_codec.datatype_size(characteristic.datatype)
    payload = bytearray()
    for r in range(rows):
        for c in range(cols):
            raw = ccp_codec.physical_to_raw(characteristic.compu_method, grid[r][c])
            payload += ccp_codec.encode_value(characteristic.datatype, raw, characteristic.byte_order)
    ccp_client.write_memory(characteristic.address, bytes(payload), characteristic.address_extension or 0)
