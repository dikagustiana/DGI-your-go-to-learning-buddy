from decimal import Decimal

import pytest

from app.config import PipelineConfig
from app.pipeline.models import Cell, OCRToken, PageResult
from app.session import SessionStore


@pytest.fixture()
def store(tmp_path):
    s = SessionStore(str(tmp_path / "doc.pdf.p2x"))
    yield s
    s.close()


def make_result(pno=1, reviewed=False):
    cell = Cell.from_text("192.240", 0.55)
    cell2 = Cell(raw="4.488,00", confidence=0.9,
                 value=Decimal("4488.00"), edited=True)
    return PageResult(
        page_number=pno, rotation_applied=270, rotation_source="manual",
        grid=[[cell, None], [cell2, Cell.from_text("SALDO", 0.99)]],
        tokens=[OCRToken("192.240", 0.55, 10, 20, 110, 50)],
        doc_type_label="rekening koran", reviewed=reviewed)


def test_page_roundtrip_preserves_everything(store):
    store.save_page(make_result())
    loaded = store.load_pages()[1]

    assert loaded.rotation_applied == 270
    assert loaded.rotation_source == "manual"
    assert loaded.doc_type_label == "rekening koran"
    assert loaded.grid[0][1] is None
    cell = loaded.grid[0][0]
    assert cell.raw == "192.240"
    assert cell.value == Decimal("192240")        # Decimal survives JSON
    assert cell.confidence == 0.55
    edited = loaded.grid[1][0]
    assert edited.edited is True                  # human edits never lost
    assert edited.value == Decimal("4488.00")
    tok = loaded.tokens[0]
    assert (tok.text, tok.x0, tok.y1) == ("192.240", 10, 50)


def test_save_page_upserts(store):
    store.save_page(make_result())
    updated = make_result(reviewed=True)
    updated.grid[0][0].raw = "corrected"
    store.save_page(updated)

    pages = store.load_pages()
    assert len(pages) == 1
    assert pages[1].reviewed is True
    assert pages[1].grid[0][0].raw == "corrected"


def test_summary_counts_reviewed(store):
    store.save_page(make_result(1, reviewed=True))
    store.save_page(make_result(2, reviewed=False))
    store.save_page(make_result(3, reviewed=True))
    assert store.summary() == (3, 2)


def test_clear_pages(store):
    store.save_page(make_result())
    store.clear_pages()
    assert store.load_pages() == {}
    assert store.summary() == (0, 0)


def test_config_roundtrip(store):
    config = PipelineConfig(dpi=400, engine="rapidocr", rotation=90,
                            page_range=(3, 17), output_layout="merged_by_label")
    store.save_config(config)
    loaded = store.load_config()
    assert loaded == config          # dataclass equality, incl. tuple range


def test_load_config_missing_returns_none(store):
    assert store.load_config() is None


def test_persistence_across_connections(tmp_path):
    path = str(tmp_path / "doc.pdf.p2x")
    with SessionStore(path) as s:
        s.save_page(make_result(reviewed=True))
    with SessionStore(path) as s:    # fresh connection = app restart
        pages = s.load_pages()
        assert pages[1].reviewed is True
        assert pages[1].grid[1][0].edited is True


def test_path_helpers(tmp_path):
    pdf = str(tmp_path / "statement.pdf")
    assert SessionStore.path_for_pdf(pdf) == pdf + ".p2x"
    assert not SessionStore.exists_for_pdf(pdf)
    SessionStore.for_pdf(pdf).close()
    assert SessionStore.exists_for_pdf(pdf)


def test_newer_schema_rejected(tmp_path):
    from app.session import SessionError
    path = str(tmp_path / "doc.pdf.p2x")
    s = SessionStore(path)
    s.set_meta("schema_version", "999")
    s.close()
    with pytest.raises(SessionError):
        SessionStore(path)
