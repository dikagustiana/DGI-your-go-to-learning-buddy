# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for pdf2excel.

Build (from this directory, inside the project's virtualenv):

    pyinstaller pdf2excel.spec --noconfirm

Produces dist/pdf2excel/ (one-folder bundle) containing:
    pdf2excel       — windowed GUI executable (no console on Windows)
    pdf2excel-cli   — console executable for inspect/convert/export

One-folder (not one-file) on purpose: Qt + onnxruntime in a one-file
binary unpack to a temp dir on every launch (slow start, antivirus
noise). Zip the folder for distribution.

The bundle ships the RapidOCR engine only. PaddleOCR/PP-StructureV3 is
excluded EXPLICITLY below — not just because it adds gigabytes, but
because PyInstaller traces the lazy imports inside paddle_engine.py and
would pull the whole paddle stack into every build on a dev machine
that has it installed. Paddle users run from source; the frozen app
greys the engine out with the usual install hint.
"""

import sys

from PyInstaller.utils.hooks import collect_data_files

# RapidOCR ships its ONNX models + config.yaml inside the wheel; they
# are data files, not imports, so they must be collected explicitly.
# The app refuses to consider the engine available unless the .onnx
# files resolve on disk (RapidOCREngine.models_present), so a build
# that loses them fails visibly instead of trying to download.
datas = collect_data_files("rapidocr_onnxruntime")

# Windows executables get the app icon; other platforms ignore it.
ICON = "assets/icon.ico" if sys.platform == "win32" else None

a = Analysis(
    ["launcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[
        # optional heavy engine — see module docstring
        "paddle", "paddleocr", "paddlex",
        # optional orientation helper (system tesseract won't be bundled)
        "pytesseract",
        # common bloat that sneaks in via transitive imports
        "matplotlib", "tkinter", "IPython", "jupyter",
        "pytest",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe_gui = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pdf2excel",
    debug=False,
    strip=False,
    upx=False,
    console=False,          # windowed: no console flash behind the GUI
    icon=ICON,
)

exe_cli = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="pdf2excel-cli",
    debug=False,
    strip=False,
    upx=False,
    console=True,           # stdout/stderr visible for scripted use
    icon=ICON,
)

coll = COLLECT(
    exe_gui,
    exe_cli,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="pdf2excel",
)
