# SPDX-License-Identifier: GPL-3.0-or-later
"""Draw the application icon and write ``src/cbrn_dashboard/resources/app.ico``.

``python scripts/gen_icon.py [--output FILE]``

The artwork is original and abstract: a dark-blue rounded square with a white gauge arc, a needle
and three bars. It is drawn with ``QPainter`` on ``QImage`` (offscreen platform), rendered at
several sizes to PNG and packed into an ICO container by hand (PNG-compressed entries are valid
in ICO). No third-party library is needed and the output is deterministic.
"""

import argparse
import os
import struct
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "src" / "cbrn_dashboard" / "resources" / "app.ico"
SIZES: tuple[int, ...] = (16, 24, 32, 48, 64, 128, 256)

_ICON_DIR = struct.Struct("<HHH")
_ICON_ENTRY = struct.Struct("<BBBBHHII")
_DESIGN_SIZE = 256.0


def render_png(size: int) -> bytes:
    """Draw the icon at ``size`` x ``size`` pixels and return the PNG bytes."""
    from PySide6.QtCore import QBuffer, QIODevice, QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPen

    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.scale(size / _DESIGN_SIZE, size / _DESIGN_SIZE)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor("#12305b")))
        painter.drawRoundedRect(QRectF(8, 8, 240, 240), 48, 48)

        white = QColor("#ffffff")
        arc_pen = QPen(white, 22)
        arc_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(arc_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Three quarters of a circle, open at the bottom: from 210 degrees clockwise by 240.
        painter.drawArc(QRectF(58, 48, 140, 140), 210 * 16, -240 * 16)

        needle_pen = QPen(white, 16)
        needle_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(needle_pen)
        painter.drawLine(QPointF(128, 118), QPointF(164, 82))

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(white))
        painter.drawEllipse(QPointF(128, 118), 14, 14)

        painter.setBrush(QBrush(QColor("#6ec1ff")))
        for x, height in ((72, 24), (114, 36), (156, 48)):
            painter.drawRoundedRect(QRectF(x, 224 - height, 28, height), 6, 6)
    finally:
        painter.end()

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError(f"Could not encode the {size}px icon as PNG")
    return bytes(buffer.data())


def pack_ico(images: Sequence[tuple[int, bytes]]) -> bytes:
    """Pack ``(size, png_bytes)`` pairs into an ICO file (size 256 is stored as byte 0)."""
    header = _ICON_DIR.pack(0, 1, len(images))
    offset = _ICON_DIR.size + _ICON_ENTRY.size * len(images)
    entries = bytearray()
    payload = bytearray()
    for size, png in images:
        dimension = 0 if size >= 256 else size
        entries += _ICON_ENTRY.pack(dimension, dimension, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    return header + bytes(entries) + bytes(payload)


def build_ico() -> bytes:
    """Render every size and return the ICO file content."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    try:
        return pack_ico([(size, render_png(size)) for size in SIZES])
    finally:
        del app


def main(argv: Sequence[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(prog="gen_icon.py", description="Write the application icon.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="the .ico to write")
    args = parser.parse_args(argv)
    data = build_ico()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"wrote {args.output} ({len(data)} bytes, sizes {', '.join(map(str, SIZES))})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
