"""Version identifiers for extraction provenance.

Every extracted page records which pipeline produced it, so an auditor
can tell whether two pages in one workbook came from different logic —
and so a session resumed under a different app version is detectable.

Bump the component version whenever its behavior changes in a way that
could alter extracted values:
  PARSER_VERSION        id-ID number parsing rules (locale_id.py)
  TABLE_BUILDER_VERSION geometric row/column reconstruction
  PIPELINE_VERSION      orientation detection / rasterization behavior
"""

from __future__ import annotations

import hashlib
import json

from app import __version__ as APP_VERSION

PARSER_VERSION = 2          # v2: typed kinds, leading-zero/identifier/ambiguous rules
TABLE_BUILDER_VERSION = 2   # v2: provenance bboxes + stability flags
PIPELINE_VERSION = 2        # v2: orientation margin recorded


def extraction_config_hash(config_dict: dict, engine: str) -> str:
    """Stable hash identifying 'what produced this page'."""
    payload = {
        "app": APP_VERSION,
        "parser": PARSER_VERSION,
        "table_builder": TABLE_BUILDER_VERSION,
        "pipeline": PIPELINE_VERSION,
        "engine": engine,
        "dpi": config_dict.get("dpi"),
        "rotation": config_dict.get("rotation"),
    }
    text = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]
