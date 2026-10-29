"""Test oturumu PDF raporu oluşturma (SRS Faz 4: Test Report Generation)."""

import time

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def _fmt(ts: float | None) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)) if ts else "-"


def build_session_report(path: str, session_name: str, operator: str,
                          started_at: float | None, ended_at: float | None,
                          event_log) -> None:
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(path, pagesize=A4,
                             leftMargin=2 * cm, rightMargin=2 * cm,
                             topMargin=2 * cm, bottomMargin=2 * cm)
    elements = []

    elements.append(Paragraph("OpenECU M220 Test Raporu", styles["Title"]))
    elements.append(Spacer(1, 0.5 * cm))

    meta_rows = [
        ["Test ismi", session_name or "-"],
        ["Operatör", operator or "-"],
        ["Başlangıç", _fmt(started_at)],
        ["Bitiş", _fmt(ended_at)],
        ["Rapor oluşturma zamanı", _fmt(time.time())],
    ]
    meta_table = Table(meta_rows, colWidths=[4.5 * cm, 10.5 * cm])
    meta_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(meta_table)
    elements.append(Spacer(1, 0.8 * cm))

    elements.append(Paragraph("Olay Günlüğü", styles["Heading2"]))
    rows = [["Zaman", "Kullanıcı / Rol", "Kategori", "Mesaj"]]
    for e in event_log.entries:
        rows.append([
            time.strftime("%H:%M:%S", time.localtime(e.timestamp)),
            f"{e.user} / {e.role}",
            e.category,
            e.message,
        ])
    if len(rows) == 1:
        rows.append(["-", "-", "-", "Kayıtlı olay yok"])

    log_table = Table(rows, colWidths=[2 * cm, 3.5 * cm, 2.5 * cm, 7 * cm], repeatRows=1)
    log_table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#dddddd")),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    elements.append(log_table)

    doc.build(elements)
