"""Small, resolution-independent controls painted by Qt on every supported system."""

from functools import lru_cache
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF


@lru_cache(maxsize=64)
def icon(name, color="#E1E1E1"):
    pixmap = QPixmap(72, 72)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(3, 3)
    ink = QColor(color)
    pen = QPen(ink, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    def lines(*points):
        painter.drawPolyline(QPolygonF([QPointF(*p) for p in points]))

    def solid(*points):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        painter.drawPolygon(QPolygonF([QPointF(*point) for point in points]))

    if name in ("play", "next", "previous"):
        if name == "previous":
            painter.translate(24, 0)
            painter.scale(-1, 1)
        if name != "play":
            lines((19, 5), (19, 19))
        solid((6, 4), (18, 12), (6, 20))
    elif name == "pause":
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ink)
        for x in (5, 14):
            painter.drawRoundedRect(QRectF(x, 4, 5, 16), 1, 1)
    elif name == "back":
        lines((9, 5), (2, 12), (9, 19))
        lines((3, 12), (22, 12))
    elif name == "add":
        lines((12, 3), (12, 21))
        lines((3, 12), (21, 12))
    elif name == "repeat":
        lines((4, 11), (4, 8), (7, 5), (19, 5))
        lines((16, 2), (20, 5), (16, 8))
        lines((20, 13), (20, 16), (17, 19), (5, 19))
        lines((8, 16), (4, 19), (8, 22))
    elif name == "check":
        lines((3, 12), (9, 18), (21, 5))
    elif name == "search":
        painter.drawEllipse(QRectF(3, 3, 13, 13))
        lines((15, 15), (21, 21))
    elif name == "folder":
        lines((2, 6), (8, 6), (10, 9), (21, 9), (21, 19), (2, 19), (2, 6))
    elif name == "library":
        for x in (3, 8):
            painter.drawRoundedRect(QRectF(x, 4, 3, 16), 0.7, 0.7)
        lines((13, 5), (17, 4), (21, 19), (17, 20), (13, 5))
    elif name == "heart":
        path = QPainterPath(QPointF(12, 20))
        path.cubicTo(8, 17, 2, 13, 2, 8)
        path.cubicTo(2, 2, 9, 2, 12, 7)
        path.cubicTo(15, 2, 22, 2, 22, 8)
        path.cubicTo(22, 13, 16, 18, 12, 20)
        painter.drawPath(path)
    elif name == "music":
        lines((8, 17), (8, 6), (20, 3), (20, 15))
        painter.setBrush(ink)
        painter.drawEllipse(QRectF(2, 15, 6, 4))
        painter.drawEllipse(QRectF(14, 13, 6, 4))
    elif name == "external":
        lines((5, 19), (19, 5))
        lines((9, 5), (19, 5), (19, 15))
    painter.end()
    pixmap.setDevicePixelRatio(3)
    return QIcon(pixmap)
