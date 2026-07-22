"""PDF loading and rasterization.

Backend choice: PyMuPDF (fitz) rather than pdf2image+poppler.
Rationale, documented per spec:
  * no external system dependency (poppler binaries) — one pip install,
    which also keeps PyInstaller packaging simple;
  * fast in-process rasterization at arbitrary DPI;
  * gives us text-layer detection (page.get_text) for the
    scanned-vs-native check with the same library.
"""

from __future__ import annotations

from dataclasses import dataclass

import fitz  # PyMuPDF
import numpy as np


@dataclass
class PdfInfo:
    path: str
    n_pages: int
    has_text_layer: bool
    text_chars: int
    producer: str
    creator: str


def inspect_pdf(path: str) -> PdfInfo:
    """Open the PDF and decide scanned vs native.

    A handful of stray characters (page stamps, OCR leftovers) shouldn't
    count as a usable text layer, so the threshold is per-page average.
    """
    with fitz.open(path) as doc:
        total_chars = 0
        for page in doc:
            total_chars += len(page.get_text("text").strip())
        n_pages = doc.page_count
        meta = doc.metadata or {}
        return PdfInfo(
            path=path,
            n_pages=n_pages,
            has_text_layer=(total_chars / max(n_pages, 1)) > 25,
            text_chars=total_chars,
            producer=meta.get("producer") or "",
            creator=meta.get("creator") or "",
        )


def rasterize_page(path: str, page_number: int, dpi: int = 300) -> np.ndarray:
    """Render one page (1-based) to an RGB numpy array at ``dpi``."""
    with fitz.open(path) as doc:
        page = doc[page_number - 1]
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8)
        return img.reshape(pix.height, pix.width, 3).copy()


def extract_native_text(path: str, page_number: int) -> str:
    """Plain text of a page for the skip-OCR path on native PDFs."""
    with fitz.open(path) as doc:
        return doc[page_number - 1].get_text("text")
