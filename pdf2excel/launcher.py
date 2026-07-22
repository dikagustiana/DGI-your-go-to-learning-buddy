"""PyInstaller entry point.

Same behavior as ``python -m app``: no arguments launches the GUI,
subcommands (inspect / convert / export) run the CLI. The spec builds
two executables from this one script — ``pdf2excel`` (windowed, no
console flash on Windows) and ``pdf2excel-cli`` (console, for scripted
and headless use).
"""

import multiprocessing
import sys


def _acquire_app_mutex():
    """Hold the named mutex Inno Setup's AppMutex checks (Windows only).

    Kept alive for the process lifetime by returning the handle. No-op
    and harmless elsewhere.
    """
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from app import APP_MUTEX
        return ctypes.windll.kernel32.CreateMutexW(None, False, APP_MUTEX)
    except Exception:
        return None


if __name__ == "__main__":
    # Required for frozen Windows binaries if any dependency spawns
    # worker processes; harmless otherwise.
    multiprocessing.freeze_support()
    _mutex = _acquire_app_mutex()   # noqa: F841 (held for process lifetime)
    sys.exit(main())
