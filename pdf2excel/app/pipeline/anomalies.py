"""Anomaly detection — reasons to distrust a page beyond OCR confidence.

OCR confidence is NOT a correctness guarantee: an engine can be very
confident about a wrong digit. This module adds independent structural
and numerical checks. Findings are attached to the PageResult, surfaced
in the review UI ("Masalah berikutnya"), listed on the Audit sheet, and
"blocker"-severity findings prevent a FINAL export until a human has
reviewed the page.

Cell-level checks skip human-edited cells: a reviewer's correction
supersedes the machine's doubt.
"""

from __future__ import annotations

import math
import statistics
from typing import Optional

from app.locale_id import KIND_AMBIGUOUS, KIND_IDENTIFIER
from app.pipeline.models import Anomaly, Cell, PageResult

#: orientation score ratios below this are "the detector barely won"
LOW_ORIENTATION_MARGIN = 3.0
#: fraction of populated cells that must parse numeric for a column to
#: count as a numeric column
NUMERIC_COLUMN_SHARE = 0.6
#: |log10(value / column median)| above this is an order-of-magnitude outlier
OUTLIER_LOG10 = 3.0


def _numeric_columns(grid: list[list[Optional[Cell]]]) -> dict[int, list]:
    """col index -> parsed values, for columns that are mostly numeric."""
    n_cols = max((len(r) for r in grid), default=0)
    result: dict[int, list] = {}
    for c in range(n_cols):
        values, populated = [], 0
        for row in grid:
            cell = row[c] if c < len(row) else None
            if cell is None or not cell.effective_text.strip():
                continue
            populated += 1
            if cell.value is not None:
                values.append(cell.value)
        if populated >= 3 and len(values) / populated >= NUMERIC_COLUMN_SHARE:
            result[c] = values
    return result


def analyze_page(page: PageResult) -> list[Anomaly]:
    """All page-local anomalies for a PageResult's current grid."""
    anomalies: list[Anomaly] = []
    grid = page.grid
    if page.error or not grid:
        return anomalies

    # Orientation decided with a thin margin → whole page suspect.
    if 0 <= page.orientation_margin < LOW_ORIENTATION_MARGIN:
        anomalies.append(Anomaly(
            code="orientation-low-margin", severity="warning",
            message="Arah halaman terdeteksi dengan keyakinan tipis — "
                    "periksa apakah tabel terbaca pada posisi yang benar."))

    for flag in page.structure_flags:
        anomalies.append(Anomaly(
            code=f"structure-{flag}", severity="warning",
            message="Struktur tabel di halaman ini tidak stabil "
                    "(batas baris/kolom nyaris berubah) — cocokkan "
                    "susunan tabel dengan gambar."))

    numeric_cols = _numeric_columns(grid)

    for r, row in enumerate(grid):
        for c in range(max((len(x) for x in grid), default=0)):
            cell = row[c] if c < len(row) else None

            # Gap in a numeric column: an amount may have been dropped.
            if c in numeric_cols and (cell is None or not cell.effective_text.strip()):
                anomalies.append(Anomaly(
                    code="numeric-gap", row=r, col=c, severity="warning",
                    message="Sel kosong di kolom angka — pastikan memang "
                            "kosong di dokumen aslinya."))
                continue
            if cell is None or cell.edited:
                continue

            if cell.parse_kind == KIND_AMBIGUOUS:
                anomalies.append(Anomaly(
                    code="ambiguous-number", row=r, col=c, severity="blocker",
                    message=f"“{cell.effective_text}” bisa dibaca lebih dari "
                            "satu cara — tentukan nilai yang benar."))
            elif cell.parse_kind == KIND_IDENTIFIER and c in numeric_cols:
                anomalies.append(Anomaly(
                    code="identifier-in-numeric-column", row=r, col=c,
                    severity="warning",
                    message=f"“{cell.effective_text}” di kolom angka tampak "
                            "seperti nomor identitas, bukan nilai."))
            if "inner-whitespace-removed" in cell.parse_reason:
                anomalies.append(Anomaly(
                    code="repaired-number", row=r, col=c, severity="warning",
                    message=f"Angka “{cell.effective_text}” mengandung spasi "
                            "yang dihapus otomatis — cocokkan dengan gambar."))

    # Order-of-magnitude outliers per numeric column.
    for c, values in numeric_cols.items():
        magnitudes = [abs(v) for v in values if v != 0]
        if len(magnitudes) < 4:
            continue
        median = statistics.median(magnitudes)
        if median == 0:
            continue
        for r, row in enumerate(grid):
            cell = row[c] if c < len(row) else None
            if cell is None or cell.value in (None, 0) or cell.edited:
                continue
            ratio = abs(math.log10(float(abs(cell.value)) / float(median)))
            if ratio > OUTLIER_LOG10:
                anomalies.append(Anomaly(
                    code="magnitude-outlier", row=r, col=c, severity="warning",
                    message=f"“{cell.effective_text}” jauh lebih besar/kecil "
                            "dari angka lain di kolomnya — mungkin ada digit "
                            "hilang atau tertukar."))

    return anomalies


def cross_page_anomalies(pages: list[PageResult]) -> dict[int, list[Anomaly]]:
    """Checks that need to see all pages of a document-type group:
    a sudden column-count change inside one label usually means the
    reconstruction (not the document) changed shape."""
    by_label: dict[str, list[PageResult]] = {}
    for p in pages:
        if not p.error and p.grid:
            by_label.setdefault(p.doc_type_label or "", []).append(p)

    extra: dict[int, list[Anomaly]] = {}
    for label, group in by_label.items():
        if len(group) < 2 or not label:
            continue
        counts = [p.n_cols for p in group]
        common = statistics.mode(counts)
        for p in group:
            if p.n_cols != common:
                extra.setdefault(p.page_number, []).append(Anomaly(
                    code="column-count-differs", severity="warning",
                    message=f"Halaman ini terbaca {p.n_cols} kolom, sedangkan "
                            f"halaman lain berjenis “{label}” umumnya "
                            f"{common} kolom."))
    return extra
