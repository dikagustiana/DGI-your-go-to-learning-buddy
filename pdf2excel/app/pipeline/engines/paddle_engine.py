"""PaddleOCR PP-StructureV3 engine — optional, native table structure.

Installed via the ``paddleocr`` wheel (v3.x), NOT by cloning the repo;
the GitHub ``ppstructure/`` directory is the deprecated V2 pipeline.
Models download on first run (large). When the package is missing the
engine simply reports unavailable and the UI greys it out with a hint —
never crash on import.

Full implementation lands in milestone 5; the interface and the
availability/graceful-degradation contract are wired now so the rest of
the app never special-cases it.
"""

from __future__ import annotations

import numpy as np

from app.pipeline.engines.base import EngineUnavailableError, OCREngine
from app.pipeline.models import Cell, OCRToken


class PaddleStructureEngine(OCREngine):
    name = "paddle-ppstructure"
    supports_table_structure = True

    @classmethod
    def is_available(cls) -> bool:
        try:
            import paddleocr  # noqa: F401
            return True
        except ImportError:
            return False

    @classmethod
    def unavailable_hint(cls) -> str:
        return ("pip install paddleocr paddlepaddle  "
                "(large download; models fetched on first run)")

    def ocr_tokens(self, image: np.ndarray, use_cls: bool = True) -> list[OCRToken]:
        if not self.is_available():
            raise EngineUnavailableError(self.unavailable_hint())
        raise NotImplementedError(
            "PP-StructureV3 support arrives in milestone 5; "
            "use the rapidocr engine for now.")

    def ocr_table(self, image: np.ndarray):
        if not self.is_available():
            raise EngineUnavailableError(self.unavailable_hint())
        raise NotImplementedError(
            "PP-StructureV3 support arrives in milestone 5; "
            "use the rapidocr engine for now.")
