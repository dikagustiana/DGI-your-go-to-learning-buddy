"""Shared datatypes flowing through the pipeline.

Everything is a plain dataclass with dict round-tripping so the session
store (milestone 4) can persist results as JSON without special casing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

from app.locale_id import parse_id_number


@dataclass
class OCRToken:
    """One recognized text fragment with its axis-aligned bbox (pixels)."""

    text: str
    confidence: float
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return self.y1 - self.y0

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "confidence": self.confidence,
            "bbox": [self.x0, self.y0, self.x1, self.y1],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OCRToken":
        x0, y0, x1, y1 = d["bbox"]
        return cls(d["text"], d["confidence"], x0, y0, x1, y1)


@dataclass
class Cell:
    """One table cell: raw OCR string, parsed id-ID value, confidence."""

    raw: str
    confidence: float
    value: Optional[Decimal] = None
    edited: bool = False  # set True when a human corrects it in QA

    @classmethod
    def from_text(cls, raw: str, confidence: float) -> "Cell":
        return cls(raw=raw, confidence=confidence,
                   value=parse_id_number(raw).value)

    def to_dict(self) -> dict:
        return {
            "raw": self.raw,
            "confidence": self.confidence,
            "value": str(self.value) if self.value is not None else None,
            "edited": self.edited,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Cell":
        v = d.get("value")
        return cls(raw=d["raw"], confidence=d["confidence"],
                   value=Decimal(v) if v is not None else None,
                   edited=d.get("edited", False))


@dataclass
class PageResult:
    """Extraction result for one PDF page."""

    page_number: int                     # 1-based
    rotation_applied: int                # degrees clockwise: 0/90/180/270
    rotation_source: str                 # "auto" | "manual" | "forced"
    grid: list[list[Optional[Cell]]] = field(default_factory=list)
    tokens: list[OCRToken] = field(default_factory=list)
    doc_type_label: str = ""             # user-assigned in QA view
    reviewed: bool = False
    error: str = ""

    @property
    def n_rows(self) -> int:
        return len(self.grid)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.grid), default=0)

    def to_dict(self) -> dict:
        return {
            "page_number": self.page_number,
            "rotation_applied": self.rotation_applied,
            "rotation_source": self.rotation_source,
            "grid": [[c.to_dict() if c else None for c in row] for row in self.grid],
            "tokens": [t.to_dict() for t in self.tokens],
            "doc_type_label": self.doc_type_label,
            "reviewed": self.reviewed,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PageResult":
        return cls(
            page_number=d["page_number"],
            rotation_applied=d["rotation_applied"],
            rotation_source=d["rotation_source"],
            grid=[[Cell.from_dict(c) if c else None for c in row]
                  for row in d.get("grid", [])],
            tokens=[OCRToken.from_dict(t) for t in d.get("tokens", [])],
            doc_type_label=d.get("doc_type_label", ""),
            reviewed=d.get("reviewed", False),
            error=d.get("error", ""),
        )
