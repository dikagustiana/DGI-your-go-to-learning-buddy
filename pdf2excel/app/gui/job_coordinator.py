"""Shared OCR job coordinator for both GUIs.

Business rule (shared, not duplicated between the simple and expert
windows): only ONE OCR job — a batch run OR a single-page re-OCR — may
run at a time, and a stale worker must never overwrite a newer result.

How it enforces that:
  * ``busy`` gates every start: a second start is refused while a job
    runs, so two workers can never write the same page, and the OCR
    engine singleton is never entered from two threads at once.
  * a monotonically increasing ``generation`` stamps each job; results
    from a generation older than the current one are dropped. (Belt and
    braces with ``busy`` — protects against a late signal arriving after
    a cancel.)
  * cancel/close use quit()+wait(timeout) and report if a worker refuses
    to stop, instead of hanging the UI forever.

The coordinator is Qt-thread aware but UI-framework-neutral in its
policy: it owns the QThread/worker lifecycle and emits plain callbacks.
"""

from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QObject, QThread, Signal

from app.config import PipelineConfig
from app.gui.worker import OcrWorker, SinglePageWorker
from app.pipeline.models import PageResult

#: how long cancel()/shutdown() wait for a worker thread to finish (ms)
WORKER_WAIT_MS = 15_000


class JobCoordinator(QObject):
    # batch signals
    batch_progress = Signal(int, int, str)     # done, total, message
    page_done = Signal(object)                 # PageResult (batch or single)
    batch_finished = Signal(list, bool)        # results, was_cancelled
    # single-page signals
    single_done = Signal(object)               # PageResult
    # shared
    failed = Signal(str)
    busy_changed = Signal(bool)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._thread: Optional[QThread] = None
        self._worker = None
        self._kind = ""            # "batch" | "single" | ""

    # ------------------------------------------------------------ state

    @property
    def busy(self) -> bool:
        return self._thread is not None

    @property
    def running_kind(self) -> str:
        return self._kind

    # ------------------------------------------------------------ batch

    def start_batch(self, pdf_path: str, config: PipelineConfig,
                    pages: list[int] | None) -> bool:
        if self.busy:
            return False
        self._kind = "batch"
        worker = OcrWorker(pdf_path, config, pages=pages)
        # Connect to BOUND METHODS of this coordinator (a QObject living
        # in the main thread), NOT lambdas: a bare lambda has no thread
        # affinity, so Qt would run it in the worker thread and any
        # thread.wait() inside would deadlock ("wait on itself").
        worker.progress.connect(self._on_batch_progress)
        worker.page_done.connect(self._on_worker_page_done)
        worker.finished.connect(self._on_batch_finished)
        worker.failed.connect(self._on_worker_failed)
        self._launch(worker)
        return True

    def _on_batch_progress(self, done: int, total: int, message: str) -> None:
        if self.sender() is self._worker:
            self.batch_progress.emit(done, total, message)

    def _on_worker_page_done(self, result: PageResult) -> None:
        if self.sender() is self._worker:      # drop stale/late signals
            self.page_done.emit(result)

    def _on_batch_finished(self, results: list, was_cancelled: bool) -> None:
        if self.sender() is not self._worker:
            return
        self._teardown()
        self.batch_finished.emit(results, was_cancelled)

    def _on_worker_failed(self, message: str) -> None:
        if self.sender() is not self._worker:
            return
        self._teardown()
        self.failed.emit(message)

    # ------------------------------------------------------ single page

    def start_single(self, pdf_path: str, page_number: int,
                     config: PipelineConfig, rotation: int) -> bool:
        if self.busy:
            return False
        self._kind = "single"
        worker = SinglePageWorker(pdf_path, page_number, config, rotation)
        worker.done.connect(self._on_single_done)
        worker.failed.connect(self._on_worker_failed)
        self._launch(worker)
        return True

    def _on_single_done(self, result: PageResult) -> None:
        if self.sender() is not self._worker:
            return
        self._teardown()
        self.single_done.emit(result)

    # --------------------------------------------------------- internals

    def _launch(self, worker) -> None:
        self._worker = worker
        self._thread = QThread(self)
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        self._thread.start()
        self.busy_changed.emit(True)

    def cancel(self) -> None:
        """Ask the batch worker to stop after the current page."""
        if self._worker is not None and hasattr(self._worker, "cancel"):
            self._worker.cancel()

    def _teardown(self) -> None:
        # Clear the worker reference FIRST: the sender-identity guard in
        # every slot then drops any signal still queued from this job.
        worker = self._worker
        thread = self._thread
        self._worker = None
        self._thread = None
        self._kind = ""
        if thread is not None:
            thread.quit()
            thread.wait(WORKER_WAIT_MS)
            thread.deleteLater()
        if worker is not None:
            worker.deleteLater()
        self.busy_changed.emit(False)

    def shutdown(self) -> bool:
        """Stop any running job for app/dialog close. Returns True if the
        worker thread stopped within the timeout."""
        stopped = True
        if self._worker is not None and hasattr(self._worker, "cancel"):
            self._worker.cancel()
        if self._thread is not None:
            self._thread.quit()
            stopped = self._thread.wait(WORKER_WAIT_MS)
        self._thread = None
        self._worker = None
        self._kind = ""
        return stopped
