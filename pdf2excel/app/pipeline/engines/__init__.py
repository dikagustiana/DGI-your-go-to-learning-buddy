"""Engine registry. The UI enumerates this to build the engine picker."""

from __future__ import annotations

from app.pipeline.engines.base import EngineUnavailableError, OCREngine
from app.pipeline.engines.paddle_engine import PaddleStructureEngine
from app.pipeline.engines.rapidocr_engine import RapidOCREngine

ENGINES: dict[str, type[OCREngine]] = {
    RapidOCREngine.name: RapidOCREngine,
    PaddleStructureEngine.name: PaddleStructureEngine,
}


def available_engines() -> dict[str, bool]:
    """name -> installed? (for the config panel / tooltips)."""
    return {name: cls.is_available() for name, cls in ENGINES.items()}


def create_engine(name: str) -> OCREngine:
    if name not in ENGINES:
        raise KeyError(f"Unknown OCR engine {name!r}; "
                       f"choices: {sorted(ENGINES)}")
    cls = ENGINES[name]
    if not cls.is_available():
        raise EngineUnavailableError(
            f"Engine {name!r} is not installed. {cls.unavailable_hint()}")
    return cls()
