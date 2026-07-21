"""Runtime configuration for the extraction pipeline.

All knobs the UI config panel will expose live here so the headless
pipeline and the GUI share one source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class PipelineConfig:
    # Rasterization. 300 DPI is the validated floor for dense scanned
    # tables (150 DPI was too noisy on the sample corpus). Do not lower
    # the default.
    dpi: int = 300

    # OCR engine key as registered in app.pipeline.engines.
    engine: str = "rapidocr"

    # Rotation: "auto" runs per-page orientation detection; an int
    # (0/90/180/270, clockwise) forces that rotation for every page.
    # The GUI additionally allows a per-page manual override on top.
    rotation: str | int = "auto"

    # Orientation detection runs quick OCR probes on a downscaled copy;
    # this bounds the longest image side for those probes.
    osd_probe_max_side: int = 1200

    # Cells whose mean OCR confidence falls below this are flagged for
    # human review (highlighted in the QA view and in the export).
    low_confidence_threshold: float = 0.80

    # Excel layout: "sheet_per_page" or "merged_by_label".
    output_layout: str = "sheet_per_page"

    # Keep the raw OCR string next to every parsed numeric value
    # (hidden column block) for audit. Finance tie-out requirement —
    # leave on unless you have a reason not to.
    export_raw_columns: bool = True

    # Optional page selection, 1-based inclusive, e.g. (1, 5). None = all.
    page_range: Optional[tuple[int, int]] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PipelineConfig":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})
