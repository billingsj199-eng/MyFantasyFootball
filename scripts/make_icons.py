# Rasterize the MFF manifest SVG logo (amber bar chart + trend line on #0f0f1a)
# to PNG app icons. Draws at 4x supersample then downscales for clean edges.
from PIL import Image, ImageDraw

BASE = 48.0  # SVG viewBox units
AMBER = (245, 158, 11)
BG = (15, 15, 26)  # #0f0f1a


def blend(fg, bg, o):
    return tuple(round(f * o + b * (1 - o)) for f, b in zip(fg, bg))


def draw_icon(px):
    ss = 4  # supersample factor
    S = px * ss
    k = S / BASE  # svg-unit -> pixel scale
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # background rounded rect (rx=8)
    d.rounded_rectangle([0, 0, S - 1, S - 1], radius=8 * k, fill=BG)

    # bars: (x, y, w, h, opacity), rx=1.5
    bars = [
        (8, 32, 7, 9, 0.3),
        (17, 25, 7, 16, 0.5),
        (26, 17, 7, 24, 0.7),
        (35, 9, 7, 32, 1.0),
    ]
    for x, y, w, h, o in bars:
        d.rounded_rectangle(
            [x * k, y * k, (x + w) * k, (y + h) * k],
            radius=1.5 * k,
            fill=blend(AMBER, BG, o),
        )

    # trend polyline, stroke-width 2, round caps
    pts = [(11.5, 29), (20.5, 22), (29.5, 14), (38.5, 6)]
    lw = 2 * k
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        d.line([x1 * k, y1 * k, x2 * k, y2 * k], fill=AMBER, width=round(lw))
    for x, y in pts:  # round joints/caps
        r = lw / 2
        d.ellipse([x * k - r, y * k - r, x * k + r, y * k + r], fill=AMBER)

    # end-point dot r=3
    r = 3 * k
    cx, cy = 38.5 * k, 6 * k
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=AMBER)

    return img.resize((px, px), Image.LANCZOS)


import os

out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "icons")
os.makedirs(out, exist_ok=True)
for px in (180, 192, 512):
    draw_icon(px).save(os.path.join(out, f"icon-{px}.png"))
    print(f"icon-{px}.png written")
