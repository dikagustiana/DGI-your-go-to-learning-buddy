"""RapidOCR (rapidocr-onnxruntime) engine — the default.

Light, CPU-friendly, models bundled in the wheel. Returns loose tokens
only; row/column reconstruction happens in table_builder.

The per-textline angle classifier (use_cls) is enabled so lines that are
upside-down relative to the page (180°) are corrected automatically —
page-level 90° rotation is handled earlier by orientation detection.
"""

from __future__ import annotations

import threading

import numpy as np

from app.pipeline.engines.base import OCREngine
from app.pipeline.models import OCRToken


class RapidOCREngine(OCREngine):
    name = "rapidocr"
    supports_table_structure = False

    _instance = None  # model load is slow; share one instance per process
    # The underlying ONNX session is a shared singleton; serialize calls
    # so a stray second thread can never enter it concurrently (the GUI
    # JobCoordinator already prevents this, but this is defense-in-depth).
    _lock = threading.Lock()

    @classmethod
    def models_present(cls, deep: bool = False) -> bool:
        """True when the bundled ONNX models match the manifest.

        Verifies by NAME + size (and SHA-256 when ``deep``), not a mere
        file count — a swapped or truncated model must fail closed, never
        trigger a download (offline-first promise). Works identically for
        a source install and the PyInstaller _internal layout because the
        package __file__ points at the collected models either way.
        """
        try:
            from app.pipeline.engines.rapidocr_models import verify_models
            return verify_models(deep=deep).ok
        except Exception:
            return False

    @classmethod
    def model_check_detail(cls) -> str:
        """Human-readable reason the models failed verification (deep)."""
        try:
            from app.pipeline.engines.rapidocr_models import verify_models
            return verify_models(deep=True).detail
        except Exception as exc:
            return str(exc)

    @classmethod
    def is_available(cls) -> bool:
        try:
            import rapidocr_onnxruntime  # noqa: F401
        except ImportError:
            return False
        # Fast presence+size probe for the frequent availability check;
        # the deep SHA-256 verification runs once on first real use.
        return cls.models_present(deep=False)

    @classmethod
    def unavailable_hint(cls) -> str:
        return "pip install rapidocr-onnxruntime"

    _verified = False

    def _get_ocr(self):
        with RapidOCREngine._lock:
            if RapidOCREngine._instance is None:
                # Deep-verify once before the models are ever loaded: a
                # tampered/truncated model fails closed here rather than
                # producing silently wrong OCR (or reaching the network).
                if not RapidOCREngine._verified:
                    from app.pipeline.engines.base import EngineUnavailableError
                    from app.pipeline.engines.rapidocr_models import verify_models
                    check = verify_models(deep=True)
                    if not check.ok:
                        raise EngineUnavailableError(check.detail)
                    RapidOCREngine._verified = True
                from rapidocr_onnxruntime import RapidOCR
                RapidOCREngine._instance = RapidOCR()
            return RapidOCREngine._instance

    def ocr_tokens(self, image: np.ndarray, use_cls: bool = True) -> list[OCRToken]:
        ocr = self._get_ocr()
        with RapidOCREngine._lock:
            result, _elapse = ocr(image, use_det=True, use_cls=use_cls,
                                  use_rec=True)
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
