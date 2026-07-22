"""Offscreen tests for session integration in the main window.

A tiny real PDF is generated per test (blank page — no OCR runs here);
results are injected into the session store directly, then the window
is opened to verify the resume path, and user actions are checked to
persist. QMessageBox prompts are monkeypatched.
"""

import os
from decimal import Decimal

import pytest

pytest.importorskip("PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.pipeline.models import Cell, PageResult  # noqa: E402
from app.session import SessionStore  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def blank_pdf(tmp_path):
    import fitz
    path = str(tmp_path / "doc.pdf")
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(path)
    doc.close()
    return path


def stored_result(pno=1, reviewed=False, label="faktur"):
    return PageResult(
        page_number=pno, rotation_applied=90, rotation_source="auto",
        grid=[[Cell.from_text("192.240", 0.55)]],
        doc_type_label=label, reviewed=reviewed)


def make_window(qapp, monkeypatch, answer=QMessageBox.StandardButton.Yes):
    from app.gui import main_window as mw
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: answer))
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: answer))
    win = mw.MainWindow()
    return win


def test_resume_yes_restores_results(qapp, monkeypatch, blank_pdf):
    with SessionStore.for_pdf(blank_pdf) as s:
        s.save_page(stored_result(1, reviewed=True))
        s.save_page(stored_result(2, label="nota debet"))

    win = make_window(qapp, monkeypatch)
    win.load_pdf(blank_pdf)
    try:
        assert set(win._results) == {1, 2}
        assert win._results[1].reviewed is True
        assert win._results[1].grid[0][0].value == Decimal("192240")
        assert win._known_labels == {"faktur", "nota debet"}
        assert "✓" in win.page_list.item(0).text()
        assert "[nota debet]" in win.page_list.item(1).text()
    finally:
        win.close()


def test_resume_no_discards_session(qapp, monkeypatch, blank_pdf):
    with SessionStore.for_pdf(blank_pdf) as s:
        s.save_page(stored_result(1))

    win = make_window(qapp, monkeypatch, answer=QMessageBox.StandardButton.No)
    win.load_pdf(blank_pdf)
    try:
        assert win._results == {}
        with SessionStore.for_pdf(blank_pdf) as s:
            assert s.summary() == (0, 0)     # cleared on disk too
    finally:
        win.close()


def test_review_actions_persist_to_disk(qapp, monkeypatch, blank_pdf):
    with SessionStore.for_pdf(blank_pdf) as s:
        s.save_page(stored_result(1))

    win = make_window(qapp, monkeypatch)
    win.load_pdf(blank_pdf)
    try:
        win.page_list.setCurrentRow(0)
        qapp.processEvents()
        # correct the known misread, relabel, mark reviewed
        win.review.table.item(0, 0).setText("1.192.240")
        win.review.label_combo.setCurrentText("rekening koran")
        win.review.reviewed_check.setChecked(True)
    finally:
        win.close()

    with SessionStore.for_pdf(blank_pdf) as s:   # fresh connection
        page = s.load_pages()[1]
    assert page.grid[0][0].raw == "1.192.240"
    assert page.grid[0][0].value == Decimal("1192240")
    assert page.grid[0][0].edited is True
    assert page.doc_type_label == "rekening koran"
    assert page.reviewed is True


def test_no_session_file_no_prompt(qapp, monkeypatch, blank_pdf):
    calls = []
    from PySide6.QtWidgets import QMessageBox as MB
    monkeypatch.setattr(MB, "question", staticmethod(
        lambda *a, **k: calls.append(a) or MB.StandardButton.Yes))
    monkeypatch.setattr(MB, "warning", staticmethod(
        lambda *a, **k: MB.StandardButton.Yes))
    from app.gui.main_window import MainWindow
    win = MainWindow()
    win.load_pdf(blank_pdf)
    try:
        assert calls == []               # no resume prompt for a fresh PDF
        assert win._store is not None    # but the store is live
    finally:
        win.close()
