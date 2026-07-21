"""Parse table HTML (as emitted by PP-StructureV3) into a text grid.

PP-StructureV3's table recognition returns ``pred_html`` — a plain HTML
table, possibly with colspan/rowspan merges. This converts it to a
rectangular ``list[list[str | None]]``: merged cells put their text in
the top-left position of the span and None in the shadowed positions,
matching how the rest of the pipeline treats empty cells.

Stdlib-only (html.parser) so it needs no PaddleOCR install to test.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Optional


class _TableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[dict]]] = []
        self._rows: Optional[list] = None
        self._row: Optional[list] = None
        self._cell: Optional[dict] = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            a = dict(attrs)

            def _span(key):
                try:
                    return max(int(a.get(key) or 1), 1)
                except ValueError:
                    return 1

            self._cell = {"text": "", "colspan": _span("colspan"),
                          "rowspan": _span("rowspan")}
        elif tag == "br" and self._cell is not None:
            self._cell["text"] += " "

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(self._cell)
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell["text"] += data


def _expand_spans(rows: list[list[dict]]) -> list[list[Optional[str]]]:
    """Resolve colspan/rowspan into a rectangular grid."""
    filled: dict[tuple[int, int], Optional[str]] = {}
    n_rows = len(rows)
    for r, row in enumerate(rows):
        c = 0
        for cell in row:
            while (r, c) in filled:
                c += 1
            text = " ".join(cell["text"].split())
            for dr in range(cell["rowspan"]):
                for dc in range(cell["colspan"]):
                    filled.setdefault((r + dr, c + dc), None)
            filled[(r, c)] = text or None
            c += cell["colspan"]
        n_rows = max(n_rows, r + 1)
    if not filled:
        return []
    n_cols = max(c for _, c in filled) + 1
    n_rows = max(n_rows, max(r for r, _ in filled) + 1)
    return [[filled.get((r, c)) for c in range(n_cols)]
            for r in range(n_rows)]


def parse_html_tables(html: str) -> list[list[list[Optional[str]]]]:
    """All tables in ``html``, each as a rectangular text grid."""
    parser = _TableHTMLParser()
    parser.feed(html or "")
    parser.close()
    return [_expand_spans(rows) for rows in parser.tables if rows]
