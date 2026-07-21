"""id-ID number parsing.

Indonesian corporate documents write numbers with a dot as the thousands
separator and a comma as the decimal separator: 130.326.720 and 4.488,00.
US-locale parsing silently corrupts these values, so every numeric cell
goes through this module and nothing else.

Named ``locale_id`` (not ``locale``) to avoid shadowing the stdlib module.

The parser is deliberately conservative: it returns a Decimal only when
the cleaned string is unambiguously a number under id-ID rules, and None
otherwise. The raw OCR string is always preserved by the caller — a None
here just means the cell stays text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

# Noise commonly glued onto numbers by OCR or by the documents themselves:
# trailing colons ("Saldo: 1.000:"), pipes from table rules, stray quotes.
_TRAILING_NOISE = ":;|'\"`*"
_LEADING_NOISE = ":;|'\"`*"

# Currency prefixes seen in the corpus. Case-insensitive.
_CURRENCY_RE = re.compile(r"^\s*(rp\.?|idr)\s*", re.IGNORECASE)

# A number body under id-ID rules after cleanup:
#   integer part with optional dot-grouping, optional ",dd" decimals.
_ID_NUMBER_RE = re.compile(
    r"""^
    (?P<int>\d{1,3}(?:\.\d{3})*|\d+)   # 130.326.720 | 130326720
    (?:,(?P<frac>\d+))?                # ,00
    $""",
    re.VERBOSE,
)


@dataclass(frozen=True)
class ParsedNumber:
    """Result of an id-ID parse. ``value`` is None when not a number."""

    raw: str
    value: Optional[Decimal]

    @property
    def is_number(self) -> bool:
        return self.value is not None


def parse_id_number(raw: str) -> ParsedNumber:
    """Parse ``raw`` as an id-ID formatted number.

    Handles: dot thousands + comma decimals, currency prefixes (Rp/IDR),
    negatives as leading '-' or accounting parentheses, the Indonesian
    ",-" suffix meaning ",00", and stray trailing/leading noise characters.
    Whitespace inside the number (OCR artifact between digit groups) is
    removed before matching.
    """
    if raw is None:
        return ParsedNumber(raw="", value=None)

    s = raw.strip()
    original = raw
    if not s:
        return ParsedNumber(raw=original, value=None)

    s = s.strip(_LEADING_NOISE + " ").rstrip(_TRAILING_NOISE + " ")
    if not s:
        return ParsedNumber(raw=original, value=None)

    negative = False

    # Accounting negatives: (1.234,56)
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    s = _CURRENCY_RE.sub("", s).strip()

    if s.startswith("-"):
        negative = True
        s = s[1:].strip()
    # Trailing minus ("1.000-") also appears on credit-note scans.
    elif s.endswith("-") and not s.endswith(",-"):
        negative = True
        s = s[:-1].strip()

    # "1.000,-" is the conventional shorthand for "1.000,00".
    if s.endswith(",-"):
        s = s[:-2] + ",00"

    # OCR sometimes injects spaces between digit groups: "130 .326.720".
    s = re.sub(r"\s+", "", s)

    if not s:
        return ParsedNumber(raw=original, value=None)

    m = _ID_NUMBER_RE.match(s)
    if not m:
        return ParsedNumber(raw=original, value=None)

    int_part = m.group("int").replace(".", "")
    frac_part = m.group("frac")
    text = int_part + ("." + frac_part if frac_part else "")
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover - regex should prevent this
        return ParsedNumber(raw=original, value=None)

    if negative:
        value = -value
    return ParsedNumber(raw=original, value=value)


def format_id_number(value: Decimal, decimals: int = 2) -> str:
    """Format a Decimal back to id-ID notation (for display, not export)."""
    q = Decimal(10) ** -decimals
    v = value.quantize(q) if decimals > 0 else value.to_integral_value()
    sign = "-" if v < 0 else ""
    v = abs(v)
    int_part, _, frac_part = f"{v:f}".partition(".")
    grouped = "{:,}".format(int(int_part)).replace(",", ".")
    if decimals > 0:
        frac_part = (frac_part or "").ljust(decimals, "0")[:decimals]
        return f"{sign}{grouped},{frac_part}"
    return f"{sign}{grouped}"
