"""Generate a synthetic image-only sample PDF that mimics the real corpus:

  * no text layer at all (pages are embedded scans, like the Canon
    iR3570/iR4570 output described in the diagnostics);
  * Indonesian number formatting (dot thousands, comma decimals);
  * page 1: portrait bank-statement table, correct orientation;
  * page 2: landscape table scanned into a portrait page, i.e. rotated
    90° — the auto-rotation path must fix it before OCR.

Usage:  python samples/make_sample.py [out.pdf]
"""

from __future__ import annotations

import io
import os
import sys

import fitz
from PIL import Image, ImageDraw, ImageFont

# Cross-platform monospace font lookup; falls back to Pillow's scalable
# built-in font when none of the system fonts exist.
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",  # Linux
    "C:/Windows/Fonts/consola.ttf",                          # Windows
    "C:/Windows/Fonts/cour.ttf",
    "/System/Library/Fonts/Menlo.ttc",                       # macOS
]


def load_font(size: int) -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)

STATEMENT_ROWS = [
    ("TANGGAL", "KETERANGAN", "MUTASI", "SALDO"),
    ("01/03/2025", "SALDO AWAL", "", "130.326.720"),
    ("02/03/2025", "SETORAN TUNAI", "25.000.000", "155.326.720"),
    ("03/03/2025", "BIAYA ADM", "4.488,00", "155.322.232"),
    ("05/03/2025", "TRF MASUK PT ABC", "192.240", "155.514.472"),
    ("07/03/2025", "PEMBAYARAN INV 4521", "12.750.500", "142.763.972"),
    ("10/03/2025", "KLIRING KELUAR", "1.000,-", "142.762.972"),
]

CLAIM_ROWS = [
    ("NO", "NO FAKTUR", "QTY", "NILAI KLAIM"),
    ("1", "FK-2025-0311", "24", "1.152.000"),
    ("2", "FK-2025-0317", "7", "336.000"),
    ("3", "FK-2025-0325", "150", "7.200.000"),
    ("4", "FK-2025-0330", "3", "144.000"),
]


def draw_table(rows, size=(2480, 3508), col_x=(150, 600, 1500, 2000),
               title="PT CONTOH SEJAHTERA - REKENING KORAN") -> Image.Image:
    """Render a table onto a white page image (defaults ~A4 at 300 DPI)."""
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    font = load_font(44)
    title_font = load_font(54)
    d.text((col_x[0], 150), title, fill="black", font=title_font)
    y = 320
    for row in rows:
        for x, text in zip(col_x, row):
            if text:
                d.text((x, y), text, fill="black", font=font)
        y += 90
    return img


def main(out_path: str = "sample_scanned.pdf") -> None:
    page1 = draw_table(STATEMENT_ROWS)

    # Landscape original, then rotated 90° clockwise into a portrait page
    # (the scanner-operator move that breaks naive OCR).
    landscape = draw_table(
        CLAIM_ROWS, size=(3508, 2480), col_x=(200, 800, 1900, 2500),
        title="DAFTAR KLAIM BARANG RUSAK (RBP)")
    page2 = landscape.rotate(-90, expand=True)

    doc = fitz.open()
    for img in (page1, page2):
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=85)
        page = doc.new_page(width=img.width * 72 / 300,
                            height=img.height * 72 / 300)
        page.insert_image(page.rect, stream=buf.getvalue())
    doc.save(out_path)
    doc.close()
    print(f"wrote {out_path}: 2 image-only pages (page 2 rotated 90°)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "sample_scanned.pdf")
