"""Bağımlılıksız, AKIŞLI Excel (.xlsx) yazıcısı.

NEDEN KENDİ YAZICI: uygulama internetsiz Windows'ta, sabit ve hash'li bir paket kümesiyle kurulur
(openpyxl/xlsxwriter bu kümede yok). .xlsx zaten XML dosyalarından oluşan bir zip'tir; burada yalnızca
bu işte gereken kısmı (metin, sayı, tarih, kalın başlık, sütun genişliği, sabit başlık satırı, süzgeç)
standart kütüphaneyle üretiyoruz.

AKIŞLI: satırlar doğrudan zip'e yazılır; milyonlarca satırlık bir CAN/parametre kaydı bellekte tutulmaz.
Bir sayfa Excel'in satır sınırına (1.048.576) dayanınca otomatik olarak "Ad (2)", "Ad (3)" sayfasına geçilir.
Dosya önce ``.tmp``'ye yazılıp tamamlanınca yerine konur: yarım/bozuk bir .xlsx asla bırakılmaz.

Yalnızca BİLGİSAYARA dosya yazar; ECU'ya (RAM/flaş) hiçbir şey göndermez.
"""
from __future__ import annotations

import datetime
import math
import os
import re
import time
import zipfile
from xml.sax.saxutils import escape

MAX_ROWS = 1_048_576
_BAD_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff￾￿]")
_BAD_SHEET = re.compile(r"[\[\]:*?/\\]")

# stil dizinleri (styles.xml'deki cellXfs sırası)
S_DEFAULT, S_HEADER, S_DATETIME, S_SECONDS, S_BOLD = 0, 1, 2, 3, 4
FORMATS = {None: S_DEFAULT, "datetime": S_DATETIME, "seconds": S_SECONDS, "bold": S_BOLD}

_EPOCH = datetime.datetime(1899, 12, 30)


def col_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


def excel_serial(unix_time: float) -> float:
    """Unix zamanı -> Excel tarih seri numarası (YEREL saat)."""
    offset = time.localtime(unix_time).tm_gmtoff or 0
    return (unix_time + offset) / 86400.0 + 25569.0


def _clean(text) -> str:
    return escape(_BAD_CHARS.sub("", str(text)))


class SheetWriter:
    def __init__(self, book: "XlsxWorkbook", base_name: str, headers: list, widths: list | None,
                 formats: list | None, autofilter: bool):
        self._book = book
        self._base = base_name
        self.headers = list(headers)
        self.widths = widths or [max(10, min(60, len(str(h)) + 4)) for h in headers]
        self.formats = formats or [None] * len(headers)
        self._autofilter = autofilter
        self._part = 0
        self._rows_in_part = 0
        self._handle = None
        self.total_rows = 0                      # veri satırları (başlık hariç)
        self._open_part()

    # -- parça (sayfa) yönetimi
    def _open_part(self):
        self._part += 1
        name = self._base if self._part == 1 else f"{self._base} ({self._part})"
        self._sheet_no, self._sheet_name = self._book._register_sheet(name)
        self._handle = self._book._zip.open(f"xl/worksheets/sheet{self._sheet_no}.xml", "w")
        w = self._handle.write
        w(('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
           'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
           '<sheetFormatPr defaultRowHeight="15"/><cols>').encode("utf-8"))
        for i, width in enumerate(self.widths, 1):
            w(f'<col min="{i}" max="{i}" width="{width}" customWidth="1"/>'.encode("utf-8"))
        w(b"</cols><sheetData>")
        self._rows_in_part = 0
        self._write_row(self.headers, header=True)

    def _close_part(self):
        if self._handle is None:
            return
        last_col = col_letter(max(len(self.headers) - 1, 0))
        tail = "</sheetData>"
        if self._autofilter and self._rows_in_part > 1:
            tail += f'<autoFilter ref="A1:{last_col}{self._rows_in_part}"/>'
        tail += "</worksheet>"
        self._handle.write(tail.encode("utf-8"))
        self._handle.close()
        self._handle = None

    # -- satır yazımı
    def _cell(self, ref: str, value, style: int) -> str:
        if value is None or value == "":
            return ""
        s = f' s="{style}"' if style else ""
        if isinstance(value, bool):
            return f'<c r="{ref}" t="b"{s}><v>{int(value)}</v></c>'
        if isinstance(value, (int, float)):
            if isinstance(value, float) and not math.isfinite(value):
                return ""
            return f'<c r="{ref}"{s}><v>{value!r}</v></c>'
        if isinstance(value, datetime.datetime):
            delta = value - _EPOCH
            return f'<c r="{ref}" s="{S_DATETIME}"><v>{delta.total_seconds() / 86400.0!r}</v></c>'
        return f'<c r="{ref}" t="inlineStr"{s}><is><t xml:space="preserve">{_clean(value)}</t></is></c>'

    def _write_row(self, values, header: bool = False):
        self._rows_in_part += 1
        r = self._rows_in_part
        cells = []
        for i, v in enumerate(values):
            style = S_HEADER if header else FORMATS.get(self.formats[i] if i < len(self.formats) else None, 0)
            cells.append(self._cell(f"{col_letter(i)}{r}", v, style))
        self._handle.write(f'<row r="{r}">{"".join(cells)}</row>'.encode("utf-8"))

    def row(self, values):
        """Bir veri satırı yazar; sayfa dolarsa yeni parça sayfaya geçer."""
        if self._rows_in_part >= MAX_ROWS:
            self._close_part()
            self._open_part()
        self._write_row(values)
        self.total_rows += 1

    def close(self):
        self._close_part()


class XlsxWorkbook:
    """Kullanım::

        with XlsxWorkbook(path) as wb:
            sh = wb.sheet("Veri", ["zaman", "değer"], formats=["datetime", None])
            sh.row([now, 1.5])

    Sayfalar SIRAYLA yazılır (bir sayfa açıkken yenisi açılırsa öncekini kapatır).
    """

    def __init__(self, path: str):
        self.path = path
        self._tmp = path + ".tmp"
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._zip = zipfile.ZipFile(self._tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True)
        self._sheets: list[tuple[int, str]] = []
        self._current: SheetWriter | None = None
        self._names: set[str] = set()
        self._closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.close()
        else:
            self.abort()
        return False

    def sheet(self, name: str, headers: list, widths: list | None = None, formats: list | None = None,
              autofilter: bool = True) -> SheetWriter:
        if self._current is not None:
            self._current.close()
        self._current = SheetWriter(self, name, headers, widths, formats, autofilter)
        return self._current

    def _register_sheet(self, name: str) -> tuple[int, str]:
        clean = _BAD_SHEET.sub("_", name).strip("'") or "Sayfa"
        base = clean[:31]
        candidate, n = base, 1
        while candidate.lower() in self._names:              # Excel, büyük/küçük harf duyarsız tekil ister
            n += 1
            suffix = f" ({n})"
            candidate = base[:31 - len(suffix)] + suffix
        self._names.add(candidate.lower())
        no = len(self._sheets) + 1
        self._sheets.append((no, candidate))
        return no, candidate

    def abort(self):
        if self._closed:
            return
        self._closed = True
        cur = self._current
        if cur is not None and cur._handle is not None:        # açık sayfa tutamacı kapanmadan zip kapanamaz
            try:
                cur._handle.close()
            except Exception:  # noqa: BLE001
                pass
            cur._handle = None
        try:
            self._zip.close()
        except Exception:  # noqa: BLE001 - zaten hata yolundayız; asıl hata çağırana gider
            pass
        try:
            os.remove(self._tmp)
        except OSError:
            pass

    def close(self):
        if self._closed:
            return
        if self._current is not None:
            self._current.close()
            self._current = None
        if not self._sheets:                                   # Excel en az bir sayfa ister
            self.sheet("Sayfa1", ["(boş)"]).close()
        z = self._zip
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{no}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for no, _ in self._sheets)
        z.writestr("[Content_Types].xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                   '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                   '<Default Extension="xml" ContentType="application/xml"/>'
                   '<Override PartName="/xl/workbook.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                   '<Override PartName="/xl/styles.xml" '
                   'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                   + overrides + "</Types>")
        z.writestr("_rels/.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                   'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        sheets = "".join(f'<sheet name="{escape(name, {chr(34): "&quot;"})}" sheetId="{no}" r:id="rId{no}"/>'
                         for no, name in self._sheets)
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   f'<sheets>{sheets}</sheets></workbook>')
        n = len(self._sheets)
        rels = "".join(
            f'<Relationship Id="rId{no}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/worksheet" Target="worksheets/sheet{no}.xml"/>' for no, _ in self._sheets)
        rels += (f'<Relationship Id="rId{n + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                 f'relationships/styles" Target="styles.xml"/>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + rels + "</Relationships>")
        z.writestr("xl/styles.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
                   '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                   '<numFmts count="2"><numFmt numFmtId="164" formatCode="dd\\.mm\\.yyyy\\ hh:mm:ss.000"/>'
                   '<numFmt numFmtId="165" formatCode="0.000"/></numFmts>'
                   '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
                   '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
                   '<fills count="3"><fill><patternFill patternType="none"/></fill>'
                   '<fill><patternFill patternType="gray125"/></fill>'
                   '<fill><patternFill patternType="solid"><fgColor rgb="FFDDE5EC"/><bgColor indexed="64"/>'
                   '</patternFill></fill></fills>'
                   '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   '<cellXfs count="5">'
                   '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
                   '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
                   '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
                   '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
                   '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
                   '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   '</styleSheet>')
        z.close()
        self._closed = True
        os.replace(self._tmp, self.path)
