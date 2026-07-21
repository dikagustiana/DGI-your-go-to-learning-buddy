"""Excel export via openpyxl.

Layout per sheet:
  * Visible block: the reconstructed grid. Cells whose text parsed as an
    id-ID number are written as real numbers (so Excel can sum them);
    everything else is written as text.
  * Audit block: one hidden column per source column, offset to the
    right, holding the raw OCR string for every cell — including the
    numeric ones. Finance tie-out requirement: the parsed value must
    always be checkable against what the OCR actually read.
  * Low-confidence cells get an amber fill so reviewers can see at a
    glance what the QA pass flagged; cells corrected by a human during
    review get a green fill instead (and are never amber — the human
    correction supersedes the OCR confidence).

Layouts: "sheet_per_page" (default) or "merged_by_label" which
concatenates pages sharing a document-type label into one sheet,
separated by a page-marker row.
"""

from __future__ import annotations

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.config import PipelineConfig
from app.pipeline.models import PageResult

LOW_CONF_FILL = PatternFill("solid", start_color="FFF3CD")   # amber
EDITED_FILL = PatternFill("solid", start_color="D4EDDA")     # green
ERROR_FILL = PatternFill("solid", start_color="F8D7DA")      # red
RAW_HEADER_FONT = Font(italic=True, color="888888")


def _write_page_grid(ws, page: PageResult, start_row: int,
                     config: PipelineConfig) -> int:
    """Write one page's grid; returns the next free row index."""
    n_cols = page.n_cols
    raw_offset = n_cols + 2  # one blank spacer column between blocks

    if config.export_raw_columns and n_cols:
        for c in range(n_cols):
            cell = ws.cell(row=start_row, column=raw_offset + c + 1,
                           value=f"raw C{c + 1}")
            cell.font = RAW_HEADER_FONT
        header_used = 1
    else:
        header_used = 0

    r = start_row + header_used
    for row in page.grid:
        for c, cell_data in enumerate(row):
            if cell_data is None:
                continue
            target = ws.cell(row=r, column=c + 1)
            if cell_data.value is not None:
                target.value = float(cell_data.value)
            else:
                target.value = cell_data.raw
            if cell_data.edited:
                target.fill = EDITED_FILL
            elif cell_data.confidence < config.low_confidence_threshold:
                target.fill = LOW_CONF_FILL
            if config.export_raw_columns:
                ws.cell(row=r, column=raw_offset + c + 1, value=cell_data.raw)
        r += 1

    if config.export_raw_columns and n_cols:
        for c in range(n_cols):
            ws.column_dimensions[get_column_letter(raw_offset + c + 1)].hidden = True
    return r


def _safe_sheet_name(name: str, existing: set[str]) -> str:
    base = "".join(ch for ch in name if ch not in "[]:*?/\\").strip() or "Sheet"
    base = base[:28]
    candidate, i = base, 2
    while candidate in existing:
        candidate = f"{base}_{i}"
        i += 1
    existing.add(candidate)
    return candidate


def export_workbook(pages: list[PageResult], out_path: str,
                    config: PipelineConfig) -> None:
    wb = Workbook()
    wb.remove(wb.active)
    names: set[str] = set()

    if config.output_layout == "merged_by_label":
        groups: dict[str, list[PageResult]] = {}
        for p in pages:
            groups.setdefault(p.doc_type_label or "unlabelled", []).append(p)
        for label, group in groups.items():
            ws = wb.create_sheet(_safe_sheet_name(label, names))
            r = 1
            for page in sorted(group, key=lambda p: p.page_number):
                marker = ws.cell(row=r, column=1, value=f"— page {page.page_number} —")
                marker.font = Font(bold=True)
                if page.error:
                    ws.cell(row=r, column=2, value=f"ERROR: {page.error}").fill = ERROR_FILL
                r = _write_page_grid(ws, page, r + 1, config) + 1
    else:  # sheet_per_page
        for page in pages:
            title = f"p{page.page_number}"
            if page.doc_type_label:
                title += f" {page.doc_type_label}"
            ws = wb.create_sheet(_safe_sheet_name(title, names))
            if page.error:
                ws.cell(row=1, column=1, value=f"ERROR: {page.error}").fill = ERROR_FILL
                continue
            _write_page_grid(ws, page, 1, config)

    if not wb.sheetnames:  # openpyxl refuses to save an empty workbook
        wb.create_sheet("empty")
    wb.save(out_path)
