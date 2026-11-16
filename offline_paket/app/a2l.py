"""A2L (ASAM MCD-2 MC) dosyasını pya2l ile okuyup, uygulamanın geri kalanının
(nesne tarayıcı, kalibrasyon ekranı, harita editörü) ihtiyaç duyduğu basit
Python nesnelerine (dataclass) çeviren katman. pya2l'in kendi zengin
nesneleriyle UI kodunu doğrudan karıştırmamak için bu ince katman var.
"""

from dataclasses import dataclass, field

from pya2l import import_a2l
from sqlalchemy.orm import selectinload
import pya2l.api.inspect as insp
import pya2l.model as model


@dataclass
class MeasurementInfo:
    name: str
    description: str
    datatype: str
    unit: str
    minimum: float | None
    maximum: float | None
    address: int | None = None          # ECU_ADDRESS (yoksa None -> CCP ile okunamaz)
    address_extension: int = 0
    byte_order: str | None = None       # "MSB_FIRST"/"MSB_LAST"/... ya da None
    compu_method: object | None = None  # pya2l CompuMethod nesnesi ya da None


@dataclass
class AxisInfo:
    count: int                  # eksen üzerindeki nokta sayısı (maxAxisPoints)
    unit: str
    attribute: str              # "FIX_AXIS" | "STD_AXIS" | "COM_AXIS" | "RES_AXIS" | "CURVE_AXIS"
    values: list | None = None  # statik biliniyorsa (şu an sadece FIX_AXIS) sayı listesi, yoksa None


@dataclass
class CharacteristicInfo:
    name: str
    description: str
    kind: str          # "SCALAR" | "CURVE" (1D, eksenli) | "MAP" (2D, eksenli) | "ARRAY" (VAL_BLK: eksensiz sabit dizi/blok)
    address: int
    unit: str
    datatype: str
    minimum: float | None
    maximum: float | None
    read_only: bool
    num_axes: int
    address_extension: int = 0
    byte_order: str | None = None
    compu_method: object | None = None  # pya2l CompuMethod nesnesi ya da None
    axes: list = field(default_factory=list)  # AxisInfo listesi (SCALAR için boş)
    index_mode: str | None = None             # RECORD_LAYOUT FNC_VALUES indexMode: ROW_DIR/COLUMN_DIR/ALTERNATE_*
    char_type: str = ""                       # A2L CHARACTERISTIC tipi: VALUE/CURVE/MAP/VAL_BLK/ASCII/CUBOID...
    dims: tuple | None = None                 # ARRAY için boyutlar: (N,) = 1xN dizi, (R, C) = 2B blok


@dataclass
class A2LSummary:
    path: str
    project_name: str
    module_name: str
    default_byte_order: str | None = None   # MOD_COMMON BYTE_ORDER (nesnede yoksa bu geçerli)
    measurements: list = field(default_factory=list)
    characteristics: list = field(default_factory=list)

    # ---- okunabilir tek değerli nesneler (grafik / trend / çalışma alanı / performans) ----
    def tunable_scalars(self) -> list:
        """Ayarlanabilir (kalibrasyon) tek değerli parametreler: skaler CHARACTERISTIC (VALUE).
        Adresi ve veri tipi çözülebilenler; clbc_* gibi parametreler buradadır."""
        return [c for c in self.characteristics
                if c.kind == "SCALAR" and c.address is not None and c.datatype
                and (c.char_type in ("", "VALUE"))]

    def readable(self) -> list:
        """Sürekli okunup çizilebilen tüm nesneler: ölçümler + ayarlanabilir skaler parametreler."""
        return list(self.measurements) + self.tunable_scalars()

    def readable_by_name(self) -> dict:
        """ad -> nesne; aynı ad ikisinde de varsa ölçüm önceliklidir."""
        out = {c.name: c for c in self.tunable_scalars()}
        out.update({m.name: m for m in self.measurements})
        return out


def _fix_axis_values(ad) -> list | None:
    """FIX_AXIS eksenlerinin nokta değerleri A2L içinde (ECU'ya gitmeden)
    hesaplanabilir/verilidir. Diğer eksen tipleri (STD_AXIS/COM_AXIS/
    RES_AXIS/CURVE_AXIS) için değerler ya ECU belleğinde ya da başka bir
    Characteristic'te tutulur; bu ilk sürüm onları çözmüyor (None döner,
    UI index numaralarını gösterir)."""
    if ad.fixAxisParList:
        return list(ad.fixAxisParList)
    p = ad.fixAxisPar
    if p and p.valid():
        return [p.offset + i * (2 ** p.shift) for i in range(p.numberapo)]
    pd = ad.fixAxisParDist
    if pd and pd.valid():
        return [pd.offset + i * pd.distance for i in range(pd.numberapo)]
    return None


def _build_axes(characteristic) -> list:
    axes = []
    for ad in (characteristic.axisDescriptions or []):
        compu = _compu(ad.compuMethod)
        unit = compu.unit if compu else (ad.physUnit or "")
        values = _fix_axis_values(ad) if ad.attribute == "FIX_AXIS" else None
        axes.append(AxisInfo(
            count=ad.maxAxisPoints,
            unit=unit or "",
            attribute=ad.attribute or "",
            values=values,
        ))
    return axes


def _array_dims(c) -> tuple | None:
    """VAL_BLK (eksensiz dizi/blok) Characteristic'lerin boyutlarını döndürür:
    (N,) -> N elemanlı 1B dizi, (R, C) -> 2B blok. Tek elemanlı ya da
    boyutu belirtilmemiş nesneler için None (skaler gibi davranılır).

    NUMBER (eski, kullanımı önerilmeyen) ve MATRIX_DIM (güncel) ikisi de
    desteklenir. 3 boyutlu bloklar tabloya sığmadığı için son iki boyutu
    ilkine katlanarak (R*C... değil) düzleştirilir: (X, Y, Z) -> (X, Y*Z)."""
    dims: list = []
    md = getattr(c, "matrixDim", None)
    try:
        md_valid = md is not None and md.valid()
    except Exception:
        md_valid = False
    if md_valid:
        for v in (md.x, md.y, md.z):
            if v and int(v) > 1:
                dims.append(int(v))
    elif getattr(c, "number", None):
        n = int(c.number)
        if n > 1:
            dims.append(n)
    if not dims:
        return None
    if len(dims) > 2:
        dims = [dims[0], dims[1] * dims[2]]
    return tuple(dims)


def _default_byte_order(session) -> str | None:
    """MOD_COMMON > BYTE_ORDER ("MSB_FIRST" = big-endian, "MSB_LAST" = little-endian).
    Tek tek MEASUREMENT/CHARACTERISTIC'te BYTE_ORDER yoksa bu değer geçerlidir."""
    try:
        mc = session.query(model.ModCommon).first()
        bo = getattr(mc, "byte_order", None) if mc is not None else None
        return getattr(bo, "byteOrder", None) or None
    except Exception:
        return None


def _compu(compu_method):
    """pya2l, COMPU_METHOD yoksa "NO_COMPU_METHOD" string'i döndürür; bu
    yardımcı onu CCP tarafında kullanışlı olacak şekilde None'a çevirir."""
    if compu_method is None or compu_method == "NO_COMPU_METHOD":
        return None
    return compu_method


class A2LDatabase:
    def __init__(self):
        self._session = None          # yalnızca ayrıştırma SIRASINDA yaşar (aşağıya bakın)
        self.path: str | None = None
        self.summary: A2LSummary | None = None

    @property
    def is_loaded(self) -> bool:
        return self.summary is not None

    def load(self, path: str) -> A2LSummary:
        """A2L dosyasını ayrıştırır (SQLite :memory:) ve parse hatalarını ValueError olarak fırlatır —
        çağıran taraf bunu yakalayıp kullanıcıya gösterir. Başarısız yükleme önceki (geçerli) A2L'i bozmaz.

        Bu metot arka plan iş parçacığında çalışabilir: SQLite bağlantısı onu açan iş parçacığında
        KULLANILIR ve KAPATILIR; uygulamanın geri kalanı yalnızca düz Python nesnelerinden oluşan
        ``summary``'yi kullanır (oturum sonradan başka iş parçacığından açılıp kapatılmaz, bellekte de
        tutulmaz)."""
        try:
            session = import_a2l(
                path, in_memory=True, progress_bar=False, loglevel="ERROR"
            )
        except Exception as exc:
            raise ValueError(f"A2L dosyası parse edilemedi: {exc}")
        try:
            self._session = session
            try:
                summary = self._build_summary(path)
            except Exception as exc:
                raise ValueError(f"A2L içeriği okunamadı: {exc}")
        finally:
            self._session = None
            try:
                session.close()
            except Exception:
                pass
        self.path = path
        self.summary = summary
        return summary

    def _build_summary(self, path: str) -> A2LSummary:
        session = self._session
        project = session.query(model.Project).first()
        module = session.query(model.Module).first()
        default_bo = _default_byte_order(session)
        measurements = []
        # İlişkiler (birim, dönüşüm, bayt sırası...) TOPLU yüklenir: nesne başına tembel (lazy) sorgu 6000
        # nesnelik bir dosyada ~15 sn sürerken toplu yükleme ~1,5 sn sürer.
        for row in session.query(model.Measurement).options(selectinload("*")).all():
            m = insp.Measurement.get(session, row.name, db_instance=row)
            compu = _compu(m.compuMethod)
            unit = compu.unit if compu else ""
            measurements.append(MeasurementInfo(
                name=m.name,
                description=m.longIdentifier or "",
                datatype=m.datatype or "",
                unit=unit or "",
                minimum=m.lowerLimit,
                maximum=m.upperLimit,
                address=getattr(m, "ecuAddress", None),
                address_extension=getattr(m, "ecuAddressExtension", 0) or 0,
                byte_order=getattr(m, "byteOrder", None) or default_bo,
                compu_method=compu,
            ))

        characteristics = []
        for row in session.query(model.Characteristic).options(selectinload("*")).all():
            c = insp.Characteristic.get(session, row.name, db_instance=row)
            compu = _compu(c.compuMethod)
            unit = compu.unit if compu else ""
            num_axes = len(c.axisDescriptions or [])
            kind = "SCALAR" if num_axes == 0 else ("CURVE" if num_axes == 1 else "MAP")
            char_type = getattr(c, "type", "") or ""
            dims = None
            if num_axes == 0 and char_type == "VAL_BLK":
                dims = _array_dims(c)
                if dims is not None:
                    kind = "ARRAY"
            datatype = ""
            index_mode = None
            try:
                datatype = c.record_layout.fncValues.data_type or ""
                index_mode = c.record_layout.fncValues.indexMode
            except AttributeError:
                pass
            characteristics.append(CharacteristicInfo(
                name=c.name,
                description=c.longIdentifier or "",
                kind=kind,
                address=c.address,
                unit=unit or "",
                datatype=datatype,
                minimum=c.lowerLimit,
                maximum=c.upperLimit,
                read_only=bool(c.readOnly),
                num_axes=num_axes,
                address_extension=getattr(c, "ecuAddressExtension", 0) or 0,
                byte_order=getattr(c, "byteOrder", None) or default_bo,
                compu_method=compu,
                axes=_build_axes(c),
                index_mode=index_mode,
                char_type=char_type,
                dims=dims,
            ))

        return A2LSummary(
            path=path,
            project_name=project.name if project else "",
            module_name=module.name if module else "",
            default_byte_order=default_bo,
            measurements=measurements,
            characteristics=characteristics,
        )
