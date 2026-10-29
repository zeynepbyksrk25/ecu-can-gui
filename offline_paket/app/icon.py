"""Uygulama simgesi — kod ile (QPainter) çizilir; harici dosyaya bağımlı
değildir. Koyu lacivert yuvarlak kare + gümüş çerçeve üzerinde turbojet motoru
(fanlı giriş, gövde, nozul, alev) ve altta CAN veri yolunu simgeleyen iki hat. build_ico() aynı çizimden
çok boyutlu bir Windows .ico üretir (exe simgesi için)."""

import math
import struct

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
    QPixmap,
)

ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)


def make_pixmap(size: int) -> QPixmap:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256.0, size / 256.0)

    # Zemin: koyu mavi gradyanlı yuvarlak kare + gümüş çerçeve
    grad = QLinearGradient(0, 0, 0, 256)
    grad.setColorAt(0.0, QColor("#1B3A66"))
    grad.setColorAt(1.0, QColor("#08121F"))
    frame = QLinearGradient(0, 0, 256, 256)
    frame.setColorAt(0.0, QColor("#E6EDF5"))
    frame.setColorAt(0.5, QColor("#8D9DB0"))
    frame.setColorAt(1.0, QColor("#DDE5EE"))
    p.setPen(QPen(QBrush(frame), 9))
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(10, 10, 236, 236), 52, 52)

    # Egzoz alevi
    flame = QPainterPath()
    flame.moveTo(196, 118)
    flame.quadTo(236, 128, 246, 128)
    flame.quadTo(236, 128, 196, 138)
    flame.closeSubpath()
    fg = QLinearGradient(190, 0, 246, 0)
    fg.setColorAt(0.0, QColor("#FFD36B"))
    fg.setColorAt(1.0, QColor(255, 120, 30, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(fg))
    p.drawPath(flame)

    # Gövde (nacelle): sol girişten sağ nozula daralan gümüş gövde
    body = QPainterPath()
    body.moveTo(34, 92)
    body.cubicTo(70, 84, 130, 90, 190, 108)
    body.lineTo(204, 112)
    body.lineTo(204, 144)
    body.lineTo(190, 148)
    body.cubicTo(130, 166, 70, 172, 34, 164)
    body.closeSubpath()
    bg = QLinearGradient(0, 86, 0, 172)
    bg.setColorAt(0.0, QColor("#F2F6FA"))
    bg.setColorAt(0.45, QColor("#A9B7C6"))
    bg.setColorAt(1.0, QColor("#5C6B7D"))
    p.setPen(QPen(QColor("#2B3A4D"), 3))
    p.setBrush(QBrush(bg))
    p.drawPath(body)

    # Nozul halkası
    p.setBrush(QColor("#3A4A5E"))
    p.drawRoundedRect(QRectF(196, 108, 16, 40), 5, 5)

    # Giriş (fan yüzü): koyu elips + kanatlar
    cx, cy = 40.0, 128.0
    p.setPen(QPen(QColor("#E6EDF5"), 4))
    p.setBrush(QColor("#0A1624"))
    p.drawEllipse(QPointF(cx, cy), 20, 40)
    p.setPen(QPen(QColor("#7FB4F0"), 3.2, Qt.SolidLine, Qt.RoundCap))
    for i in range(8):
        a = math.radians(i * 45 + 12)
        p.drawLine(QPointF(cx, cy), QPointF(cx + 15 * math.cos(a), cy + 34 * math.sin(a)))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#E6EDF5"))
    p.drawEllipse(QPointF(cx, cy), 6, 6)

    # Gövde üzerinde vurgu çizgileri
    p.setPen(QPen(QColor(255, 255, 255, 150), 3, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(78, 100), QPointF(170, 114))
    p.setPen(QPen(QColor("#2B3A4D"), 2.5))
    for x in (108, 138, 168):
        p.drawLine(QPointF(x, 100 + (x - 100) * 0.2), QPointF(x, 160 - (x - 100) * 0.2))

    # Alt kısım: CAN veri yolu (iki hat + düğümler)
    for y, col in ((188, "#5AA9FF"), (210, "#8FD0FF")):
        pen = QPen(QColor(col), 7)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(52, y), QPointF(204, y))
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#F4F7FA"))
    for x in (76, 128, 180):
        p.drawEllipse(QPointF(x, 188), 5, 5)
        p.drawEllipse(QPointF(x, 210), 5, 5)
    p.end()
    return QPixmap.fromImage(img)


def make_icon() -> QIcon:
    icon = QIcon()
    for s in ICON_SIZES:
        icon.addPixmap(make_pixmap(s))
    return icon


def build_ico(path: str):
    """Windows .ico (PNG gömülü girdiler) yazar."""
    images = []
    for s in ICON_SIZES:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        make_pixmap(s).save(buf, "PNG")
        images.append((s, bytes(ba)))
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, blobs = b"", b""
    for s, data in images:
        dim = 0 if s >= 256 else s
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        blobs += data
        offset += len(data)
    with open(path, "wb") as f:
        f.write(header + entries + blobs)
