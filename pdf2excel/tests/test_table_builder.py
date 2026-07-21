from decimal import Decimal

from app.pipeline.models import OCRToken
from app.pipeline.table_builder import build_grid, find_column_bounds, group_rows


def tok(text, x0, y0, x1, y1, conf=0.95):
    return OCRToken(text=text, confidence=conf, x0=x0, y0=y0, x1=x1, y1=y1)


def make_statement_tokens():
    """3-column mini bank statement: date | description | amount."""
    rows = [
        ("01/03/2025", "SETORAN TUNAI", "130.326.720"),
        ("02/03/2025", "BIAYA ADM", "4.488,00"),
        ("03/03/2025", "TRANSFER MASUK", "192.240"),
    ]
    tokens = []
    y = 100
    for date, desc, amount in rows:
        tokens.append(tok(date, 50, y, 250, y + 30))
        # description split into two tokens, as OCR often does
        words = desc.split(" ", 1)
        tokens.append(tok(words[0], 400, y, 550, y + 30))
        if len(words) > 1:
            tokens.append(tok(words[1], 560, y + 2, 700, y + 32))  # slight wobble
        tokens.append(tok(amount, 900, y, 1100, y + 30))
        y += 60
    return tokens


def test_group_rows_bands_by_y():
    rows = group_rows(make_statement_tokens())
    assert len(rows) == 3
    assert all(len(r) in (3, 4) for r in rows)
    # tokens within a row come back left-to-right
    for r in rows:
        assert [t.x0 for t in r] == sorted(t.x0 for t in r)


def test_column_bounds_finds_three_gutters():
    bounds = find_column_bounds(make_statement_tokens())
    assert len(bounds) == 3


def test_build_grid_reconstructs_table():
    grid = build_grid(make_statement_tokens())
    assert len(grid) == 3
    assert all(len(row) == 3 for row in grid)

    assert grid[0][0].raw == "01/03/2025"
    assert grid[0][0].value is None            # dates stay text
    assert grid[1][1].raw == "BIAYA ADM"       # split tokens re-joined
    assert grid[0][2].value == Decimal("130326720")
    assert grid[1][2].value == Decimal("4488.00")
    assert grid[2][2].value == Decimal("192240")


def test_cell_confidence_is_minimum_of_fragments():
    tokens = [
        tok("SETORAN", 100, 10, 200, 40, conf=0.95),
        tok("TUNAI", 210, 10, 300, 40, conf=0.40),
    ]
    grid = build_grid(tokens)
    assert grid[0][0].raw == "SETORAN TUNAI"
    assert grid[0][0].confidence == 0.40


def test_sparse_column_still_detected():
    # amount column populated in only one of three rows
    tokens = [
        tok("A", 50, 100, 150, 130), tok("1.000", 500, 100, 620, 130),
        tok("B", 50, 160, 150, 190),
        tok("C", 50, 220, 150, 250),
    ]
    grid = build_grid(tokens)
    assert all(len(row) == 2 for row in grid)
    assert grid[0][1].value == Decimal("1000")
    assert grid[1][1] is None
    assert grid[2][1] is None


def test_full_width_title_does_not_erase_gutters():
    # A document title spanning columns 1-2 must not merge them.
    tokens = make_statement_tokens()
    tokens.append(tok("PT CONTOH SEJAHTERA - REKENING KORAN", 50, 20, 700, 55))
    bounds = find_column_bounds(tokens)
    assert len(bounds) == 3
    grid = build_grid(tokens)
    # The title still lands in a cell of its own row (by its center x).
    title_row = [c.raw for c in grid[0] if c is not None]
    assert title_row == ["PT CONTOH SEJAHTERA - REKENING KORAN"]
    body = grid[1:]
    assert all(len(row) == 3 for row in body)
    assert body[0][0].raw == "01/03/2025"
    assert body[0][1].raw == "SETORAN TUNAI"


def test_empty_input():
    assert build_grid([]) == []
    assert group_rows([]) == []
    assert find_column_bounds([]) == []
