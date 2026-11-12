"""The app icon and the interface's icons, drawn in code.

Nothing here is a picture file or a character borrowed from a font: every mark is
a path on a 24-unit grid with one stroke weight, so the set stays consistent at
any size and takes whatever colour it is given.

The app icon is the wordmark: NOW bent over the dot, the two close together.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)

#: The tile colour of the app icon. It does not follow the accent: an icon that
#: changed colour with a preference would stop being recognisable on a taskbar.
BRAND = "#0a6e78"

_ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)

# -- the wordmark ------------------------------------------------------------

#: N and W as points on a 10 by 12 box, each drawn as one open stroke. The O is a
#: ring, so all three letters keep the same weight.
_N = ((0.0, 12.0), (0.0, 0.0), (10.0, 12.0), (10.0, 0.0))
_W = ((0.0, 0.0), (2.5, 12.0), (5.0, 3.5), (7.5, 12.0), (10.0, 0.0))

Points = tuple[tuple[float, float], ...]


def _letter(points: Points, width: float, height: float) -> QPainterPath:
    """One letter, centred on the origin so it can be placed on the arc."""
    path = QPainterPath()
    for index, (x, y) in enumerate(points):
        point = QPointF(x / 10 * width - width / 2, y / 12 * height - height / 2)
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    return path


def _draw_wordmark(painter: QPainter, size: float) -> None:
    """NOW on an arc, curving over the dot just below it."""
    centre = QPointF(size * 0.5, size * 0.632)
    radius = size * 0.272
    height = size * 0.125
    width = size * 0.095
    stroke = max(1.0, size * 0.038)

    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    for angle, shape in ((-26.0, _N), (0.0, None), (26.0, _W)):
        painter.save()
        painter.translate(centre)
        painter.rotate(angle)
        painter.translate(0, -radius)
        if shape is None:
            ring = height * 0.5 - stroke * 0.5
            painter.drawEllipse(QPointF(0, 0), ring * 0.95, ring)
        else:
            painter.drawPath(_letter(shape, width, height))
        painter.restore()

    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawEllipse(centre, size * 0.105, size * 0.105)


def _draw_small_mark(painter: QPainter, size: float) -> None:
    """Below the size where three letters would turn to mush: the dot and one arc."""
    centre = QPointF(size * 0.5, size * 0.6)
    pen = QPen(QColor("#ffffff"))
    pen.setWidthF(max(1.0, size * 0.085))
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    radius = size * 0.26
    painter.drawArc(
        QRectF(centre.x() - radius, centre.y() - radius, radius * 2, radius * 2),
        25 * 16,
        130 * 16,
    )
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor("#ffffff")))
    painter.drawEllipse(centre, size * 0.1, size * 0.1)


def app_image(size: int) -> QImage:
    """The app icon at one size, on its rounded brand tile."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    margin = size * 0.03
    tile = QRectF(0, 0, size, size).adjusted(margin, margin, -margin, -margin)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(QColor(BRAND)))
    painter.drawRoundedRect(tile, size * 0.22, size * 0.22)

    if size >= 64:
        _draw_wordmark(painter, size)
    else:
        _draw_small_mark(painter, size)
    painter.end()
    return image


def app_icon() -> QIcon:
    """The app icon at every size the desktop might ask for."""
    icon = QIcon()
    for size in _ICO_SIZES:
        icon.addPixmap(QPixmap.fromImage(app_image(size)))
    return icon


def save_ico(path: Path) -> None:
    """Write the icon as a Windows .ico (the format follows the file name)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not app_image(256).save(str(path)):
        raise OSError(f"could not write {path}")


# -- the interface's icons ---------------------------------------------------

Draw = Callable[[QPainterPath], None]


def _line(path: QPainterPath, x1: float, y1: float, x2: float, y2: float) -> None:
    path.moveTo(x1, y1)
    path.lineTo(x2, y2)


def _poly(path: QPainterPath, *points: tuple[float, float]) -> None:
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)


def _circle(path: QPainterPath, x: float, y: float, radius: float) -> None:
    path.addEllipse(QPointF(x, y), radius, radius)


def _box(path: QPainterPath, x: float, y: float, w: float, h: float, r: float = 2.0) -> None:
    path.addRoundedRect(QRectF(x, y, w, h), r, r)


def _devices(path: QPainterPath) -> None:
    _box(path, 2, 4, 13, 9)
    _line(path, 8.5, 13, 8.5, 17)
    _line(path, 6, 17, 11, 17)
    _box(path, 17, 9, 5, 12, 1.5)


def _topology(path: QPainterPath) -> None:
    _circle(path, 12, 5, 2.6)
    _circle(path, 4, 18, 2.6)
    _circle(path, 20, 18, 2.6)
    _line(path, 10.4, 7.1, 5.3, 15.6)
    _line(path, 13.6, 7.1, 18.7, 15.6)
    _line(path, 6.6, 18, 17.4, 18)


def _activity(path: QPainterPath) -> None:
    _poly(path, (2, 12), (7, 12), (10, 4.5), (14, 19.5), (17, 12), (22, 12))


def _settings(path: QPainterPath) -> None:
    _line(path, 3, 7.5, 21, 7.5)
    _line(path, 3, 16.5, 21, 16.5)
    _circle(path, 9, 7.5, 2.8)
    _circle(path, 15, 16.5, 2.8)


def _search(path: QPainterPath) -> None:
    _circle(path, 10.5, 10.5, 6.5)
    _line(path, 15.3, 15.3, 20.5, 20.5)


def _scan(path: QPainterPath) -> None:
    _circle(path, 12, 14.5, 1.7)
    for radius in (5.5, 9.5):
        box = QRectF(12 - radius, 14.5 - radius, radius * 2, radius * 2)
        path.arcMoveTo(box, 30)
        path.arcTo(box, 30, 120)


def _export(path: QPainterPath) -> None:
    _poly(path, (3, 15), (3, 20.5), (21, 20.5), (21, 15))
    _line(path, 12, 3, 12, 15)
    _poly(path, (7.5, 8.5), (12, 3.6), (16.5, 8.5))


def _check(path: QPainterPath) -> None:
    _poly(path, (4, 12.5), (9.5, 18), (20, 6.5))


def _trash(path: QPainterPath) -> None:
    _line(path, 3.5, 6, 20.5, 6)
    _poly(path, (5.5, 6), (6.6, 20.5), (17.4, 20.5), (18.5, 6))
    _poly(path, (9, 6), (9, 3.5), (15, 3.5), (15, 6))


def _info(path: QPainterPath) -> None:
    _circle(path, 12, 12, 9)
    _line(path, 12, 11, 12, 17)
    _line(path, 12, 7.2, 12, 7.4)


def _folder(path: QPainterPath) -> None:
    _poly(path, (3, 19.5), (3, 5), (9.5, 5), (11.5, 8), (21, 8), (21, 19.5), (3, 19.5))


def _plus(path: QPainterPath) -> None:
    _line(path, 12, 5, 12, 19)
    _line(path, 5, 12, 19, 12)


def _minus(path: QPainterPath) -> None:
    _line(path, 5, 12, 19, 12)


def _fit(path: QPainterPath) -> None:
    _poly(path, (3, 8.5), (3, 3.5), (8.5, 3.5))
    _poly(path, (15.5, 3.5), (21, 3.5), (21, 8.5))
    _poly(path, (21, 15.5), (21, 20.5), (15.5, 20.5))
    _poly(path, (8.5, 20.5), (3, 20.5), (3, 15.5))


def _close(path: QPainterPath) -> None:
    _line(path, 5.5, 5.5, 18.5, 18.5)
    _line(path, 18.5, 5.5, 5.5, 18.5)


def _chevron(path: QPainterPath) -> None:
    _poly(path, (7, 10), (12, 15), (17, 10))


def _palette(path: QPainterPath) -> None:
    _circle(path, 12, 12, 9)
    _circle(path, 12, 7.6, 1.5)
    _circle(path, 8, 13.6, 1.5)
    _circle(path, 16, 13.6, 1.5)


def _bell(path: QPainterPath) -> None:
    _poly(path, (5.5, 17.5), (7, 15), (7, 10.5))
    box = QRectF(7, 4, 10, 10)
    path.arcMoveTo(box, 0)
    path.arcTo(box, 0, 180)
    _poly(path, (17, 10.5), (17, 15), (18.5, 17.5), (5.5, 17.5))
    _line(path, 10, 20.5, 14, 20.5)


def _shield(path: QPainterPath) -> None:
    _poly(path, (12, 2.5), (20, 6), (20, 12), (12, 21.5), (4, 12), (4, 6), (12, 2.5))


def _printer(path: QPainterPath) -> None:
    _poly(path, (7, 8), (7, 3.5), (17, 3.5), (17, 8))
    _box(path, 3, 8, 18, 8)
    _poly(path, (7, 13), (7, 20.5), (17, 20.5), (17, 13))


def _camera(path: QPainterPath) -> None:
    _box(path, 2.5, 6.5, 15, 11, 2)
    _poly(path, (17.5, 12), (21.5, 8.5), (21.5, 15.5), (17.5, 12))


def _phone(path: QPainterPath) -> None:
    _box(path, 7, 2.5, 10, 19, 2)
    _line(path, 10.5, 18.5, 13.5, 18.5)


def _globe(path: QPainterPath) -> None:
    _circle(path, 12, 12, 9)
    _line(path, 3, 12, 21, 12)
    path.moveTo(12, 3)
    path.cubicTo(17, 7, 17, 17, 12, 21)
    path.moveTo(12, 3)
    path.cubicTo(7, 7, 7, 17, 12, 21)


#: Every icon the interface can draw, by name.
SHAPES: dict[str, Draw] = {
    "devices": _devices,
    "topology": _topology,
    "activity": _activity,
    "settings": _settings,
    "search": _search,
    "scan": _scan,
    "export": _export,
    "check": _check,
    "trash": _trash,
    "info": _info,
    "folder": _folder,
    "plus": _plus,
    "minus": _minus,
    "fit": _fit,
    "close": _close,
    "chevron": _chevron,
    "palette": _palette,
    "bell": _bell,
    "shield": _shield,
    "printer": _printer,
    "camera": _camera,
    "phone": _phone,
    "globe": _globe,
}

_cache: dict[tuple[str, str, int], QIcon] = {}


def paint(painter: QPainter, name: str, rect: QRectF, colour: str, *, width: float = 2.0) -> None:
    """Draw one icon inside ``rect``, in the colour given."""
    path = QPainterPath()
    SHAPES[name](path)
    scale = min(rect.width(), rect.height()) / 24
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.translate(rect.center())
    painter.scale(scale, scale)
    painter.translate(-12, -12)
    pen = QPen(QColor(colour))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


def icon(name: str, colour: str, size: int = 18) -> QIcon:
    """One icon as a QIcon, for a button or a menu entry."""
    key = (name, colour, size)
    found = _cache.get(key)
    if found is not None:
        return found
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    # The stroke is set on the 24-unit grid, so it stays even once scaled down.
    paint(painter, name, QRectF(1, 1, size - 2, size - 2), colour, width=2.1)
    painter.end()
    made = QIcon(QPixmap.fromImage(image))
    _cache[key] = made
    return made


def forget_cached_icons() -> None:
    """Drop the cache, so every icon is redrawn after the appearance changes."""
    _cache.clear()


def status_dot(painter: QPainter, centre: QPointF, colour: str, *, online: bool) -> None:
    """The mark for online or offline: filled when online, an outline when not."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if online:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(colour)))
        painter.drawEllipse(centre, 3.6, 3.6)
    else:
        pen = QPen(QColor(colour))
        pen.setWidthF(1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(centre, 3.0, 3.0)
    painter.restore()


#: Which icon stands for which guessed kind of device, most specific first.
_KIND_ICONS: tuple[tuple[str, str], ...] = (
    ("router", "topology"),
    ("gateway", "topology"),
    ("network", "topology"),
    ("printer", "printer"),
    ("camera", "camera"),
    ("nas", "folder"),
    ("storage", "folder"),
    ("server", "folder"),
    ("proxmox", "folder"),
    ("iphone", "phone"),
    ("phone", "phone"),
    ("tablet", "phone"),
    ("media", "camera"),
    ("tv", "camera"),
    ("web interface", "globe"),
    ("smart", "scan"),
    ("single-board", "activity"),
    ("virtual", "activity"),
)


def device_icon(kind: str | None) -> str:
    """The icon name for a guessed kind, falling back to the generic device."""
    lowered = (kind or "").lower()
    for needle, name in _KIND_ICONS:
        if needle in lowered:
            return name
    return "devices"


if __name__ == "__main__":  # pragma: no cover - used by the packaging script
    _app = QGuiApplication(sys.argv)
    save_ico(Path(sys.argv[1]))
