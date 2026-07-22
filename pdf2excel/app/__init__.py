"""pdf2excel — offline scanned-PDF to Excel converter for Indonesian finance documents."""

# Single source of truth for the app + installer version. The installer
# reads it via installer/gen_version.py -> installer/version.iss, the UI
# shows it, and the session records it. Bump here only.
__version__ = "1.0.0"

#: named mutex used on Windows so the Inno Setup installer can refuse to
#: install/upgrade while the app is running (see setup.iss AppMutex).
APP_MUTEX = "PDFkeExcel_SingleInstance_Mutex"
