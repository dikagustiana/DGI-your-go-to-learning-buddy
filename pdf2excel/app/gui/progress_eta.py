"""Elapsed / ETA estimation for long batches.

Kept separate from Qt so it is unit-testable: feed it a monotonic clock
and page-completion ticks, get back a human, plain-Indonesian status
line with real page numbers, elapsed time, and an ETA *range* (not a
false-precision single number) once enough pages have finished.
"""

from __future__ import annotations

from dataclasses import dataclass, field


def _hms(seconds: float) -> str:
    seconds = int(max(seconds, 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} jam {m} menit"
    if m:
        return f"{m} menit {s} detik"
    return f"{s} detik"


@dataclass
class ProgressEstimator:
    total: int
    start_time: float
    done: int = 0
    _last_tick: float = 0.0
    _durations: list[float] = field(default_factory=list)

    def start(self, now: float) -> None:
        self.start_time = now
        self._last_tick = now

    def tick(self, now: float, done: int) -> None:
        """Record that ``done`` pages are now complete."""
        if done > self.done:
            self._durations.append(now - self._last_tick)
            self._last_tick = now
            self.done = done

    def elapsed(self, now: float) -> float:
        return now - self.start_time

    def eta_range(self, now: float) -> tuple[float, float] | None:
        """(low, high) seconds remaining, or None until enough samples."""
        if self.done < 3 or self.done >= self.total:
            return None
        per_page = (now - self.start_time) / self.done
        remaining = self.total - self.done
        # ±25% band communicates honest uncertainty.
        return remaining * per_page * 0.75, remaining * per_page * 1.25

    def status(self, now: float, current_page: int | None = None) -> str:
        parts = []
        if current_page is not None and self.done < self.total:
            parts.append(f"Sedang memproses halaman {current_page} "
                         f"(nomor {self.done + 1} dari {self.total})…")
        else:
            parts.append(f"{self.done} dari {self.total} halaman selesai…")
        parts.append(f"Sudah berjalan {_hms(self.elapsed(now))}.")
        band = self.eta_range(now)
        if band:
            lo, hi = band
            parts.append(f"Perkiraan sisa waktu {_hms(lo)}–{_hms(hi)}.")
        parts.append("Komputer boleh ditinggal, tapi jangan dimatikan "
                     "atau ditidurkan.")
        return " ".join(parts)
