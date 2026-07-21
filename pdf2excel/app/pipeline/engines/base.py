"""Common OCR engine interface.

Both engines (RapidOCR default, PaddleOCR PP-StructureV3 optional) plug
in behind this. Engines that only return loose tokens (RapidOCR) leave
``ocr_table`` unimplemented and the pipeline reconstructs the grid from
bounding boxes; engines with native table-structure recognition
(PP-StructureV3) can override ``ocr_table`` to return the grid directly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

import numpy as np

from app.pipeline.models import Cell, OCRToken


class EngineUnavailableError(RuntimeError):
    """Raised when an engine's backing package is not installed."""


class OCREngine(ABC):
    #: registry key + UI label
    name: str = ""
    #: True when the engine returns table structure natively
    supports_table_structure: bool = False

    @classmethod
    @abstractmethod
    def is_available(cls) -> bool:
        """Cheap installed-check; must not download models or crash."""

    @classmethod
    def unavailable_hint(cls) -> str:
        """Human-readable hint shown in the UI tooltip when disabled."""
        return ""

    @abstractmethod
    def ocr_tokens(self, image: np.ndarray, use_cls: bool = True) -> list[OCRToken]:
        """Run OCR on an RGB numpy image, return loose text tokens.

        ``use_cls=False`` disables the per-line angle classifier where
        the engine has one. Orientation detection relies on this: with
        the classifier off, upside-down text recognizes as garbage,
        which is exactly the signal that separates 0° from 180°.
        """

    def ocr_table(self, image: np.ndarray) -> Optional[list[list[Optional[Cell]]]]:
        """Return a cell grid directly, or None if unsupported."""
        return None
