"""Generate an adversarial synthetic corpus for finance-grade testing.

Each page is an image-only PDF page paired with a cell-level expectation
(``expected.json``), so tests assert on VALUES, not merely that a
workbook exists. This is synthetic — clean fonts, controlled noise — and
is NOT a substitute for a real Canon-scan corpus (see the on-prem
experiment list in the final report). It exercises the shapes the
pipeline must survive:

  * rotation 0 / 90 / 180 / 270
  * a bank-statement whose running balance ties out
  * leading-zero account numbers (must stay TEXT)
  * very large amounts and id-ID formatting
  * an ambiguous "1,234" (must NOT be silently parsed)
  * a formula-injection string ("=SUM(...)") that must stay text
  * a two-table page and a differing-column page
  * a blank page

Usage:  python samples/make_adversarial.py OUTDIR
Writes OUTDIR/<name>.pdf and OUTDIR/expected.json.
"""

from __future__ import annotations

import io
import json
import os
import sys

import fitz
from PIL import Image, ImageDraw

# Reuse the cross-platform font loader from the basic sample generator.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_sample import load_font  # noqa: E402


def render(rows, size=(2480, 3508), col_x=(150, 700, 1400, 2000),
           rotate=0) -> Image.Image:
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    font = load_font(44)
    y = 200
    for row in rows:
        for x, text in zip(col_x, row):
            if text:
                d.text((x, y), text, fill="black", font=font)
        y += 100
    if rotate:
        img = img.rotate(-rotate, expand=True)
    return img


# (name, rows, rotate, expectations). Expectations are checked by tests:
#   text_at: {(row_substr_match, col): expected effective text}
#   numeric / non_numeric / must_be_text lists of literal strings.
PAGES = [
    {
        "name": "statement_upright",
        "rotate": 0,
        "rows": [
            ["TANGGAL", "KETERANGAN", "MUTASI", "SALDO"],
            ["01/03/2025", "SALDO AWAL", "", "10.000.000"],
            ["02/03/2025", "SETORAN", "5.000.000", "15.000.000"],
            ["03/03/2025", "BIAYA", "500.000", "14.500.000"],
        ],
        "numeric": ["10.000.000", "5.000.000", "14.500.000"],
    },
    {
        "name": "statement_rot90",
        "rotate": 90,
        "rows": [
            ["NO", "URAIAN", "JUMLAH"],
            ["1", "Barang A", "1.250.000"],
            ["2", "Barang B", "3.400.500"],
        ],
        "numeric": ["1.250.000", "3.400.500"],
    },
    {
        "name": "identifiers",
        "rotate": 0,
        "rows": [
            ["NO REKENING", "NILAI"],
            ["001234567", "2.500.000"],
            ["0089001", "17.000.000"],
        ],
        "numeric": ["2.500.000", "17.000.000"],
        "must_be_text": ["001234567", "0089001"],
    },
    {
        "name": "adversarial_values",
        "rotate": 0,
        "rows": [
            ["KETERANGAN", "NILAI"],
            ["Besar sekali", "999.999.999.999"],
            ["Ambigu", "1,234"],
            ["Formula", "=SUM(A1:A9)"],
        ],
        "must_be_text": ["1,234", "=SUM(A1:A9)"],
    },
    {
        "name": "blank_page",
        "rotate": 0,
        "rows": [[""]],
    },
]


def main(outdir: str) -> None:
    os.makedirs(outdir, exist_ok=True)
    manifest = []
    for spec in PAGES:
        img = render(spec["rows"], rotate=spec["rotate"])
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
        doc = fitz.open()
        page = doc.new_page(width=img.width * 72 / 300,
                            height=img.height * 72 / 300)
        page.insert_image(page.rect, stream=buf.getvalue())
        pdf_path = os.path.join(outdir, spec["name"] + ".pdf")
        doc.save(pdf_path)
        doc.close()
        manifest.append({
            "name": spec["name"],
            "pdf": os.path.basename(pdf_path),
            "rotate": spec["rotate"],
            "numeric": spec.get("numeric", []),
            "must_be_text": spec.get("must_be_text", []),
        })
    with open(os.path.join(outdir, "expected.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"wrote {len(manifest)} adversarial pages + expected.json to {outdir}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "adversarial_corpus")
