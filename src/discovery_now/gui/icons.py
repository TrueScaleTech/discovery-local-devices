"""The app icon, drawn in code so there is no image file to ship or to go stale."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QPixmap,
)

_SIZES = (16, 24, 32, 48, 64, 128, 256)


def _paint(size: int) -> QImage:
    """A rounded teal tile with a radar sweep: the look of "finding what is out there"."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.03
    tile = QRectF(0, 0, size, size).adjusted(margin, margin, -margin, -margin)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#0b7a86")))
    painter.drawRoundedRect(tile, size * 0.22, size * 0.22)

    centre = QPointF(size * 0.5, size * 0.5)
    for factor, alpha in ((0.34, 255), (0.22, 170)):
        pen = QPen(QColor(255, 255, 255, alpha))
        pen.setWidthF(max(1.0, size * 0.06))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        radius = size * factor
        painter.drawArc(
            QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2),
            30 * 16,
            120 * 16,
        )

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#ffffff")))
    dot = size * 0.075
    painter.drawEllipse(QPointF(centre.x(), centre.y() + size * 0.1), dot, dot)
    painter.end()
    return image


def app_icon() -> QIcon:
    """The icon at every size the desktop might ask for."""
    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(QPixmap.fromImage(_paint(size)))
    return icon


def save_ico(path: Path) -> None:
    """Write the icon as a Windows .ico (the format follows the file name)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _paint(256).save(str(path)):
        raise OSError(f"could not write {path}")


if __name__ == "__main__":  # pragma: no cover - used by the packaging script
    _app = QGuiApplication(sys.argv)
    save_ico(Path(sys.argv[1]))
