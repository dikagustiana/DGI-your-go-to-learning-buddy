from decimal import Decimal

import pytest

from app.locale_id import format_id_number, parse_id_number


@pytest.mark.parametrize("raw, expected", [
    # plain id-ID formats from the sample corpus
    ("130.326.720", Decimal("130326720")),
    ("4.488,00", Decimal("4488.00")),
    ("192.240", Decimal("192240")),
    ("92.240", Decimal("92240")),
    ("0", Decimal("0")),
    ("7", Decimal("7")),
    # missing separators (OCR often drops the dots)
    ("130326720", Decimal("130326720")),
    ("4488,00", Decimal("4488.00")),
    # decimals without grouping (1 or 2 fractional digits)
    ("0,5", Decimal("0.5")),
    ("1234,56", Decimal("1234.56")),
    # currency prefixes
    ("Rp 1.500.000", Decimal("1500000")),
    ("Rp. 1.500.000", Decimal("1500000")),
    ("IDR 250,75", Decimal("250.75")),
    # negatives
    ("-1.234,56", Decimal("-1234.56")),
    ("(1.234,56)", Decimal("-1234.56")),
    ("(Rp 500.000)", Decimal("-500000")),
    ("1.000-", Decimal("-1000")),
    # the ",-" shorthand
    ("1.000,-", Decimal("1000.00")),
    ("Rp 25.000,-", Decimal("25000.00")),
    # trailing ':' and other noise
    ("1.500.000:", Decimal("1500000")),
    ("1.500.000 :", Decimal("1500000")),
    ("|4.488,00|", Decimal("4488.00")),
    ("'192.240'", Decimal("192240")),
    # whitespace injected by OCR between groups
    ("130 .326.720", Decimal("130326720")),
    ("1. 500.000", Decimal("1500000")),
])
def test_parses_id_numbers(raw, expected):
    p = parse_id_number(raw)
    assert p.is_number, f"{raw!r} should parse"
    assert p.value == expected
    assert p.raw == raw  # raw is always preserved verbatim


@pytest.mark.parametrize("raw", [
    "", "   ", None,
    "SALDO AWAL", "PT Maju Jaya",
    "12A34",              # letters inside
    "1.23.456",           # broken grouping — ambiguous, refuse
    "1,234.56",           # US format — refuse rather than misparse
    "12,34,56",           # two commas
    "()", "-", "Rp", ":",
    "01/02/2025",         # dates must not become numbers
    "1234,567",           # 3 fractional digits — ambiguous under id-ID
    "1,234",              # ambiguous: thousands (US) vs fraction (id-ID)
    "001234",             # leading zero — identifier, stays text
    "1234567890123456",   # > 15 digits — identifier, not an amount
])
def test_rejects_non_numbers(raw):
    p = parse_id_number(raw)
    assert not p.is_number, f"{raw!r} must not parse, got {p.value}"


@pytest.mark.parametrize("raw, kind", [
    ("1,234", "ambiguous"),
    ("1234,567", "ambiguous"),
    ("1,234.56", "ambiguous"),
    ("001234", "identifier"),
    ("1234567890123456", "identifier"),
    ("130.326.720", "money"),
    ("7", "integer"),
    ("SALDO", "text"),
])
def test_parse_kind_is_recorded(raw, kind):
    assert parse_id_number(raw).kind == kind


def test_us_format_never_silently_misparsed():
    # The single most dangerous failure: reading 1,234.56 as id-ID would
    # produce garbage. It must come back as text, not a wrong number.
    assert parse_id_number("1,234.56").value is None


def test_format_roundtrip():
    assert format_id_number(Decimal("130326720"), decimals=0) == "130.326.720"
    assert format_id_number(Decimal("4488.00")) == "4.488,00"
    assert format_id_number(Decimal("-1234.5")) == "-1.234,50"
