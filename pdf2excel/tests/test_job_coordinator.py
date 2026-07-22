"""Regression tests for the shared JobCoordinator (Fase 3).

These verify the concurrency GUARANTEES (mutual exclusion, generation
guarding, idle shutdown) deterministically, without spinning real
QThreads — thread races under the offscreen test platform are flaky and
the guarantees are pure control-flow that can be checked directly.
"""

import os

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.config import PipelineConfig  # noqa: E402
from app.gui.job_coordinator import JobCoordinator  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def coord(qapp, monkeypatch):
    """A coordinator whose _launch records the worker but starts no thread."""
    c = JobCoordinator()
    launched = []

    def fake_launch(worker):
        c._worker = worker
        c._thread = object()          # non-None => busy
        c.busy_changed.emit(True)
        launched.append(worker)

    monkeypatch.setattr(c, "_launch", fake_launch)
    c._launched = launched
    yield c


def _finish(coord):
    """Simulate the running job ending (mirrors _teardown without Qt).

    Clearing _worker is what makes the sender-identity guard drop any
    signal still queued from the finished job.
    """
    coord._thread = None
    coord._worker = None
    coord._kind = ""
    coord.busy_changed.emit(False)


def test_batch_blocks_any_second_start(coord):
    cfg = PipelineConfig()
    assert coord.start_batch("x.pdf", cfg, [1]) is True
    assert coord.busy is True
    assert coord.running_kind == "batch"
    # A second batch OR a single-page re-OCR must be refused while busy —
    # two workers can never write the same page.
    assert coord.start_batch("x.pdf", cfg, [2]) is False
    assert coord.start_single("x.pdf", 1, cfg, 0) is False


def test_single_blocks_batch(coord):
    cfg = PipelineConfig()
    assert coord.start_single("x.pdf", 1, cfg, 90) is True
    assert coord.running_kind == "single"
    assert coord.start_batch("x.pdf", cfg, [1]) is False


def test_can_start_again_after_finish(coord):
    cfg = PipelineConfig()
    assert coord.start_batch("x.pdf", cfg, [1]) is True
    _finish(coord)
    assert coord.busy is False
    assert coord.start_batch("x.pdf", cfg, [2]) is True


def test_busy_changed_emitted(coord):
    states = []
    coord.busy_changed.connect(states.append)
    coord.start_batch("x.pdf", PipelineConfig(), [1])
    _finish(coord)
    assert states == [True, False]


def test_stale_generation_dropped(coord):
    # A signal from a superseded generation must not reach listeners.
    got = []
    coord.page_done.connect(got.append)
    coord.start_batch("x.pdf", PipelineConfig(), [1])
    worker = coord._launched[-1]
    _finish(coord)                       # generation bumped past the job
    worker.page_done.emit("STALE")       # late signal from the old worker
    assert "STALE" not in got


def test_fresh_generation_delivered(coord):
    got = []
    coord.page_done.connect(got.append)
    coord.start_batch("x.pdf", PipelineConfig(), [1])
    worker = coord._launched[-1]
    worker.page_done.emit("FRESH")       # current generation
    assert "FRESH" in got


def test_shutdown_idle_returns_true(qapp):
    assert JobCoordinator().shutdown() is True
