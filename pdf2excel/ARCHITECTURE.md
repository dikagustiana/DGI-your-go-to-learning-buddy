# Architecture

```
app/
├── __main__.py            CLI entry: GUI (no args) / inspect / convert / export
├── config.py              PipelineConfig — every knob the UI will expose
├── locale_id.py           id-ID number parsing (dot=thousands, comma=decimal)
├── session.py             SessionStore — resumable per-page persistence (SQLite)
├── pipeline/
│   ├── models.py          OCRToken / Cell / PageResult (+ JSON round-trip)
│   ├── pdf_loader.py      PyMuPDF: scanned-vs-native detection, 300 DPI raster
│   ├── orientation.py     per-page rotation detection (OSD → native → heuristic)
│   ├── table_builder.py   tokens + bboxes → row/column grid
│   ├── html_table.py      PP-StructureV3 pred_html → text grid (spans resolved)
│   ├── runner.py          per-page + whole-PDF orchestration (Qt-free)
│   └── engines/
│       ├── base.py        OCREngine interface + EngineUnavailableError
│       ├── rapidocr_engine.py   default engine (tokens only)
│       └── paddle_engine.py     PP-StructureV3 (optional, native tables)
├── gui/
│   ├── main_window.py     MainWindow: toolbar, page list, review, statusbar
│   ├── review_view.py     QA view: image + editable table + rotation/label
│   ├── worker.py          OcrWorker (batch) + SinglePageWorker (re-OCR)
│   └── qt_utils.py        numpy → QPixmap
├── export/
│   └── excel.py           openpyxl export: parsed values + hidden raw block
tests/                     unit tests (locale, table builder, html tables,
                           session store, offscreen GUI)
samples/make_sample.py     synthetic image-only sample PDF generator
launcher.py                PyInstaller entry point (= python -m app)
pdf2excel.spec             PyInstaller build spec (GUI + CLI executables)
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
`is_available() == False` (via `find_spec`, never a real import — the
paddle import chain takes seconds and probes the network) and the UI
greys them out with the hint — nothing crashes on import. `use_cls=False`
exists specifically for the orientation detector's flip stage;
`detect_orientation` lets an engine answer the whole question natively.

### PP-StructureV3 engine (`engines/paddle_engine.py`)

Optional, `pip install paddlepaddle paddleocr "paddlex[ocr]"`. Three
class-level singleton models (loading takes seconds):

* **PPStructureV3** pipeline for `ocr_table`: returns real HTML tables
  (`table_res_list[].pred_html`); `html_table.py` resolves
  colspan/rowspan into the rectangular grid (merged cells put text in
  the top-left slot, None in shadowed slots). Multiple tables on a page
  stack with a blank separator row. Pages with no table region fall
  back to the geometric `table_builder` over the pipeline's own OCR
  tokens. Doc-orientation/unwarping submodules are disabled — the
  pipeline pre-rotates.
* **PaddleOCR** (PP-OCRv5) for `ocr_tokens` — used by the fallback path
  and available to the orientation heuristic.
* **PP-LCNet_x1_0_doc_ori** for `detect_orientation`: the classifier
  label is the page's current clockwise rotation (verified
  empirically), so the correction is `(360 − label) % 360`; confidence
  < 0.6 falls through to the generic heuristic.

Cell confidence: the structure model does not score cells, so each cell
is matched back to the overall OCR tokens — exact text match, then
space-insensitive, then substring containment (tokens ≥ 3 chars) taking
the **minimum** matched score; unmatched cells get a conservative 0.75
(below the 0.80 review threshold, i.e. flagged amber by default).
PaddleX expects BGR arrays; channels are reversed at every boundary.

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
on window close. `SinglePageWorker` follows the same pattern for the QA
view's per-page re-OCR (rotation forced, `rotation_source="manual"`).

### Review/QA view (`gui/review_view.py`)

The QA pass is a hard requirement: OCR drops/misreads digits (observed
`192.240` → `92.240`), so nothing is trusted or exported unchecked.

* The view binds directly to the page's `PageResult` and mutates it in
  place; every user action emits `result_changed` so the main window
  refreshes the page list and (milestone 4) the session store persists.
* **Cell edits** re-parse through `locale_id` immediately, set
  `edited=True`, and recolor green. Amber = confidence below threshold;
  green (human-verified) supersedes amber, both in the UI and in the
  Excel export fills. Editing an empty slot creates a `Cell` with
  confidence 1.0. Human edits are never silently discarded — batch
  re-runs and per-page re-OCR both confirm first.
* **Rotation override** decouples image from grid: the image re-renders
  immediately at the chosen angle, a stale banner appears because the
  grid still reflects the extraction angle, and the re-OCR button sends
  `request_reocr(page, rotation)` to the main window. After a re-run the
  doc-type label is preserved but `reviewed` resets — a new extraction
  has not been checked by anyone.
* **Export gate**: the main window warns (default No) when exporting
  while non-error pages remain unreviewed, listing the page numbers.

### Session persistence (`session.py`)

SQLite (WAL mode), one file next to the PDF: `statement.pdf` →
`statement.pdf.p2x`. Two tables: `meta` (schema version, pipeline
config as JSON) and `pages` (one JSON `PageResult` per page, upserted
atomically). SQLite over a JSON blob because writes are incremental —
one page at a time, hundreds of times per session — and a crash
mid-write must not corrupt reviewed work; keeping the file next to the
PDF means it travels with the document and needs no registry.

Write points — everything is persisted the moment it exists:
* batch OCR: `runner.process_pdf(on_page=…)` saves each page as it
  completes (CLI and GUI both), so cancel/crash keeps finished pages;
* every `result_changed` from the QA view (cell edit, label, reviewed);
* every per-page re-OCR result.

On open, an existing non-empty session triggers a resume prompt
(pages/reviewed counts from `summary()`, which uses `json_extract` —
no full deserialization). "No" clears the stored pages. If the store
can't be opened (read-only dir), the GUI warns once and runs without
persistence instead of crashing. A session written by a newer schema
version is refused (`SessionError`) rather than silently mangled.

Threading: the store is touched only from the UI thread (worker results
arrive via queued signals) or the single CLI thread — one connection,
no cross-thread SQLite use. `Cell`/`PageResult` round-trip via
`to_dict`/`from_dict` (Decimals as strings), so nothing numeric loses
precision in storage.

### Export options

The GUI Export… button opens `gui/export_dialog.py`: sheet layout
(per page / merged by label), include/omit the hidden raw-OCR audit
columns, and "export only reviewed pages". Reviewed-only bypasses the
unreviewed-pages warning gate — it exports exactly the human-checked
subset. The CLI equivalent is `python -m app export input.pdf -o out
[--layout …] [--no-raw] [--reviewed-only]`, which reads the session and
never re-runs OCR.

### Packaging (`pdf2excel.spec`)

One PyInstaller Analysis over `launcher.py` (equivalent to
`python -m app`), two EXEs sharing one COLLECT folder: `pdf2excel`
(windowed) and `pdf2excel-cli` (console). One-folder mode because Qt +
onnxruntime in a one-file binary re-unpack on every launch. RapidOCR's
ONNX models are wheel data files, collected explicitly with
`collect_data_files("rapidocr_onnxruntime")` — this is what makes the
frozen app work offline with no model downloads.

paddle/paddleocr/paddlex are hard-excluded: PyInstaller traces the lazy
imports inside `paddle_engine.py`, so without the exclude every build
made on a paddle-equipped dev machine would ship the multi-gigabyte
stack. Inside the frozen app `find_spec("paddle")` returns None, so the
engine reports unavailable and the GUI greys it out — the same graceful
path as a source install without paddle.

### Excel export (`export/excel.py`)

Per sheet: visible grid (numbers as numbers, text as text), a **hidden**
raw-string column block offset to the right (audit requirement), amber
fill on low-confidence cells, red marker rows for pages that failed.
Layouts: `sheet_per_page` or `merged_by_label` (pages grouped by
document-type label, separated by page-marker rows).
