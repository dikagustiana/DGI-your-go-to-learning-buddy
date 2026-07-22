"""Keep the computer awake during a long conversion (Windows).

A 150-page run can take ~an hour; if Windows sleeps, the job stops. This
asks Windows to stay awake (display may still sleep) while a job runs,
and ALWAYS releases the request afterwards. No-op on other platforms.

Use as a context manager or start()/stop() pair; releasing is
idempotent and safe to call from cleanup paths.
"""

from __future__ import annotations

import sys

# Windows SetThreadExecutionState flags.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


class KeepAwake:
    def __init__(self) -> None:
        self._active = False

    def start(self) -> None:
        if self._active or sys.platform != "win32":
            self._active = sys.platform == "win32" and self._active
            return
        try:
            import ctypes
            ctypes.windll.kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED)
            self._active = True
        except Exception:
            self._active = False

    def stop(self) -> None:
        if not self._active or sys.platform != "win32":
            self._active = False
            return
        try:
            import ctypes
            # Clearing back to CONTINUOUS-only releases the wake request.
            ctypes.windll.kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
        except Exception:
            pass
        finally:
            self._active = False

    def __enter__(self) -> "KeepAwake":
        self.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop()
