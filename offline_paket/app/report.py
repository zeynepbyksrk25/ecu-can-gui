"""Test oturumu PDF raporu oluşturma (SRS Faz 4: Test Report Generation).

Türkçe karakterler (ş ğ ı İ Ş Ğ ç ö ü) için reportlab'in varsayılan Helvetica
(WinAnsi) fontu YETERSİZDİR; bu yüzden Unicode TTF gömülür: önce paketli
DejaVu Sans (app/fonts), yoksa Windows Arial. Font bulunamazsa rapor
üretilmez (sessizce bozuk PDF yerine açık hata)."""

import os
import sys
import time
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT_REGULAR = "OpenECU-Sans"
FONT_BOLD = "OpenECU-Sans-Bold"


class ReportError(Exception):
    """Rapor üretilemedi (font yok, dosya yazılamadı vb.)."""


def _bundled_font_dir() -> str:
    base = getattr(sys, "_MEIPASS", None)          # PyInstaller --onefile açılım klasörü
    if base:
        return os.path.join(base, "app", "fonts")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts")


def _font_candidates() -> list:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    return [
        (os.path.join(_bundled_font_dir(), "DejaVuSans.ttf"), os.path.join(_bundled_font_dir(), "DejaVuSans-Bold.ttf")),
        (os.path.join(windir, "Fonts", "arial.ttf"), os.path.join(windir, "Fonts", "arialbd.ttf")),
    ]


def register_fonts() -> None:
    """Türkçe destekli fontu reportlab'e kaydeder (idempotent)."""
    if FONT_REGULAR in pdfmetrics.getRegisteredFontNames():
        return
    for regular, bold in _font_candidates():
        if os.path.isfile(regular):
            pdfmetrics.registerFont(TTFont(FONT_REGULAR, regular))
            pdfmetrics.registerFont(TTFont(FONT_BOLD, bold if os.path.isfile(bold) else regular))
            pdfmetrics.registerFontFamily(FONT_REGULAR, normal=FONT_REGULAR, bold=FONT_BOLD,
                                          italic=FONT_REGULAR, boldItalic=FONT_BOLD)
            return
    raise ReportError(
        "PDF için Türkçe karakter destekli yazı tipi bulunamadı (app/fonts/DejaVuSans.ttf veya "
        "Windows Arial). Program klasöründeki 'fonts' dosyalarının eksiksiz olduğundan emin olun."
    )


def _fmt(ts: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "-"


def _p(text, style) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def build_session_report(path: str, session_name: str, operator: str,
                          started_at: float | None, ended_at: float | None,
                          event_log) -> None:
    if not started_at:
        raise ValueError("Rapor için önce oturumu başlatın (Başlangıç zamanı yok).")
    register_fonts()

    base = ParagraphStyle("base", fontName=FONT_REGULAR, fontSize=8, leading=10, splitLongWords=True,
                          wordWrap="CJK")      # "CJK": boşluksuz uzun metinleri de sarar
    meta_style = ParagraphStyle("meta", parent=base, fontSize=9, leading=11)
    head_style = ParagraphStyle("head", parent=base, fontName=FONT_BOLD)
    title_style = ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=18, leading=22,
                                 spaceAfter=6, wordWrap=None)
    h2_style = ParagraphStyle("h2", parent=base, fontName=FONT_BOLD, fontSize=13, leading=16, wordWrap=None)

    end = ended_at or time.time()
    entries = [e for e in event_log.entries if started_at <= e.timestamp <= end]
    skipped = len(event_log.entries) - len(entries)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(FONT_REGULAR, 8)
        canvas.setFillColor(colors.grey)
        canvas.drawString(2 * cm, 1.2 * cm, f"OpenECU M220 Test Raporu — {_fmt(time.time())}")
        canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Sayfa {doc.page}")
        canvas.restoreState()

    tmp = path + ".tmp"
    try:
        doc = SimpleDocTemplate(tmp, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                                topMargin=2 * cm, bottomMargin=2 * cm,
                                title="OpenECU M220 Test Raporu", author=operator or "")
        el = [Paragraph("OpenECU M220 Test Raporu", title_style), Spacer(1, 0.5 * cm)]

        meta = [["Test ismi", session_name or "-"], ["Operatör", operator or "-"],
                ["Başlangıç", _fmt(started_at)], ["Bitiş", _fmt(ended_at) if ended_at else "(devam ediyor)"],
                ["Rapor oluşturma zamanı", _fmt(time.time())]]
        meta_t = Table([[_p(k, head_style), _p(v, meta_style)] for k, v in meta],
                       colWidths=[4.5 * cm, 12.5 * cm])
        meta_t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                    ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        el += [meta_t, Spacer(1, 0.8 * cm), Paragraph("Olay Günlüğü", h2_style), Spacer(1, 0.2 * cm)]

        rows = [[_p(h, head_style) for h in ("Zaman", "Kullanıcı / Rol", "Kategori", "Mesaj")]]
        for e in entries:
            rows.append([_p(time.strftime("%H:%M:%S", time.localtime(e.timestamp)), base),
                         _p(f"{e.user} / {e.role}", base), _p(e.category, base), _p(e.message, base)])
        if len(rows) == 1:
            rows.append([_p("-", base), _p("-", base), _p("-", base), _p("Bu oturum aralığında kayıtlı olay yok", base)])
        log_t = Table(rows, colWidths=[1.8 * cm, 3.6 * cm, 2.6 * cm, 9.0 * cm], repeatRows=1)
        log_t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                   ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
                                   ("VALIGN", (0, 0), (-1, -1), "TOP")]))
        el.append(log_t)
        if skipped:
            el += [Spacer(1, 0.3 * cm),
                   _p(f"Not: oturum aralığı dışında kalan {skipped} olay rapora dahil edilmedi.", base)]
        doc.build(el, onFirstPage=footer, onLaterPages=footer)
        os.replace(tmp, path)
    except OSError as exc:
        raise ReportError(f"PDF yazılamadı: {exc}") from exc
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except OSError:
                pass
