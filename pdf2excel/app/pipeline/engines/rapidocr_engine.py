"""RapidOCR (rapidocr-onnxruntime) engine — the default.

Light, CPU-friendly, models bundled in the wheel. Returns loose tokens
only; row/column reconstruction happens in table_builder.

The per-textline angle classifier (use_cls) is enabled so lines that are
upside-down relative to the page (180°) are corrected automatically —
page-level 90° rotation is handled earlier by orientation detection.
"""

from __future__ import annotations

import numpy as np

from app.pipeline.engines.base import OCREngine
from app.pipeline.models import OCRToken


class RapidOCREngine(OCREngine):
    name = "rapidocr"
    supports_table_structure = False

    _instance = None  # model load is slow; share one instance per process

    @classmethod
    def models_present(cls) -> bool:
        """Verify the bundled ONNX models actually resolve on disk.

        The models ship as data files inside the rapidocr_onnxruntime
        package. In a PyInstaller one-folder build they are collected
        under _internal/rapidocr_onnxruntime/models — the package's
        __file__ points there too, so this same check validates both
        the source install and the frozen app. Detection, angle
        classification and recognition each need one model; anything
        less means a broken bundle, and the app must fail loudly at
        startup rather than attempt a download (offline-first promise).
        """
        try:
            import pathlib
            import rapidocr_onnxruntime
            pkg_dir = pathlib.Path(rapidocr_onnxruntime.__file__).parent
            return len(list(pkg_dir.glob("**/*.onnx"))) >= 3
        except Exception:
            return False

    @classmethod
    def is_available(cls) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return False
        return cls.models_present()

    @classmethod
    def unavailable_hint(cls) -> str:
        return "pip install rapidocr-onnxruntime"

    def _get_ocr(self):
        if RapidOCREngine._instance is None:
            from rapidocr_onnxruntime import RapidOCR
            RapidOCREngine._instance = RapidOCR()
        return RapidOCREngine._instance

    def ocr_tokens(self, image: np.ndarray, use_cls: bool = True) -> list[OCRToken]:
        ocr = self._get_ocr()
        result, _elapse = ocr(image, use_det=True, use_cls=use_cls, use_rec=True)
        tokens: list[OCRToken] = []
        if not result:
            return tokens
        for box, text, score in result:
            # box is 4 corner points (possibly a slightly rotated quad);
            # collapse to the axis-aligned bbox — good enough for
            # row/column banding on deskewed scans.
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            text = (text or "").strip()
            if not text:
                continue
            tokens.append(OCRToken(
                text=text,
                confidence=float(score),
                x0=float(min(xs)), y0=float(min(ys)),
                x1=float(max(xs)), y1=float(max(ys)),
            ))
        return tokens
