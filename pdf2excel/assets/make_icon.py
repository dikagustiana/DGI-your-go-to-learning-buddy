"""Generate the app icon (icon.ico + icon.png).

Regenerate with:  python assets/make_icon.py

Design: high-contrast, legible at 16px for reduced eyesight — a red
page (PDF) with an arrow to a green sheet (Excel). No text at small
sizes; text renders poorly under 32px.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

PDF_RED = (198, 45, 45)
XLS_GREEN = (16, 124, 65)
ARROW = (40, 40, 40)
WHITE = (255, 255, 255)


def draw_base(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 512  # design units

    def r(x):
        return int(round(x * s))

    # red PDF page, top-left
    d.rounded_rectangle([r(40), r(60), r(250), r(330)],
                        radius=r(28), fill=PDF_RED)
    # folded corner
    d.polygon([(r(250 - 60), r(60)), (r(250), r(60 + 60)),
               (r(250 - 60), r(60 + 60))], fill=WHITE)
    # text lines on the page
    for i in range(3):
        y = r(150 + i * 50)
        d.rounded_rectangle([r(75), y, r(215), y + r(22)],
                            radius=r(11), fill=WHITE)

    # green Excel sheet, bottom-right
    d.rounded_rectangle([r(262), r(182), r(472), r(452)],
                        radius=r(28), fill=XLS_GREEN)
    # grid lines
    for i in range(1, 3):
        x = r(262 + i * 70)
        d.rectangle([x, r(220), x + r(10), r(415)], fill=WHITE)
    for i in range(1, 3):
        y = r(182 + 40 + i * 75)
        d.rectangle([r(295), y, r(440), y + r(10)], fill=WHITE)

    # bold arrow from page to sheet
    d.line([(r(120), r(390)), (r(230), r(430))], fill=ARROW, width=r(38))
    d.polygon([(r(285), r(447)), (r(205), r(470)), (r(225), r(392))],
              fill=ARROW)
    return img


def main() -> None:
    base = draw_base(512)
    base.save(os.path.join(HERE, "icon.png"))
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base.save(os.path.join(HERE, "icon.ico"),
              sizes=[(n, n) for n in sizes])
    print("wrote icon.png + icon.ico", sizes)


if __name__ == "__main__":
    main()
