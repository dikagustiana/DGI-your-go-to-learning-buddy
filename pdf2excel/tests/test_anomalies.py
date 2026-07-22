"""Regression tests for the anomaly framework and validators (Fase 2)."""

from app.pipeline.anomalies import analyze_page, cross_page_anomalies
from app.pipeline.models import Cell, PageResult
from app.pipeline.validators import run_validators


def mk(text, conf=0.95):
    return Cell.from_text(text, conf)


def page(grid, label="", margin=-1.0, flags=None):
    return PageResult(page_number=1, rotation_applied=0, rotation_source="auto",
                      grid=grid, doc_type_label=label, orientation_margin=margin,
                      structure_flags=flags or [], dpi=300)


def codes(anoms):
    return {a.code for a in anoms}


def test_ambiguous_number_is_blocker():
    p = page([[mk("Total"), mk("1,234")]])   # ambiguous under id-ID
    anoms = analyze_page(p)
    amb = [a for a in anoms if a.code == "ambiguous-number"]
    assert amb and amb[0].severity == "blocker"


def test_numeric_gap_flagged():
    # A column with ≥3 numbers is a numeric column; a blank among them
    # may be a dropped amount.
    grid = [[mk("A"), mk("1.000")],
            [mk("B"), mk("2.000")],
            [mk("C"), mk("3.000")],
            [mk("D"), None]]            # empty cell in a numeric column
    assert "numeric-gap" in codes(analyze_page(page(grid)))


def test_magnitude_outlier_flagged():
    grid = [[mk(str(v))] for v in
            ["1.000", "1.100", "950", "1.050", "1.000.000"]]
    # convert to id-ID: use dotted thousands
    grid = [[mk("1.000")], [mk("1.100")], [mk("950")], [mk("1.050")],
            [mk("9.999.999")]]
    assert "magnitude-outlier" in codes(analyze_page(page(grid)))


def test_low_orientation_margin_flagged():
    p = page([[mk("x"), mk("y")]], margin=1.2)
    assert "orientation-low-margin" in codes(analyze_page(p))


def test_structure_flag_becomes_anomaly():
    p = page([[mk("x")]], flags=["row-banding-unstable"])
    assert any(a.code.startswith("structure-") for a in analyze_page(p))


def test_edited_cell_not_flagged():
    c = mk("1,234")                     # would be ambiguous...
    c.apply_correction("1.234")         # ...but a human fixed it
    assert "ambiguous-number" not in codes(analyze_page(page([[mk("t"), c]])))


def test_running_balance_validator_detects_mismatch():
    # saldo column (rightmost). Row 3's balance is wrong on purpose.
    grid = [
        [mk("01/03"), mk("0"), mk("1.000.000")],       # saldo 1,000,000
        [mk("02/03"), mk("500.000"), mk("1.500.000")], # +500k ok
        [mk("03/03"), mk("200.000"), mk("1.900.000")], # +200k => should be 1.7M
        [mk("04/03"), mk("100.000"), mk("2.000.000")], # +100k ok vs 1.9M
    ]
    anoms = run_validators("rekening koran", grid)
    assert any(a.code == "balance-mismatch" and a.severity == "blocker"
               for a in anoms)


def test_running_balance_silent_when_layout_mismatch():
    # Random non-balance grid must not produce false balance alarms.
    grid = [[mk("apel"), mk("2"), mk("merah")],
            [mk("jeruk"), mk("5"), mk("oranye")],
            [mk("pisang"), mk("3"), mk("kuning")]]
    assert not [a for a in run_validators("rekening koran", grid)
                if a.code == "balance-mismatch"]


def test_detail_total_validator():
    grid = [
        [mk("Barang A"), mk("100.000")],
        [mk("Barang B"), mk("200.000")],
        [mk("TOTAL"), mk("500.000")],       # should be 300.000
    ]
    anoms = run_validators("faktur", grid)
    assert any(a.code == "total-mismatch" for a in anoms)


def test_cross_page_column_count_difference():
    p1 = PageResult(1, 0, "auto", grid=[[mk("a"), mk("b")]],
                    doc_type_label="faktur")
    p2 = PageResult(2, 0, "auto", grid=[[mk("a"), mk("b")]],
                    doc_type_label="faktur")
    p3 = PageResult(3, 0, "auto", grid=[[mk("a"), mk("b"), mk("c")]],
                    doc_type_label="faktur")
    extra = cross_page_anomalies([p1, p2, p3])
    assert 3 in extra and any(a.code == "column-count-differs"
                              for a in extra[3])
