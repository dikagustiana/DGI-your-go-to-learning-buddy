"""Background OCR worker.

Wraps the Qt-free pipeline (app.pipeline.runner) in a QObject that runs
inside a QThread, so a 150-page batch never freezes the UI. Results are
emitted per page as soon as they are ready, letting the page list fill
in live during a long run.

Cancellation is cooperative: ``cancel()`` flips a flag that is checked
between pages, so the page currently in OCR finishes and nothing is left
half-done.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from app.config import PipelineConfig
from app.pipeline import pdf_loader
from app.pipeline.engines import create_engine
from app.pipeline.models import PageResult
from app.pipeline.runner import process_page


class OcrWorker(QObject):
    #: done, total, message
    progress = Signal(int, int, str)
    #: one PageResult, emitted as soon as its page finishes
    page_done = Signal(object)
    #: all PageResults collected so far (also emitted after a cancel)
    finished = Signal(list, bool)  # (results, was_cancelled)
    #: fatal error before/around the page loop (bad file, engine missing)
    failed = Signal(str)

    def __init__(self, pdf_path: str, config: PipelineConfig,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._config = config
        self._cancelled = False

    def cancel(self) -> None:
        """Thread-safe: a plain bool flip read between pages."""
        self._cancelled = True

    @Slot()
    def run(self) -> None:
        try:
            info = pdf_loader.inspect_pdf(self._pdf_path)
            first, last = 1, info.n_pages
            if self._config.page_range:
                first = max(first, self._config.page_range[0])
                last = min(last, self._config.page_range[1])
            pages = list(range(first, last + 1))
            total = len(pages)

            self.progress.emit(0, total, "Loading OCR engine…")
            engine = create_engine(self._config.engine)
        except Exception as exc:
            self.failed.emit(str(exc))
            return

        results: list[PageResult] = []
        for i, pno in enumerate(pages):
            if self._cancelled:
                self.finished.emit(results, True)
                return
            self.progress.emit(i, total, f"OCR page {pno} of {info.n_pages}…")
            try:
                result = process_page(self._pdf_path, pno, self._config,
                                      engine=engine)
            except Exception as exc:  # a bad page must not kill the batch
                result = PageResult(page_number=pno, rotation_applied=0,
                                    rotation_source="error", error=str(exc))
            results.append(result)
            self.page_done.emit(result)
            self.progress.emit(i + 1, total, f"Page {pno} done")

        self.finished.emit(results, False)


class SinglePageWorker(QObject):
    """Re-runs one page — used by the QA view's rotation override."""

    done = Signal(object)   # PageResult
    failed = Signal(str)

    def __init__(self, pdf_path: str, page_number: int,
                 config: PipelineConfig, rotation: int,
                 parent: QObject | None = None):
        super().__init__(parent)
        self._pdf_path = pdf_path
        self._page_number = page_number
        self._config = config
        self._rotation = rotation % 360

    @Slot()
    def run(self) -> None:
        try:
            import dataclasses
            config = dataclasses.replace(self._config, rotation=self._rotation)
            result = process_page(self._pdf_path, self._page_number, config)
            result.rotation_source = "manual"
            self.done.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
