"""Tests for the long-run progress estimator and keep-awake (Fase 5)."""

from app.gui.keep_awake import KeepAwake
from app.gui.progress_eta import ProgressEstimator


def test_status_shows_real_page_number():
    est = ProgressEstimator(total=156, start_time=0.0)
    est.tick(5.0, 1)
    s = est.status(5.0, current_page=42)
    assert "halaman 42" in s
    assert "dari 156" in s
    assert "jangan dimatikan" in s.lower()


def test_eta_range_appears_after_samples():
    est = ProgressEstimator(total=100, start_time=0.0)
    assert est.eta_range(0.0) is None            # no samples yet
    for i in range(1, 5):
        est.tick(float(i * 10), i)               # 10s per page
    band = est.eta_range(40.0)
    assert band is not None
    lo, hi = band
    assert lo < hi                               # a range, not false precision
    # ~96 pages left * 10s = ~960s, within the ±25% band
    assert lo <= 960 <= hi


def test_elapsed_and_completion():
    est = ProgressEstimator(total=2, start_time=100.0)
    est.tick(110.0, 1)
    est.tick(120.0, 2)
    assert est.done == 2
    assert est.eta_range(120.0) is None          # complete → no ETA
    assert "2 dari 2" in est.status(120.0)


def test_keep_awake_noop_off_windows():
    # On non-Windows this must be a safe no-op and never raise.
    ka = KeepAwake()
    ka.start()
    ka.stop()
    with KeepAwake():
        pass
