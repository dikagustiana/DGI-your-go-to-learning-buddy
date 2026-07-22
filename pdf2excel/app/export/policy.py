"""Export policy: when is a workbook FINAL, and how drafts are labeled.

Single source of truth for both GUIs and the CLI — the rules must never
diverge between the simple and the expert flow:

* FINAL requires: no failed pages, every non-error page reviewed by a
  human, no blocker anomalies outstanding, no page marked
  needs-reextraction.
* Anything else is a DRAF: the workbook is still produced (the user may
  legitimately want it early), but its filename and its Ringkasan sheet
  say so loudly. A draft must never look like a verified deliverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.pipeline.models import PageResult


@dataclass
class ExportEligibility:
    final_ok: bool
    reasons: list[str] = field(default_factory=list)   # plain Indonesian


def final_eligibility(pages: list[PageResult]) -> ExportEligibility:
    reasons: list[str] = []

    failed = [p.page_number for p in pages if p.error]
    if failed:
        reasons.append(
            f"{len(failed)} halaman gagal dibaca "
            f"(halaman {_page_list(failed)}).")

    unreviewed = [p.page_number for p in pages
                  if not p.error and not p.reviewed]
    if unreviewed:
        reasons.append(
            f"{len(unreviewed)} halaman belum diperiksa manusia "
            f"(halaman {_page_list(unreviewed)}).")

    reextract = [p.page_number for p in pages if p.needs_reextraction]
    if reextract:
        reasons.append(
            f"{len(reextract)} halaman ditandai perlu dibaca ulang "
            f"(halaman {_page_list(reextract)}).")

    blockers = [(p.page_number, a) for p in pages
                for a in p.blocker_anomalies()]
    if blockers:
        pages_b = sorted({pno for pno, _ in blockers})
        reasons.append(
            f"{len(blockers)} masalah serius belum diselesaikan "
            f"(halaman {_page_list(pages_b)}).")

    return ExportEligibility(final_ok=not reasons, reasons=reasons)


def status_label(final_ok: bool) -> str:
    return "FINAL" if final_ok else "DRAF — BELUM DIPERIKSA"


def filename_suffix(final_ok: bool) -> str:
    return "" if final_ok else " (DRAF)"


def _page_list(numbers: list[int], limit: int = 10) -> str:
    text = ", ".join(str(n) for n in numbers[:limit])
    if len(numbers) > limit:
        text += ", …"
    return text
