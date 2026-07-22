"""Regression tests for v1→v2 session migration (Fase 1/3)."""

import json
import sqlite3

from app.session import SCHEMA_VERSION, SessionError, SessionStore


def write_v1_session(path, pages):
    """Hand-build a schema-v1 session file (single mutable 'raw' cells)."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE pages (page_number INTEGER PRIMARY KEY, data TEXT)")
    conn.execute("INSERT INTO meta VALUES ('schema_version', '1')")
    for p in pages:
        conn.execute("INSERT INTO pages VALUES (?, ?)",
                     (p["page_number"], json.dumps(p)))
    conn.commit()
    conn.close()


def v1_page(pno, cells):
    return {"page_number": pno, "rotation_applied": 0,
            "rotation_source": "auto", "grid": cells, "tokens": [],
            "doc_type_label": "", "reviewed": False, "error": ""}


def test_unedited_v1_cell_keeps_ocr_as_original(tmp_path):
    path = str(tmp_path / "doc.pdf.p2x")
    write_v1_session(path, [v1_page(1, [[
        {"raw": "130.326.720", "confidence": 0.9,
         "value": "130326720", "edited": False}]])])

    with SessionStore(path) as s:
        assert s.get_meta("schema_version") == str(SCHEMA_VERSION)
        cell = s.load_pages()[1].grid[0][0]
        assert cell.ocr_original == "130.326.720"   # recovered as original
        assert cell.corrected_text is None
        assert not cell.legacy_audit_incomplete


def test_edited_v1_cell_marked_audit_incomplete(tmp_path):
    # An edited v1 cell has already lost its OCR original — we must NOT
    # pretend the current text was the OCR reading.
    path = str(tmp_path / "doc.pdf.p2x")
    write_v1_session(path, [v1_page(1, [[
        {"raw": "192.240", "confidence": 0.9,
         "value": "192240", "edited": True}]])])

    with SessionStore(path) as s:
        cell = s.load_pages()[1].grid[0][0]
        assert cell.ocr_original is None             # not faked
        assert cell.corrected_text == "192.240"
        assert cell.edited is True
        assert cell.legacy_audit_incomplete is True


def test_migration_does_not_delete_pages(tmp_path):
    path = str(tmp_path / "doc.pdf.p2x")
    write_v1_session(path, [
        v1_page(1, [[{"raw": "a", "confidence": 0.9, "value": None,
                      "edited": False}]]),
        v1_page(2, [[{"raw": "b", "confidence": 0.9, "value": None,
                      "edited": False}]]),
    ])
    with SessionStore(path) as s:
        assert set(s.load_pages()) == {1, 2}
        assert s.get_meta("migrated_from") == "1"


def test_newer_schema_rejected(tmp_path):
    path = str(tmp_path / "doc.pdf.p2x")
    s = SessionStore(path)
    s.set_meta("schema_version", "999")
    s.close()
    try:
        SessionStore(path)
        assert False, "should have raised"
    except SessionError:
        pass
