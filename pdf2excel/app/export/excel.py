"""Excel export via openpyxl.

Workbook layout (fixed order):

  Ringkasan   status DRAF/FINAL front and center, source-PDF identity,
              extraction provenance (app/engine/config versions), page
              counts, anomaly counts, and — for drafts — the exact
              reasons the workbook is not FINAL.
  <data>      one sheet per page, or pages merged per document-type
              label. Cells show the EFFECTIVE value (human correction
              if present, else OCR). Values that parsed unambiguously
              as id-ID numbers are real Excel numbers; identifiers,
              ambiguous strings and text stay strings.
  Audit       one row per populated cell: immutable OCR original,
              human correction, parsed value + kind + reason,
              confidence, editor identity/time, page review state,
              engine + config hash, source bounding box. This sheet is
              the audit trail — it replaces the old per-page hidden
              column blocks (whose per-page offsets could hide visible
              data on merged sheets — fixed by construction here).
  Masalah     machine-detected anomalies (page, cell, severity, plain
              explanation).

Safety rules:
  * Any text beginning with "=" is forced to a string literal so OCR
    noise can never become an executing Excel formula.
  * Numbers are written from parsed Decimals only when the parser
    classified them as money/integer (≤ 15 digits guaranteed by the
    parser) — identifiers, leading zeros and long digit runs stay text.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app import __version__ as APP_VERSION
from app.config import PipelineConfig
from app.export.policy import ExportEligibility, final_eligibility, status_label
from app.locale_id import KIND_INTEGER, KIND_MONEY
from app.pipeline.models import Cell, PageResult

LOW_CONF_FILL = PatternFill("solid", start_color="FFF3CD")   # amber
EDITED_FILL = PatternFill("solid", start_color="D4EDDA")     # green
ANOMALY_FILL = PatternFill("solid", start_color="F8D7DA")    # red
LEGACY_FILL = PatternFill("solid", start_color="E2E3E5")     # gray
ERROR_FILL = PatternFill("solid", start_color="F8D7DA")

DRAF_FONT = Font(bold=True, size=16, color="B02A37")
FINAL_FONT = Font(bold=True, size=16, color="0D6832")
HEADER_FONT = Font(bold=True)


def write_text(cell_obj, text: str) -> None:
    """Write a string that can never execute as a formula."""
    cell_obj.value = text
    if isinstance(text, str) and text.startswith("="):
        cell_obj.data_type = "s"


def _is_safe_number(cell: Cell) -> bool:
    return (cell.value is not None
            and cell.parse_kind in (KIND_MONEY, KIND_INTEGER))


def _write_cell(ws, row: int, col: int, cell: Cell,
                threshold: float, anomaly_cells: set[tuple[int, int]],
                grid_row: int, grid_col: int) -> None:
    target = ws.cell(row=row, column=col)
    if _is_safe_number(cell):
        # Parser caps at 15 significant digits, so float is exact here.
        target.value = float(cell.value)
    else:
        write_text(target, cell.effective_text)

    if cell.edited:
        target.fill = EDITED_FILL
    elif (grid_row, grid_col) in anomaly_cells:
        target.fill = ANOMALY_FILL
    elif cell.legacy_audit_incomplete:
        target.fill = LEGACY_FILL
    elif cell.confidence < threshold:
        target.fill = LOW_CONF_FILL


def _write_page_grid(ws, page: PageResult, start_row: int,
                     config: PipelineConfig) -> int:
    """Write one page's effective grid; returns the next free row."""
    anomaly_cells = {(a.row, a.col) for a in page.anomalies
                     if a.row is not None and a.col is not None}
    r = start_row
    for gr, row in enumerate(page.grid):
        for gc, cell_data in enumerate(row):
            if cell_data is None:
                continue
            _write_cell(ws, r, gc + 1, cell_data,
                        config.low_confidence_threshold, anomaly_cells,
                        gr, gc)
        r += 1
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


# ------------------------------------------------------------- Ringkasan

def _write_summary(ws, pages: list[PageResult], eligibility: ExportEligibility,
                   config: PipelineConfig, source_pdf: str | None) -> None:
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 90

    status = ws.cell(row=1, column=1, value=status_label(eligibility.final_ok))
    status.font = FINAL_FONT if eligibility.final_ok else DRAF_FONT

    if not eligibility.final_ok:
        note = ws.cell(
            row=2, column=1,
            value="Angka dalam file ini BELUM selesai diperiksa manusia. "
                  "Jangan dipakai sebagai laporan final.")
        note.font = Font(italic=True, color="B02A37")

    rows: list[tuple[str, str]] = []
    if source_pdf:
        rows.append(("Sumber PDF", os.path.basename(source_pdf)))
    rows.append(("Diekspor pada (UTC)",
                 datetime.now(timezone.utc).isoformat(timespec="seconds")))
    rows.append(("Aplikasi", f"PDF ke Excel v{APP_VERSION}"))
    engines = sorted({p.engine for p in pages if p.engine})
    rows.append(("Mesin pembaca", ", ".join(engines) or "-"))
    hashes = sorted({p.config_hash for p in pages if p.config_hash})
    rows.append(("Kode konfigurasi ekstraksi", ", ".join(hashes) or "-"))
    if len(hashes) > 1:
        rows.append(("PERHATIAN", "Halaman-halaman diekstrak dengan "
                                  "konfigurasi/versi BERBEDA — lihat kolom "
                                  "config di sheet Audit."))
    n_err = sum(1 for p in pages if p.error)
    n_rev = sum(1 for p in pages if p.reviewed and not p.error)
    rows.append(("Jumlah halaman", str(len(pages))))
    rows.append(("Sudah diperiksa manusia", str(n_rev)))
    rows.append(("Halaman gagal dibaca", str(n_err)))
    n_blocker = sum(len(p.blocker_anomalies()) for p in pages)
    n_warn = sum(len(p.anomalies) for p in pages) - n_blocker
    rows.append(("Masalah serius (blocker)", str(n_blocker)))
    rows.append(("Peringatan", str(n_warn)))
    n_legacy = sum(1 for p in pages for row in p.grid for c in row
                   if c is not None and c.legacy_audit_incomplete)
    if n_legacy:
        rows.append(("Sel tanpa OCR asli (sesi lama)",
                     f"{n_legacy} — teks asli hasil OCR hilang karena "
                     "diedit di versi aplikasi lama."))

    r = 4
    for key, value in rows:
        ws.cell(row=r, column=1, value=key).font = HEADER_FONT
        write_text(ws.cell(row=r, column=2), value)
        r += 1

    if eligibility.reasons:
        r += 1
        ws.cell(row=r, column=1, value="Belum FINAL karena:").font = HEADER_FONT
        for reason in eligibility.reasons:
            r += 1
            cell = ws.cell(row=r, column=2, value=reason)
            cell.alignment = Alignment(wrap_text=True)


# ----------------------------------------------------------------- Audit

AUDIT_HEADERS = [
    "halaman", "baris", "kolom", "jenis dokumen",
    "OCR asli", "koreksi manusia", "nilai terparse", "tipe parse",
    "alasan parse", "keyakinan OCR", "diedit", "diedit pada", "pemeriksa",
    "halaman diperiksa", "diperiksa pada", "mesin", "config",
    "bbox (px @dpi)", "audit lama tidak lengkap",
]


def _write_audit(ws, pages: list[PageResult]) -> None:
    for c, header in enumerate(AUDIT_HEADERS, start=1):
        cell = ws.cell(row=1, column=c, value=header)
        cell.font = HEADER_FONT
    ws.freeze_panes = "A2"

    r = 2
    for page in pages:
        for gr, row in enumerate(page.grid):
            for gc, cell_data in enumerate(row):
                if cell_data is None:
                    continue
                bbox = ""
                if cell_data.bbox:
                    coords = ",".join(str(int(v)) for v in cell_data.bbox)
                    bbox = f"{coords} @{page.dpi}dpi"
                values = [
                    page.page_number, gr + 1, gc + 1, page.doc_type_label,
                    cell_data.ocr_original,
                    cell_data.corrected_text,
                    (str(cell_data.value)
                     if cell_data.value is not None else None),
                    cell_data.parse_kind, cell_data.parse_reason,
                    round(cell_data.confidence, 3),
                    "ya" if cell_data.edited else "",
                    cell_data.edited_at, cell_data.reviewer,
                    "ya" if page.reviewed else "",
                    page.reviewed_at, page.engine, page.config_hash,
                    bbox,
                    "ya" if cell_data.legacy_audit_incomplete else "",
                ]
                for c, v in enumerate(values, start=1):
                    if isinstance(v, str):
                        write_text(ws.cell(row=r, column=c), v)
                    else:
                        ws.cell(row=r, column=c, value=v)
                r += 1
    for c in range(1, len(AUDIT_HEADERS) + 1):
        ws.column_dimensions[get_column_letter(c)].width = 16


def _write_anomalies(ws, pages: list[PageResult]) -> None:
    headers = ["halaman", "baris", "kolom", "tingkat", "kode", "penjelasan"]
    for c, header in enumerate(headers, start=1):
        ws.cell(row=1, column=c, value=header).font = HEADER_FONT
    ws.freeze_panes = "A2"
    ws.column_dimensions["F"].width = 80

    r = 2
    for page in pages:
        if page.error:
            write_text(ws.cell(row=r, column=6),
                       f"Halaman gagal dibaca: {page.error}")
            ws.cell(row=r, column=1, value=page.page_number)
            ws.cell(row=r, column=4, value="blocker")
            ws.cell(row=r, column=5, value="page-error")
            ws.cell(row=r, column=1).fill = ERROR_FILL
            r += 1
        for a in page.anomalies:
            ws.cell(row=r, column=1, value=page.page_number)
            ws.cell(row=r, column=2,
                    value=a.row + 1 if a.row is not None else None)
            ws.cell(row=r, column=3,
                    value=a.col + 1 if a.col is not None else None)
            ws.cell(row=r, column=4, value=a.severity)
            ws.cell(row=r, column=5, value=a.code)
            write_text(ws.cell(row=r, column=6), a.message)
            r += 1


# ------------------------------------------------------------- workbook

def export_workbook(pages: list[PageResult], out_path: str,
                    config: PipelineConfig,
                    source_pdf: str | None = None,
                    eligibility: ExportEligibility | None = None) -> None:
    if eligibility is None:
        eligibility = final_eligibility(pages)

    wb = Workbook()
    wb.remove(wb.active)
    names: set[str] = set()

    summary = wb.create_sheet(_safe_sheet_name("Ringkasan", names))
    _write_summary(summary, pages, eligibility, config, source_pdf)

    if config.output_layout == "merged_by_label":
        groups: dict[str, list[PageResult]] = {}
        for p in pages:
            groups.setdefault(p.doc_type_label or "tanpa-jenis", []).append(p)
        for label, group in groups.items():
            ws = wb.create_sheet(_safe_sheet_name(label, names))
            r = 1
            for page in sorted(group, key=lambda p: p.page_number):
                marker = ws.cell(row=r, column=1,
                                 value=f"— halaman {page.page_number} —")
                marker.font = HEADER_FONT
                if page.error:
                    ws.cell(row=r, column=2,
                            value=f"GAGAL: {page.error}").fill = ERROR_FILL
                r = _write_page_grid(ws, page, r + 1, config) + 1
    else:  # sheet_per_page
        for page in pages:
            title = f"p{page.page_number}"
            if page.doc_type_label:
                title += f" {page.doc_type_label}"
            ws = wb.create_sheet(_safe_sheet_name(title, names))
            if page.error:
                ws.cell(row=1, column=1,
                        value=f"GAGAL DIBACA: {page.error}").fill = ERROR_FILL
                continue
            _write_page_grid(ws, page, 1, config)

    if config.export_raw_columns:
        _write_audit(wb.create_sheet(_safe_sheet_name("Audit", names)), pages)
    _write_anomalies(
        wb.create_sheet(_safe_sheet_name("Masalah", names)), pages)

    wb.save(out_path)
