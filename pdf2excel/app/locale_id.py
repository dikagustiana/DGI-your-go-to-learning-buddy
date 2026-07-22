"""id-ID number parsing — conservative and context-aware.

Indonesian corporate documents write numbers with a dot as the thousands
separator and a comma as the decimal separator: 130.326.720 and
4.488,00. US-locale parsing silently corrupts these values, so every
numeric cell goes through this module and nothing else.

Named ``locale_id`` (not ``locale``) to avoid shadowing the stdlib module.

Design rules (finance bias — a wrong number is worse than no number):

* Only parse when the string is UNAMBIGUOUSLY a number under id-ID
  rules; everything else stays text, with the rejection reason recorded
  for the audit trail.
* Identifiers are never numbers: leading zeros (``001234`` — account /
  voucher numbers) and very long digit runs (> 15 digits — beyond both
  plausible amounts and exact float/Excel representation) are kept as
  text with kind ``identifier``.
* Currency fractions are 1 or 2 digits. A comma followed by 3+ digits
  (``1,234``) is AMBIGUOUS — it reads as thousands to a US-trained eye
  and as a fraction under id-ID — so it is rejected as ambiguous rather
  than guessed. (A column-schema layer may later resolve these.)
* US format ``1,234.56`` is rejected, never misparsed.
* OCR sometimes injects spaces between digit groups; those parse, but
  the reason records the repair so the anomaly framework can flag it.

The result carries ``kind`` and ``reason`` so both the QA UI and the
Audit worksheet can show *why* a cell did or did not become a number.
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
#   integer part with optional dot-grouping, optional ",d" / ",dd" decimals.
_ID_NUMBER_RE = re.compile(
    r"""^
    (?P<int>\d{1,3}(?:\.\d{3})*|\d+)   # 130.326.720 | 130326720
    (?:,(?P<frac>\d+))?                # ,00
    $""",
    re.VERBOSE,
)

#: digit runs longer than this are identifiers, not amounts (also the
#: limit of exact double/Excel representation)
MAX_NUMBER_DIGITS = 15

# Parse kinds
KIND_MONEY = "money"          # had decimals or grouping
KIND_INTEGER = "integer"      # plain digits (quantities, counts)
KIND_IDENTIFIER = "identifier"  # digit-ish but must stay text
KIND_AMBIGUOUS = "ambiguous"  # looks numeric but format is ambiguous
KIND_TEXT = "text"            # everything else


@dataclass(frozen=True)
class ParsedNumber:
    """Result of an id-ID parse. ``value`` is None when not a number.

    ``kind`` classifies the string; ``reason`` explains a rejection or
    records a repair (e.g. whitespace removed inside digit groups) so
    the decision is auditable.
    """

    raw: str
    value: Optional[Decimal]
    kind: str = KIND_TEXT
    reason: str = ""

    @property
    def is_number(self) -> bool:
        return self.value is not None


def _reject(raw: str, kind: str, reason: str) -> ParsedNumber:
    return ParsedNumber(raw=raw, value=None, kind=kind, reason=reason)


def parse_id_number(raw: str) -> ParsedNumber:
    """Parse ``raw`` as an id-ID formatted number.

    Handles: dot thousands + comma decimals, currency prefixes (Rp/IDR),
    negatives as leading '-' or accounting parentheses, the Indonesian
    ",-" suffix meaning ",00", and stray trailing/leading noise
    characters.
    """
    if raw is None:
        return _reject("", KIND_TEXT, "empty")

    s = raw.strip()
    original = raw
    if not s:
        return _reject(original, KIND_TEXT, "empty")

    repairs: list[str] = []

    s = s.strip(_LEADING_NOISE + " ").rstrip(_TRAILING_NOISE + " ")
    if s != raw.strip():
        repairs.append("noise-stripped")
    if not s:
        return _reject(original, KIND_TEXT, "only-noise")

    negative = False

    # Accounting negatives: (1.234,56)
    if s.startswith("(") and s.endswith(")"):
        negative = True
        s = s[1:-1].strip()

    if _CURRENCY_RE.match(s):
        s = _CURRENCY_RE.sub("", s).strip()
        repairs.append("currency-prefix")

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
        repairs.append("comma-dash-suffix")

    # OCR sometimes injects spaces between digit groups: "130 .326.720".
    if re.search(r"\s", s):
        s = re.sub(r"\s+", "", s)
        repairs.append("inner-whitespace-removed")

    if not s:
        return _reject(original, KIND_TEXT, "only-noise")

    # US format 1,234.56 (comma groups + dot decimals): refuse loudly.
    if re.match(r"^\d{1,3}(?:,\d{3})+(?:\.\d+)?$", s):
        return _reject(original, KIND_AMBIGUOUS, "us-format")

    m = _ID_NUMBER_RE.match(s)
    if not m:
        return _reject(original, KIND_TEXT, "not-a-number")

    int_part_raw = m.group("int")
    frac_part = m.group("frac")
    int_part = int_part_raw.replace(".", "")

    # Leading zero => identifier (account/voucher numbers), except a
    # bare "0" or "0,xx".
    if len(int_part) > 1 and int_part.startswith("0"):
        return _reject(original, KIND_IDENTIFIER, "leading-zero")

    # Very long digit runs are identifiers, not amounts — and exceed
    # exact float/Excel representation.
    total_digits = len(int_part) + len(frac_part or "")
    if total_digits > MAX_NUMBER_DIGITS:
        return _reject(original, KIND_IDENTIFIER, "too-many-digits")

    # Currency fractions are 1 or 2 digits. ",234" is ambiguous:
    # thousands to a US eye, fraction under id-ID. Refuse to guess.
    if frac_part is not None and len(frac_part) > 2:
        return _reject(original, KIND_AMBIGUOUS, "fractional-digits")

    text = int_part + ("." + frac_part if frac_part else "")
    try:
        value = Decimal(text)
    except InvalidOperation:  # pragma: no cover - regex should prevent this
        return _reject(original, KIND_TEXT, "not-a-number")

    if negative:
        value = -value

    kind = KIND_MONEY if (frac_part is not None or "." in int_part_raw) \
        else KIND_INTEGER
    return ParsedNumber(raw=original, value=value, kind=kind,
                        reason="+".join(repairs))


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
