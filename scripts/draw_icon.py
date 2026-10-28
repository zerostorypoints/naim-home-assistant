"""Draw the integration icon: an original amplifier glyph in HiFiSync colours.

Usage: python scripts/draw_icon.py custom_components/naim_streaming/brand
Needs Pillow. Writes icon.png, icon@2x.png, dark_icon.png, dark_icon@2x.png.
"""

import math
import sys

from PIL import Image, ImageDraw

S = 2048  # supersampled canvas
BG_RAISED, BG_DEEP = "#241e16", "#0d0b08"
AMBER, AMBER_DEEP, AMBER_SOFT = "#e8a04a", "#ba7517", "#f3c98a"
INK_WARM, SIGNAL = "#f4ead2", "#80a8bf"


def draw(dark: bool) -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    chassis = "#3a3024" if dark else BG_RAISED
    edge = INK_WARM if dark else BG_DEEP
    # feet
    for x in (330, 1620):
        d.rounded_rectangle((x, 1440, x + 110, 1530), 28, fill=edge)
    # chassis
    d.rounded_rectangle((96, 560, 1952, 1480), 150, fill=chassis, outline=edge, width=40)
    # amber accent line along the top of the front panel
    d.rounded_rectangle((250, 660, 1800, 690), 15, fill=AMBER)
    # display
    d.rounded_rectangle((260, 820, 1080, 1320), 70, fill=BG_DEEP, outline=AMBER_DEEP, width=18)
    pts = []
    for i in range(0, 2881):
        x = 340 + i * (660 / 2880)
        env = math.sin(math.pi * i / 2880)
        y = 1070 - 150 * env * math.sin(i / 2880 * 4 * math.pi)
        pts.append((x, y))
    for x, y in pts:  # round brush along the path: smooth edges, round caps
        d.ellipse((x - 17, y - 17, x + 17, y + 17), fill=SIGNAL)
    # volume knob
    cx, cy, r = 1500, 1070, 270
    d.ellipse((cx - r - 30, cy - r - 30, cx + r + 30, cy + r + 30), fill=AMBER_DEEP)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=AMBER)
    d.ellipse((cx - r + 60, cy - r + 60, cx + r - 60, cy + r - 60), outline=AMBER_SOFT, width=14)
    a = math.radians(-135)  # pointer towards upper left
    d.line(
        (
            cx + 60 * math.cos(a),
            cy + 60 * math.sin(a),
            cx + (r - 40) * math.cos(a),
            cy + (r - 40) * math.sin(a),
        ),
        fill=BG_DEEP,
        width=44,
    )
    d.ellipse(
        (
            cx + (r - 40) * math.cos(a) - 22,
            cy + (r - 40) * math.sin(a) - 22,
            cx + (r - 40) * math.cos(a) + 22,
            cy + (r - 40) * math.sin(a) + 22,
        ),
        fill=BG_DEEP,
    )
    return im


def square_trim(im: Image.Image, size: int) -> Image.Image:
    box = im.getbbox()
    crop = im.crop(box)
    side = max(crop.size)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    return canvas.resize((size, size), Image.LANCZOS)


out = sys.argv[1]
for dark, prefix in ((False, ""), (True, "dark_")):
    base = draw(dark)
    square_trim(base, 256).save(f"{out}/{prefix}icon.png", optimize=True)
    square_trim(base, 512).save(f"{out}/{prefix}icon@2x.png", optimize=True)
