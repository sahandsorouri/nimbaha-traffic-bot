#!/usr/bin/env python3.11
"""
Generate AppIcon.icns for Claude Usage Bar.

Renders a Big Sur-style rounded-square ("squircle") icon in Claude's coral with
a white usage ring (echoing the menu bar ring), at every size macOS wants, then
packs them into AppIcon.icns via `iconutil`.

    python3.11 make_icon.py        # writes AppIcon.icns next to this script
"""

from __future__ import annotations

import math
import shutil
import subprocess
import tempfile
from pathlib import Path

from AppKit import (
    NSBitmapImageRep,
    NSColor,
    NSGraphicsContext,
    NSBezierPath,
)
from Foundation import NSMakePoint, NSMakeRect, NSMakeSize

HERE = Path(__file__).resolve().parent
ICNS_PATH = HERE / "AppIcon.icns"

# Claude coral background; white ring at ~68% to evoke usage.
CORAL = (0.851, 0.459, 0.341, 1.0)  # ~ #D97757
RING_VALUE = 68.0


def _draw(size: int) -> NSBitmapImageRep:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    ctx = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(ctx)
    try:
        # Big Sur grid: content square inset ~10%, corner radius ~22.37% of it.
        inset = size * 0.10
        side = size - 2 * inset
        radius = side * 0.2237
        square = NSMakeRect(inset, inset, side, side)
        squircle = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            square, radius, radius
        )
        NSColor.colorWithCalibratedRed_green_blue_alpha_(*CORAL).setFill()
        squircle.fill()

        # Usage ring, centered.
        cx = cy = size / 2.0
        ring_radius = side * 0.30
        line = max(side * 0.085, 1.0)
        rect = NSMakeRect(
            cx - ring_radius, cy - ring_radius, ring_radius * 2, ring_radius * 2
        )

        track = NSBezierPath.bezierPathWithOvalInRect_(rect)
        track.setLineWidth_(line)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(1, 1, 1, 0.30).setStroke()
        track.stroke()

        start = 90.0
        end = 90.0 - 360.0 * (RING_VALUE / 100.0)
        arc = NSBezierPath.bezierPath()
        arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
            NSMakePoint(cx, cy), ring_radius, start, end, True
        )
        arc.setLineWidth_(line)
        arc.setLineCapStyle_(1)  # round cap
        NSColor.whiteColor().setStroke()
        arc.stroke()
    finally:
        NSGraphicsContext.restoreGraphicsState()
    return rep


def _write_png(rep: NSBitmapImageRep, path: Path) -> None:
    png = rep.representationUsingType_properties_(4, None)  # NSBitmapImageFileTypePNG
    png.writeToFile_atomically_(str(path), True)


def main() -> int:
    if shutil.which("iconutil") is None:
        raise SystemExit("iconutil not found (macOS required).")

    # iconset entries: (filename, pixel size)
    entries = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()
        cache: dict[int, NSBitmapImageRep] = {}
        for name, px in entries:
            rep = cache.get(px) or _draw(px)
            cache[px] = rep
            _write_png(rep, iconset / name)
        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS_PATH)],
            check=True,
        )
    print(f"Wrote {ICNS_PATH} ({ICNS_PATH.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
