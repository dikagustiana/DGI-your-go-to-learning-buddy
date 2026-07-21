# Architecture

```
app/
├── __main__.py            CLI entry (GUI attaches here in milestone 2)
├── config.py              PipelineConfig — every knob the UI will expose
├── locale_id.py           id-ID number parsing (dot=thousands, comma=decimal)
├── pipeline/
│   ├── models.py          OCRToken / Cell / PageResult (+ JSON round-trip)
│   ├── pdf_loader.py      PyMuPDF: scanned-vs-native detection, 300 DPI raster
│   ├── orientation.py     per-page rotation detection (OSD → OCR heuristic)
│   ├── table_builder.py   tokens + bboxes → row/column grid
│   ├── runner.py          per-page + whole-PDF orchestration (Qt-free)
│   └── engines/
│       ├── base.py        OCREngine interface + EngineUnavailableError
│       ├── rapidocr_engine.py   default engine (tokens only)
│       └── paddle_engine.py     PP-StructureV3 (optional, native tables)
├── gui/
│   ├── main_window.py     MainWindow: toolbar, page list, preview, statusbar
│   ├── worker.py          OcrWorker: pipeline in a QThread, per-page signals
│   └── qt_utils.py        numpy → QPixmap
├── export/
│   └── excel.py           openpyxl export: parsed values + hidden raw block
tests/                     unit tests (locale, table builder)
samples/make_sample.py     synthetic image-only sample PDF generator
```

## Design decisions

### PDF rasterization: PyMuPDF, not pdf2image+poppler

Single pip dependency, no system poppler binaries, arbitrary-DPI
in-process rendering, and the same library provides text-layer detection
(`page.get_text`). This also keeps PyInstaller packaging simple — no
bundling of external executables.

Rendering is fixed at **300 DPI** by default; 150 DPI was measured to be
too noisy for dense scanned tables.

### Scanned vs native detection

`inspect_pdf` counts text-layer characters across pages. More than ~25
chars per page on average ⇒ treated as native; the CLI warns (and the GUI
will offer a skip-OCR direct-parse path). The sample corpus (Canon
iR3570/iR4570 scans, `Subject: Image`) has zero.

### Orientation detection (`pipeline/orientation.py`)

Pages are frequently landscape tables scanned into portrait (rotated
90°), and OCR on the un-rotated image is garbage. Order of attempts:

1. **Tesseract OSD** (`--psm 0`) via pytesseract — only if a system
   tesseract exists; never required.
2. **Two-stage OCR heuristic** (always available). The naive approach —
   "OCR at 0/90/180/270, keep the highest text score" — **does not
   work**: RapidOCR reads vertical lines (tall crops are rotated
   internally before recognition) and its angle classifier silently
   fixes upside-down lines, so all four rotations score almost
   identically (measured spread < 3%). Instead:
   - **Axis** — OCR once at 0° on a downscaled probe (≤1200 px):
     if the confidence-weighted text volume lives in landscape boxes,
     the page is 0-or-180; if in portrait (tall) boxes, it is 90-or-270.
   - **Flip** — OCR both candidates *with the angle classifier off*:
     only right-way-up text recognizes confidently; upside-down text
     degrades to low-confidence garbage. Measured margin ≈ 30× (e.g.
     305.7 vs 9.9), so the decision is robust.

   Cost: 3 probe passes on a downscaled image, cheap relative to the one
   full-resolution pass that follows.

The GUI adds a manual per-page override; `PageResult.rotation_source`
records `auto` / `manual` / `forced` for the audit trail.

### Table reconstruction (`pipeline/table_builder.py`)

RapidOCR returns loose tokens with bounding boxes; structure is rebuilt
geometrically:

1. **Rows** — sort by vertical center, group into Y-bands with tolerance
   = ½ × median token height (running band center absorbs baseline
   wobble from skewed scans without merging adjacent rows).
2. **Columns** — project all token X-extents into a coverage histogram;
   maximal zero-coverage runs wider than ~0.6 × median token height are
   column gutters. Evidence is pooled across all rows, so sparsely
   populated columns are still found. Outlier-wide tokens (> 2.5 × the
   median token width — titles, full-width banners) are excluded from
   the histogram because they span gutters and would erase real column
   boundaries; they are still assigned to a cell afterwards.
3. **Cells** — token → column by center-x; tokens sharing (row, col)
   concatenate left-to-right. Cell confidence = **minimum** of its
   fragments: a cell is only as trustworthy as its worst fragment
   (finance bias: over-flag, never under-flag).

No table schema is assumed anywhere — a page yields whatever grid its
tokens support, and document-type grouping is a per-page user label.

### id-ID parsing (`locale_id.py`)

Dot = thousands, comma = decimal. Handles currency prefixes (`Rp`,
`IDR`), accounting negatives `(1.234,56)`, trailing-minus, the `",-"`
suffix (⇒ `,00`), OCR noise (trailing `:` `;` `|`, quotes, spaces inside
digit groups). Deliberately conservative: anything ambiguous — broken
grouping, US-format `1,234.56`, dates — returns *not a number* and stays
text. Every `Cell` stores both the raw OCR string and the parsed
`Decimal`; the raw string is exported alongside the value.

### Engine interface (`pipeline/engines/`)

```python
class OCREngine:
    supports_table_structure: bool
    @classmethod is_available()          # cheap import check, never crashes
    @classmethod unavailable_hint()      # UI tooltip text
    ocr_tokens(image, use_cls=True)      # loose tokens
    ocr_table(image) -> grid | None      # native structure, if supported
```

`runner.process_page` prefers `ocr_table` when the engine supports it
(PP-StructureV3) and falls back to `ocr_tokens` + `table_builder`
(RapidOCR). Engines whose packages are missing report
`is_available() == False` and the UI greys them out with the hint —
nothing crashes on import. `use_cls=False` exists specifically for the
orientation detector's flip stage.

### Threading model

The pipeline (`app.pipeline.*`) is deliberately Qt-free; the CLI drives
it with plain callables. The GUI wraps it in `gui/worker.py`:
`OcrWorker` is a `QObject` moved to a `QThread`; it loads the engine and
loops pages off the UI thread, emitting `progress(done, total, msg)`,
`page_done(PageResult)` (so the page list fills in live during a
150-page run), and `finished(results, was_cancelled)`. Cancellation is
cooperative — a flag checked between pages, so the in-flight page
completes and no partial state is left behind. Per-page exceptions
become error-marked `PageResult`s instead of killing the batch; only
setup failures (bad file, missing engine) abort via `failed(str)`.

The main window disables Run/Export/config widgets while a batch runs,
re-renders the preview of whichever page is selected as its result
arrives, and tears the thread down with `quit()`/`wait()` on finish and
on window close.

### Session persistence (milestone 4)

All pipeline datatypes (`Cell`, `PageResult`) already round-trip through
`to_dict`/`from_dict`, so the session store (SQLite) can persist per-page
results — including human edits, review status, and doc-type labels —
without any additional serialization work.

### Excel export (`export/excel.py`)

Per sheet: visible grid (numbers as numbers, text as text), a **hidden**
raw-string column block offset to the right (audit requirement), amber
fill on low-confidence cells, red marker rows for pages that failed.
Layouts: `sheet_per_page` or `merged_by_label` (pages grouped by
document-type label, separated by page-marker rows).
