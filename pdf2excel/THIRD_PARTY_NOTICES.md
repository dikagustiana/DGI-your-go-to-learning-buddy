# Third-party notices

"PDF ke Excel" bundles third-party components. A full machine-readable
inventory of everything present in a given build is generated as
`sbom.json` alongside each release installer (see `installer/gen_sbom.py`).
The load-bearing runtime dependencies and their licenses:

| Component | Role | License | Notes |
|-----------|------|---------|-------|
| **PyMuPDF (fitz)** | PDF rasterization + text detection | **AGPL-3.0 / commercial** | ⚠ **DISTRIBUTION BLOCKER — see below.** |
| **PySide6 (Qt for Python)** | GUI | **LGPL-3.0 / GPL / commercial** | ⚠ LGPL obligations — see below. |
| RapidOCR (`rapidocr-onnxruntime`) | default OCR engine | Apache-2.0 | Models: PP-OCRv4 (Apache-2.0). |
| onnxruntime | OCR model runtime | MIT | |
| openpyxl | Excel writing | MIT | |
| Pillow | image handling | MIT-CMU (HPND) | |
| numpy | arrays | BSD-3-Clause | |
| PaddleOCR / PaddleX | optional engine (NOT shipped) | Apache-2.0 | Excluded from the installer. |

## ⚠ Legal blockers to resolve BEFORE production distribution

These are **decisions for the product owner / legal**, not something a
build script can settle. They do not affect internal development or
testing, but they gate shipping the installer to third parties.

1. **PyMuPDF is AGPL-3.0 (or a paid commercial license).** Distributing
   an application built on PyMuPDF under AGPL means the application's
   corresponding source must be offered under AGPL-compatible terms to
   recipients, including network-use provisions. For a proprietary or
   redistributed binary this typically requires **either** (a) a
   commercial PyMuPDF license from Artifex, **or** (b) replacing the PDF
   backend with a non-AGPL library (e.g. `pypdfium2` for
   rasterization, BSD/Apache-style). This is the single biggest
   licensing decision. The code isolates rasterization in
   `app/pipeline/pdf_loader.py`, so a backend swap is contained.

2. **PySide6 is LGPL-3.0** (unless a commercial Qt license is held).
   LGPL distribution obligations include: providing the LGPL license
   text, letting the user relink/replace the Qt libraries, and not
   statically linking Qt in a way that prevents that. A PyInstaller
   one-folder build ships Qt as separate shared libraries (good for
   LGPL), but the license texts and a written offer/relinking note must
   accompany the installer. Confirm compliance or obtain a commercial
   Qt license.

Until (1) and (2) are cleared, treat every built installer as
**internal-only**. The CI marks unsigned/dev artifacts accordingly.

## License texts

Full license texts of bundled components are available in each
distribution's metadata (and reproduced by the SBOM). Before external
distribution, assemble the required texts (at minimum AGPL-3.0,
LGPL-3.0, Apache-2.0, MIT, BSD-3-Clause, HPND) into the installer.
