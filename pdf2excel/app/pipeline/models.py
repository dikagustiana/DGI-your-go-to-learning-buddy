"""Shared datatypes flowing through the pipeline.

Audit-trail contract (finance requirement, do not weaken):

* ``Cell.ocr_original`` is what the OCR engine read. It is IMMUTABLE
  after extraction — human corrections go to ``corrected_text`` and
  never overwrite it. ``effective_text`` is what the reader should see
  (correction if present, else the OCR original).
* Cells carry provenance: the source bounding box (pixels of the
  rotation-corrected page image at ``PageResult.dpi``), when they were
  edited and by which local reviewer.
* Legacy sessions (schema v1 stored a single mutable ``raw``) migrate
  with ``legacy_audit_incomplete=True`` on cells whose original OCR text
  was already lost to an edit — the app never pretends to have an
  original it doesn't.

Everything is a plain dataclass with dict round-tripping so the session
store can persist results as JSON without special casing.
"""

from __future__ import annotations

import getpass
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app.locale_id import KIND_TEXT, parse_id_number


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def local_reviewer() -> str:
    """Best-effort local identity for the audit trail (never sent anywhere)."""
    try:
        return getpass.getuser()
    except Exception:
        return ""


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
    """One table cell with an immutable OCR original + human correction."""

    ocr_original: Optional[str]          # None: legacy-lost or human-inserted
    confidence: float
    corrected_text: Optional[str] = None
    value: Optional[Decimal] = None      # parsed from effective_text
    parse_kind: str = KIND_TEXT
    parse_reason: str = ""
    edited: bool = False
    edited_at: Optional[str] = None      # ISO-8601 UTC
    reviewer: str = ""
    bbox: Optional[tuple[float, float, float, float]] = None
    legacy_audit_incomplete: bool = False

    # ------------------------------------------------------------ views

    @property
    def effective_text(self) -> str:
        if self.corrected_text is not None:
            return self.corrected_text
        return self.ocr_original or ""

    @property
    def raw(self) -> str:
        """Display text (= effective_text). Read-only by design: writes
        must go through apply_correction so ocr_original survives."""
        return self.effective_text

    # ------------------------------------------------------- lifecycle

    @classmethod
    def from_text(cls, text: str, confidence: float,
                  bbox: Optional[tuple[float, float, float, float]] = None
                  ) -> "Cell":
        p = parse_id_number(text)
        return cls(ocr_original=text, confidence=confidence, value=p.value,
                   parse_kind=p.kind, parse_reason=p.reason, bbox=bbox)

    @classmethod
    def human_created(cls, text: str, reviewer: str = "") -> "Cell":
        """A cell typed into an empty slot by a reviewer (no OCR source)."""
        p = parse_id_number(text)
        return cls(ocr_original=None, confidence=1.0, corrected_text=text,
                   value=p.value, parse_kind=p.kind, parse_reason=p.reason,
                   edited=True, edited_at=_now_iso(),
                   reviewer=reviewer or local_reviewer())

    def apply_correction(self, text: str, reviewer: str = "") -> None:
        """Record a human correction WITHOUT touching ocr_original."""
        p = parse_id_number(text)
        self.corrected_text = text
        self.value = p.value
        self.parse_kind = p.kind
        self.parse_reason = p.reason
        self.edited = True
        self.edited_at = _now_iso()
        self.reviewer = reviewer or local_reviewer()

    # --------------------------------------------------- serialization

    def to_dict(self) -> dict:
        return {
            "ocr_original": self.ocr_original,
            "confidence": self.confidence,
            "corrected_text": self.corrected_text,
            "value": str(self.value) if self.value is not None else None,
            "parse_kind": self.parse_kind,
            "parse_reason": self.parse_reason,
            "edited": self.edited,
            "edited_at": self.edited_at,
            "reviewer": self.reviewer,
            "bbox": list(self.bbox) if self.bbox else None,
            "legacy_audit_incomplete": self.legacy_audit_incomplete,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Cell":
        if "ocr_original" not in d and "raw" in d:
            return cls.from_legacy_dict(d)
        v = d.get("value")
        bbox = d.get("bbox")
        return cls(
            ocr_original=d.get("ocr_original"),
            confidence=d["confidence"],
            corrected_text=d.get("corrected_text"),
            value=Decimal(v) if v is not None else None,
            parse_kind=d.get("parse_kind", KIND_TEXT),
            parse_reason=d.get("parse_reason", ""),
            edited=d.get("edited", False),
            edited_at=d.get("edited_at"),
            reviewer=d.get("reviewer", ""),
            bbox=tuple(bbox) if bbox else None,
            legacy_audit_incomplete=d.get("legacy_audit_incomplete", False),
        )

    @classmethod
    def from_legacy_dict(cls, d: dict) -> "Cell":
        """Schema-v1 cell: a single mutable ``raw`` string.

        If it was edited, the OCR original is unrecoverable — say so
        (legacy_audit_incomplete) instead of pretending.
        """
        v = d.get("value")
        value = Decimal(v) if v is not None else None
        edited = d.get("edited", False)
        raw = d.get("raw", "")
        if edited:
            return cls(ocr_original=None, confidence=d.get("confidence", 0.0),
                       corrected_text=raw, value=value, edited=True,
                       legacy_audit_incomplete=True)
        return cls(ocr_original=raw, confidence=d.get("confidence", 0.0),
                   value=value)


@dataclass
class Anomaly:
    """A machine-detected reason to distrust part of a page."""

    code: str                 # stable identifier, e.g. "numeric-gap"
    message: str              # plain-Indonesian, shown to reviewers
    severity: str = "warning"  # "warning" | "blocker"
    row: Optional[int] = None  # 0-based grid coordinates, when cell-level
    col: Optional[int] = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message,
                "severity": self.severity, "row": self.row, "col": self.col}

    @classmethod
    def from_dict(cls, d: dict) -> "Anomaly":
        return cls(code=d["code"], message=d["message"],
                   severity=d.get("severity", "warning"),
                   row=d.get("row"), col=d.get("col"))


@dataclass
class PageResult:
    """Extraction result for one PDF page."""

    page_number: int                     # 1-based
    rotation_applied: int                # degrees clockwise: 0/90/180/270
    rotation_source: str                 # "auto" | "manual" | "forced"
    grid: list[list[Optional[Cell]]] = field(default_factory=list)
    tokens: list[OCRToken] = field(default_factory=list)
    doc_type_label: str = ""             # user-assigned in QA
    reviewed: bool = False
    reviewed_at: Optional[str] = None
    error: str = ""
    dpi: int = 0                         # raster DPI the bboxes refer to
    orientation_margin: float = -1.0     # score ratio best/runner-up (-1 n/a)
    config_hash: str = ""                # extraction provenance (versions.py)
    engine: str = ""
    anomalies: list[Anomaly] = field(default_factory=list)
    structure_flags: list[str] = field(default_factory=list)
    needs_reextraction: bool = False     # reviewer marked page as bad

    @property
    def n_rows(self) -> int:
        return len(self.grid)

    @property
    def n_cols(self) -> int:
        return max((len(r) for r in self.grid), default=0)

    def set_reviewed(self, reviewed: bool) -> None:
        self.reviewed = reviewed
        self.reviewed_at = _now_iso() if reviewed else None

    def blocker_anomalies(self) -> list[Anomaly]:
        return [a for a in self.anomalies if a.severity == "blocker"]

    def to_dict(self) -> dict:
        return {
            "schema": 2,
            "page_number": self.page_number,
            "rotation_applied": self.rotation_applied,
            "rotation_source": self.rotation_source,
            "grid": [[c.to_dict() if c else None for c in row] for row in self.grid],
            "tokens": [t.to_dict() for t in self.tokens],
            "doc_type_label": self.doc_type_label,
            "reviewed": self.reviewed,
            "reviewed_at": self.reviewed_at,
            "error": self.error,
            "dpi": self.dpi,
            "orientation_margin": self.orientation_margin,
            "config_hash": self.config_hash,
            "engine": self.engine,
            "anomalies": [a.to_dict() for a in self.anomalies],
            "structure_flags": self.structure_flags,
            "needs_reextraction": self.needs_reextraction,
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
            reviewed_at=d.get("reviewed_at"),
            error=d.get("error", ""),
            dpi=d.get("dpi", 0),
            orientation_margin=d.get("orientation_margin", -1.0),
            config_hash=d.get("config_hash", ""),
            engine=d.get("engine", ""),
            anomalies=[Anomaly.from_dict(a) for a in d.get("anomalies", [])],
            structure_flags=d.get("structure_flags", []),
            needs_reextraction=d.get("needs_reextraction", False),
        )
