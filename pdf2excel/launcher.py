"""PyInstaller entry point.

Same behavior as ``python -m app``: no arguments launches the GUI,
subcommands (inspect / convert / export) run the CLI. The spec builds
two executables from this one script — ``pdf2excel`` (windowed, no
console flash on Windows) and ``pdf2excel-cli`` (console, for scripted
and headless use).
"""

import multiprocessing
import sys

from app.__main__ import main

if __name__ == "__main__":
    # Required for frozen Windows binaries if any dependency spawns
    # worker processes; harmless otherwise.
    multiprocessing.freeze_support()
    sys.exit(main())
