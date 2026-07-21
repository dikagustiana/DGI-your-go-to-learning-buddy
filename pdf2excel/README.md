# pdf2excel — offline scanned-PDF → Excel converter

Converts scanned (image-only) PDF documents — Indonesian corporate finance
papers: rekening koran, faktur, debit/credit notes, RBP listings — into
clean Excel workbooks. Runs **100% locally**: no cloud OCR, no external API
calls anywhere in the OCR/extraction path. All models run on-device.

## Status: milestone 2 (GUI shell) ✅

| # | Milestone | Status |
|---|-----------|--------|
| 1 | Core pipeline: load → detect scanned → rasterize 300 DPI → auto-rotate → RapidOCR → grid reconstruction → .xlsx | **done** |
| 2 | PySide6 shell: open file, batch run in worker thread, page list | **done** |
| 3 | Review/QA view: image + editable table, confidence highlighting, rotation override, doc-type labels | pending |
| 4 | Export options + resumable session persistence | pending |
| 5 | PaddleOCR PP-StructureV3 engine (optional) | pending (interface wired) |
| 6 | PyInstaller packaging | pending |

## Setup

Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

RapidOCR's models ship inside the wheel — no downloads, works offline
immediately.

Optional extras:

* **Tesseract OSD** for faster orientation detection: install a system
  `tesseract` binary and `pip install pytesseract`. Without it the app
  falls back to a built-in OCR-probe heuristic (slower per page, no
  extra dependencies).
* **PaddleOCR PP-StructureV3** (milestone 5, native table structure):
  `pip install paddleocr paddlepaddle` — large download, models fetched on
  first run. Installed via the wheel, **not** by cloning the PaddleOCR
  repo (the `ppstructure/` directory there is the deprecated V2).

## Usage

### GUI

```bash
python -m app
```

Open PDF… → Run OCR → watch pages fill in live (each list entry shows
the reconstructed grid size and any auto-applied rotation) → click a
page to see its corrected image and extracted table → Export…. OCR runs
in a background thread; the Cancel button stops after the current page.
Engine, DPI, default rotation, and export layout sit in the toolbar; the
PaddleOCR engine appears greyed-out with an install hint until its
package is installed.

### Headless CLI

```bash
# What is this file? (page count, scanned vs native, engine availability)
python -m app inspect statement.pdf

# Convert. Auto-detects per-page rotation, OCRs at 300 DPI, exports xlsx.
python -m app convert statement.pdf -o statement.xlsx

# Options
python -m app convert statement.pdf -o out.xlsx \
    --pages 1-20            `# 1-based page range` \
    --rotation 270          `# force a rotation instead of auto-detect` \
    --dpi 300 \
    --engine rapidocr \
    --layout sheet_per_page  # or merged_by_label
```

`python -m app` with no arguments will launch the GUI from milestone 2.

### Try it on a synthetic sample

```bash
python samples/make_sample.py sample.pdf   # 2 image-only pages, page 2 rotated 90°
python -m app convert sample.pdf -o sample.xlsx
```

## What the output looks like

* One sheet per page (default). Cells that parse as **id-ID numbers**
  (dot = thousands, comma = decimals: `130.326.720`, `4.488,00`) are
  written as real Excel numbers; everything else stays text.
* A **hidden column block** on the right of each sheet preserves the raw
  OCR string for every cell — unhide it to audit any parsed value.
* Cells below the OCR-confidence threshold get an amber fill.
* Text that doesn't unambiguously parse as an id-ID number is **kept as
  text**, never guessed into a number. US-format `1,234.56` is refused
  rather than silently misparsed.

**OCR output is never to be trusted blindly for finance tie-out.** The
QA review view (milestone 3) blocks export until a human has had the
chance to check flagged cells against the page image.

## Running tests

```bash
python -m pytest tests/
```

## Packaging

PyInstaller packaging lands in milestone 6 and will be documented here
(`pyinstaller` spec + build command for a Windows `.exe`).

## Documentation

See [ARCHITECTURE.md](ARCHITECTURE.md) for the pipeline design, the
orientation-detection algorithm, and the table-reconstruction algorithm.
