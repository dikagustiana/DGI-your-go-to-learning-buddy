from app.pipeline.html_table import parse_html_tables


def test_simple_table():
    html = ("<html><body><table>"
            "<tr><td>TANGGAL</td><td>SALDO</td></tr>"
            "<tr><td>01/03/2025</td><td>130.326.720</td></tr>"
            "</table></body></html>")
    tables = parse_html_tables(html)
    assert tables == [[
        ["TANGGAL", "SALDO"],
        ["01/03/2025", "130.326.720"],
    ]]


def test_empty_cells_become_none():
    html = "<table><tr><td>A</td><td></td></tr><tr><td>  </td><td>B</td></tr></table>"
    assert parse_html_tables(html) == [[["A", None], [None, "B"]]]


def test_colspan_shadows_right():
    html = ("<table>"
            "<tr><td colspan=2>HEADER</td><td>X</td></tr>"
            "<tr><td>a</td><td>b</td><td>c</td></tr>"
            "</table>")
    assert parse_html_tables(html) == [[
        ["HEADER", None, "X"],
        ["a", "b", "c"],
    ]]


def test_rowspan_shadows_below():
    html = ("<table>"
            "<tr><td rowspan=\"2\">L</td><td>r1</td></tr>"
            "<tr><td>r2</td></tr>"
            "</table>")
    assert parse_html_tables(html) == [[
        ["L", "r1"],
        [None, "r2"],
    ]]


def test_th_entities_and_br():
    html = ("<table><tr><th>D &amp; K</th><th>Nilai<br>Klaim</th></tr>"
            "<tr><td>1</td><td>2</td></tr></table>")
    assert parse_html_tables(html)[0][0] == ["D & K", "Nilai Klaim"]


def test_multiple_tables_and_junk():
    html = ("<p>ignored</p><table><tr><td>t1</td></tr></table>"
            "<div><table><tr><td>t2</td></tr></table></div>")
    assert parse_html_tables(html) == [[["t1"]], [["t2"]]]


def test_ragged_rows_padded():
    html = ("<table><tr><td>a</td><td>b</td><td>c</td></tr>"
            "<tr><td>only</td></tr></table>")
    assert parse_html_tables(html) == [[
        ["a", "b", "c"],
        ["only", None, None],
    ]]


def test_invalid_spans_ignored():
    html = '<table><tr><td colspan="x" rowspan="">v</td></tr></table>'
    assert parse_html_tables(html) == [[["v"]]]


def test_empty_input():
    assert parse_html_tables("") == []
    assert parse_html_tables("<p>no table</p>") == []


def test_match_confidence_mapping():
    from app.pipeline.engines.paddle_engine import (
        UNMATCHED_CELL_CONFIDENCE, _match_confidence)
    scores = {"192.240": 0.99, "TRF MASUK": 0.80, "PT ABC": 0.70,
              "OK": 0.10}
    assert _match_confidence("192.240", scores) == 0.99
    # space-insensitive exact match
    assert _match_confidence("192. 240", {"192.240": 0.95}) == 0.95
    # merged cell takes the MINIMUM of contained token scores
    assert _match_confidence("TRF MASUK PT ABC", scores) == 0.70
    # short tokens ("OK") never containment-match
    assert _match_confidence("BOOKKEEPING", scores) == UNMATCHED_CELL_CONFIDENCE
    assert _match_confidence("unknown", {}) == UNMATCHED_CELL_CONFIDENCE
