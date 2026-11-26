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
CCPTab ve Worksheets tablo penceresindeki uyarı etiketleri.
"""

import logging

from app.ccp import codec as ccp_codec

log = logging.getLogger(__name__)


class UnsupportedLayoutError(ValueError):
    """Bellek yerleşimi doğrulanamadığı için güvenli yazma yapılamaz."""


_SUPPORTED_INDEX_MODES = (None, "", "ROW_DIR", "COLUMN_DIR")


def layout_support(characteristic) -> tuple[bool, str]:
    """(yazılabilir mi, neden). Yalnızca FIX_AXIS/eksensiz nesneler ve
    ROW_DIR/COLUMN_DIR yerleşimleri desteklenir; STD/COM/RES/CURVE_AXIS ve
    ALTERNATE_* düzenleri ECU belleğinde farklı ofsetlere sahip olduğundan
    yazma REDDEDİLİR (okuma yine yapılabilir, UI uyarı gösterir)."""
    for ax in (getattr(characteristic, "axes", None) or []):
        if (ax.attribute or "") != "FIX_AXIS":
            return False, (f"{ax.attribute} eksenli tablolarda bellek yerleşimi (eksen noktaları "
                           f"kayıt içinde) doğrulanmadı; güvenli yazma yapılamaz.")
    mode = getattr(characteristic, "index_mode", None)
    if mode not in _SUPPORTED_INDEX_MODES:
        return False, f"Desteklenmeyen FNC_VALUES indeks modu: {mode}."
    return True, ""


def _mem_index(characteristic, r: int, c: int, rows: int, cols: int) -> int:
    """(satır, sütun) -> bellekteki eleman sırası."""
    if getattr(characteristic, "index_mode", None) == "COLUMN_DIR":
        return c * rows + r
    return r * cols + c


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
    return _decode_grid(characteristic, raw_bytes)


def _decode_grid(characteristic, raw_bytes: bytes) -> list:
    rows, cols = grid_shape(characteristic)
    size = ccp_codec.datatype_size(characteristic.datatype)
    grid = []
    for r in range(rows):
        row_vals = []
        for c in range(cols):
            offset = _mem_index(characteristic, r, c, rows, cols) * size
            raw = ccp_codec.decode_value(
                characteristic.datatype, raw_bytes[offset:offset + size], characteristic.byte_order
            )
            row_vals.append(ccp_codec.raw_to_physical(characteristic.compu_method, raw))
        grid.append(row_vals)
    return grid


def encode_grid(characteristic, grid: list) -> bytes:
    """Fiziksel grid'i doğrulayıp ECU bellek sırasındaki ham baytlara çevirir.
    Hiçbir şey yazmaz; hata varsa ValueError (WriteValidationError vb.)."""
    ok, why = layout_support(characteristic)
    if not ok:
        raise UnsupportedLayoutError(f"{characteristic.name}: {why}")
    if getattr(characteristic, "read_only", False):
        raise ccp_codec.WriteValidationError(f"{characteristic.name}: A2L'de READ_ONLY, yazılamaz.")
    rows, cols = grid_shape(characteristic)
    if len(grid) != rows or any(len(row) != cols for row in grid):
        raise ValueError(f"{characteristic.name}: tablo boyutu {rows}x{cols} olmalı.")
    size = ccp_codec.datatype_size(characteristic.datatype)
    payload = bytearray(size * rows * cols)
    for r in range(rows):
        for c in range(cols):
            v = ccp_codec.validate_write(characteristic, grid[r][c], check_read_only=False)
            raw = ccp_codec.physical_to_raw(characteristic.compu_method, v)
            chunk = ccp_codec.encode_value(characteristic.datatype, raw, characteristic.byte_order)
            off = _mem_index(characteristic, r, c, rows, cols) * size
            payload[off:off + size] = chunk
    return bytes(payload)


def write_grid(ccp_client, characteristic, grid: list, verify: bool = True) -> list:
    """Tabloyu güvenli yazar: (1) tamamı önceden doğrulanıp kodlanır,
    (2) mevcut içerik anlık görüntü olarak okunur, (3) yazılır, (4) geri
    okunup karşılaştırılır, (5) herhangi bir hata olursa anlık görüntü
    geri yazılır. Döner: yazmadan ÖNCEKİ fiziksel grid (geçmiş/geri alma için)."""
    payload = encode_grid(characteristic, grid)
    ext = characteristic.address_extension or 0
    snapshot = ccp_client.read_memory(characteristic.address, len(payload), ext)
    old_grid = _decode_grid(characteristic, snapshot)
    try:
        ccp_client.write_memory(characteristic.address, payload, ext, verify=verify)
    except Exception as exc:
        try:
            ccp_client.write_memory(characteristic.address, snapshot, ext)
            log.error("%s yazımı başarısız (%s); önceki içerik geri yazıldı.", characteristic.name, exc)
        except Exception as rb_exc:  # noqa: BLE001
            log.critical("%s yazımı başarısız (%s) VE geri alma da başarısız (%s): ECU'daki tablo TUTARSIZ olabilir!",
                         characteristic.name, exc, rb_exc)
            raise RuntimeError(
                f"{characteristic.name}: yazma başarısız ({exc}) ve önceki içerik geri yazılamadı ({rb_exc}). "
                f"ECU'daki tablo tutarsız olabilir; yeniden yazın veya ECU'yu sıfırlayın."
            ) from exc
        raise
    return old_grid
