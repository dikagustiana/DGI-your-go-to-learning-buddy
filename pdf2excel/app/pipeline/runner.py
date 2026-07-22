"""Headless pipeline orchestration.

This is the single processing path: the CLI calls it directly and the
GUI (milestone 2) will call it from a QThread worker via the same
``progress`` / ``should_cancel`` hooks. Keep it Qt-free.
"""

from __future__ import annotations

from typing import Callable, Optional

from app.config import PipelineConfig
from app.pipeline import anomalies as anomalies_mod
from app.pipeline import orientation, pdf_loader, table_builder, validators
from app.pipeline.engines import create_engine
from app.pipeline.models import PageResult
from app.versions import extraction_config_hash

ProgressFn = Callable[[int, int, str], None]        # (done, total, message)
CancelFn = Callable[[], bool]
PageFn = Callable[[PageResult], None]               # per-page sink (e.g. session)


def refresh_anomalies(result: PageResult) -> None:
    """Recompute page-local anomalies + doc-type validators.

    Called after extraction and again after review edits or a label
    change, so the anomaly list always reflects the current grid.
    """
    if result.error:
        result.anomalies = []
        return
    found = anomalies_mod.analyze_page(result)
    found.extend(validators.run_validators(result.doc_type_label, result.grid))
    result.anomalies = found


def process_page(pdf_path: str, page_number: int, config: PipelineConfig,
                 engine=None) -> PageResult:
    """Run the full pipeline on one page: rasterize → rotate → OCR → grid."""
    if engine is None:
        engine = create_engine(config.engine)

    image = pdf_loader.rasterize_page(pdf_path, page_number, dpi=config.dpi)

    margin = -1.0
    if config.rotation == "auto":
        rot, margin = orientation.detect_rotation_scored(
            image, engine, probe_max_side=config.osd_probe_max_side)
        rot_source = "auto"
    else:
        rot = int(config.rotation) % 360
        rot_source = "forced"
    if rot:
        image = orientation.rotate_image(image, rot)

    grid = engine.ocr_table(image) if engine.supports_table_structure else None
    tokens = engine.ocr_tokens(image) if grid is None else []
    flags: list[str] = []
    if grid is None:
        grid = table_builder.build_grid(tokens)
        flags = table_builder.stability_flags(tokens, grid)

    result = PageResult(
        page_number=page_number, rotation_applied=rot,
        rotation_source=rot_source, grid=grid, tokens=tokens,
        dpi=config.dpi, orientation_margin=margin,
        engine=config.engine, structure_flags=flags,
        config_hash=extraction_config_hash(config.to_dict(), config.engine))
    refresh_anomalies(result)
    return result


def process_pdf(pdf_path: str, config: PipelineConfig,
                progress: Optional[ProgressFn] = None,
                should_cancel: Optional[CancelFn] = None,
                on_page: Optional[PageFn] = None) -> list[PageResult]:
    """Process a page range of a PDF; page errors are captured per page
    so one bad scan never aborts a 150-page batch. ``on_page`` fires as
    each page completes — used to persist results incrementally so a
    crash or cancel mid-batch loses at most the in-flight page."""
    info = pdf_loader.inspect_pdf(pdf_path)
    first, last = 1, info.n_pages
    if config.page_range:
        first = max(first, config.page_range[0])
        last = min(last, config.page_range[1])
    pages = list(range(first, last + 1))
    total = len(pages)

    engine = create_engine(config.engine)
    results: list[PageResult] = []
    for i, pno in enumerate(pages):
        if should_cancel and should_cancel():
            break
        if progress:
            progress(i, total, f"OCR page {pno}/{info.n_pages}")
        try:
            results.append(process_page(pdf_path, pno, config, engine=engine))
        except Exception as exc:  # keep the batch alive
            results.append(PageResult(page_number=pno, rotation_applied=0,
                                      rotation_source="error", error=str(exc)))
        if on_page:
            on_page(results[-1])
        if progress:
            progress(i + 1, total, f"page {pno} done")
    return results
