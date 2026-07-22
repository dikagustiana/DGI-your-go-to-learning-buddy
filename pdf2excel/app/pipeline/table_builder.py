"""Reconstruct a row/column grid from loose OCR tokens.

RapidOCR returns text fragments with bounding boxes but no table
structure, so structure is rebuilt geometrically:

  1. Rows: sort tokens by vertical center and group into Y-bands. A
     token joins the current band when its center is within half a
     median-token-height of the band's running center; otherwise a new
     row starts. This tolerates the slight baseline wobble of skewed
     scans without merging adjacent table rows.

  2. Columns: project every token's horizontal extent onto the X axis
     and build a coverage histogram. Maximal zero-coverage gaps wider
     than a threshold are column separators — the whitespace gutters of
     the table. This uses evidence from all rows at once, so a column
     that is empty in many rows is still discovered as long as any row
     populates it. Outlier-wide tokens (document titles, full-width
     header lines) are excluded from the histogram: they span the
     gutters and would otherwise erase real column boundaries. They are
     still placed into a cell afterwards, by their center.

  3. Cells: assign each token to the column containing its center;
     tokens sharing (row, column) are concatenated left-to-right with a
     space, and the cell confidence is the minimum of its parts (a cell
     is only as trustworthy as its worst fragment — finance tie-out
     bias: over-flag, never under-flag).

No table schema is assumed; each page yields whatever grid its tokens
support, and document-type grouping happens later at the UI level.
"""

from __future__ import annotations

import statistics

from app.pipeline.models import Cell, OCRToken


def group_rows(tokens: list[OCRToken], band_factor: float = 0.5) -> list[list[OCRToken]]:
    """Group tokens into rows by Y-band; rows and their tokens are sorted."""
    if not tokens:
        return []
    med_h = statistics.median(t.height for t in tokens)
    tol = max(med_h * band_factor, 1.0)

    rows: list[list[OCRToken]] = []
    centers: list[float] = []  # running mean center of each row
    for tok in sorted(tokens, key=lambda t: t.cy):
        if rows and abs(tok.cy - centers[-1]) <= tol:
            row = rows[-1]
            row.append(tok)
            centers[-1] = sum(t.cy for t in row) / len(row)
        else:
            rows.append([tok])
            centers.append(tok.cy)
    for row in rows:
        row.sort(key=lambda t: t.x0)
    return rows


def find_column_bounds(tokens: list[OCRToken], min_gap: float | None = None,
                       bin_px: int = 4,
                       gap_factor: float = 0.6) -> list[tuple[float, float]]:
    """Find column X-ranges from the whitespace gutters of the page."""
    if not tokens:
        return []
    x_min = min(t.x0 for t in tokens)
    x_max = max(t.x1 for t in tokens)
    if min_gap is None:
        # Gutters narrower than ~0.6 median token height are usually
        # just inter-word spacing, not column separators.
        med_h = statistics.median(t.height for t in tokens)
        min_gap = max(med_h * gap_factor, bin_px * 2)

    # Titles and full-width banners span several columns; keep them out
    # of the gutter evidence. 2.5x the median token width separates them
    # cleanly from ordinary cell content.
    med_w = statistics.median(t.x1 - t.x0 for t in tokens)
    body = [t for t in tokens if (t.x1 - t.x0) <= med_w * 2.5]
    if body:
        tokens = body

    n_bins = max(int((x_max - x_min) / bin_px) + 1, 1)
    coverage = [0] * n_bins
    for t in tokens:
        b0 = int((t.x0 - x_min) / bin_px)
        b1 = int((t.x1 - x_min) / bin_px)
        for b in range(max(b0, 0), min(b1, n_bins - 1) + 1):
            coverage[b] += 1

    # Split points = centers of zero-coverage runs wider than min_gap.
    splits: list[float] = []
    run_start = None
    for i, c in enumerate(coverage + [1]):  # sentinel closes a trailing run
        if c == 0 and run_start is None:
            run_start = i
        elif c != 0 and run_start is not None:
            width = (i - run_start) * bin_px
            if width >= min_gap:
                splits.append(x_min + (run_start + (i - run_start) / 2) * bin_px)
            run_start = None

    bounds: list[tuple[float, float]] = []
    left = x_min - 1
    for s in splits:
        bounds.append((left, s))
        left = s
    bounds.append((left, x_max + 1))
    return bounds


def build_grid(tokens: list[OCRToken],
               band_factor: float = 0.5,
               gap_factor: float = 0.6) -> list[list[Cell | None]]:
    """Full reconstruction: tokens -> rows -> columns -> cell grid.

    Cells carry provenance: their bbox is the union of the source
    token boxes, and their confidence is the MINIMUM of the fragments
    (a cell is only as trustworthy as its worst fragment).
    """
    rows = group_rows(tokens, band_factor=band_factor)
    if not rows:
        return []
    bounds = find_column_bounds(tokens, gap_factor=gap_factor)
    n_cols = len(bounds)

    def col_of(tok: OCRToken) -> int:
        for i, (lo, hi) in enumerate(bounds):
            if lo <= tok.cx < hi:
                return i
        return n_cols - 1

    grid: list[list[Cell | None]] = []
    for row in rows:
        buckets: dict[int, list[OCRToken]] = {}
        for tok in row:
            buckets.setdefault(col_of(tok), []).append(tok)
        cells: list[Cell | None] = []
        for c in range(n_cols):
            toks = buckets.get(c)
            if not toks:
                cells.append(None)
                continue
            toks.sort(key=lambda t: t.x0)
            text = " ".join(t.text for t in toks)
            conf = min(t.confidence for t in toks)
            bbox = (min(t.x0 for t in toks), min(t.y0 for t in toks),
                    max(t.x1 for t in toks), max(t.y1 for t in toks))
            cells.append(Cell.from_text(text, conf, bbox=bbox))
        grid.append(cells)
    return grid


def stability_flags(tokens: list[OCRToken],
                    grid: list[list[Cell | None]]) -> list[str]:
    """Cheap structural self-checks on the geometric reconstruction.

    The geometric builder is a CANDIDATE extraction, not ground truth.
    These flags mark pages where small parameter changes flip the
    structure — i.e. where the row-banding or column-gutter decision was
    marginal and a human should look. (A full multi-hypothesis builder
    is future work; these safety flags are the honest first step.)
    """
    flags: list[str] = []
    if not tokens or not grid:
        return flags

    n_rows = len(grid)
    n_cols = max((len(r) for r in grid), default=0)

    # Row banding: does a slightly tighter/looser Y tolerance change
    # the number of rows?
    for factor in (0.35, 0.65):
        alt = group_rows(tokens, band_factor=factor)
        if len(alt) != n_rows:
            flags.append("row-banding-unstable")
            break

    # Column gutters: does a slightly different gap threshold change
    # the number of columns?
    for factor in (0.45, 0.9):
        alt_bounds = find_column_bounds(tokens, gap_factor=factor)
        if len(alt_bounds) != n_cols:
            flags.append("column-gutter-unstable")
            break

    return flags
