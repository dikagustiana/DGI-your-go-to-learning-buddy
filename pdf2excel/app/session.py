"""Resumable session persistence (SQLite).

A 156-page QA pass takes longer than one sitting, so every page result —
extraction, human cell edits, document-type labels, reviewed flags — is
written to a local session file the moment it changes. Closing the app
loses nothing; reopening the same PDF offers to resume.

Storage choice: SQLite over a JSON blob because writes are incremental
(one page at a time, hundreds of times per session) and must survive a
crash mid-write; WAL mode gives atomic per-page saves without rewriting
the whole file.

The session file sits NEXT TO the PDF (``statement.pdf`` →
``statement.pdf.p2x``): it travels with the document, needs no central
registry, and makes it obvious which scans have work in progress. If
the directory is read-only the store fails to open and callers degrade
to no persistence rather than crashing.

Schema (version 1):
  meta(key TEXT PRIMARY KEY, value TEXT)     -- schema_version, config, pdf info
  pages(page_number INTEGER PRIMARY KEY,
        data TEXT NOT NULL)                  -- PageResult as JSON

Everything here is Qt-free; the GUI calls it from the UI thread only
(worker results arrive via signals on the UI thread), and the CLI uses
one connection in one thread, so no cross-thread SQLite issues arise.
"""

from __future__ import annotations

import json
import os
import sqlite3
from typing import Optional

from app.config import PipelineConfig
from app.pipeline.models import PageResult

SCHEMA_VERSION = 1
SESSION_SUFFIX = ".p2x"


class SessionError(RuntimeError):
    pass


class SessionStore:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta ("
            " key TEXT PRIMARY KEY, value TEXT)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS pages ("
            " page_number INTEGER PRIMARY KEY, data TEXT NOT NULL)")
        self._conn.commit()

        stored = self.get_meta("schema_version")
        if stored is None:
            self.set_meta("schema_version", str(SCHEMA_VERSION))
        elif int(stored) > SCHEMA_VERSION:
            raise SessionError(
                f"Session file {path!r} was written by a newer version of "
                f"this app (schema {stored} > {SCHEMA_VERSION}).")

    # ------------------------------------------------------------ paths

    @staticmethod
    def path_for_pdf(pdf_path: str) -> str:
        return pdf_path + SESSION_SUFFIX

    @classmethod
    def for_pdf(cls, pdf_path: str) -> "SessionStore":
        return cls(cls.path_for_pdf(pdf_path))

    @classmethod
    def exists_for_pdf(cls, pdf_path: str) -> bool:
        return os.path.exists(cls.path_for_pdf(pdf_path))

    # ------------------------------------------------------------- meta

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            (key, value))
        self._conn.commit()

    def get_meta(self, key: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def save_config(self, config: PipelineConfig) -> None:
        self.set_meta("config", json.dumps(config.to_dict()))

    def load_config(self) -> Optional[PipelineConfig]:
        raw = self.get_meta("config")
        if raw is None:
            return None
        d = json.loads(raw)
        if isinstance(d.get("page_range"), list):  # JSON has no tuples
            d["page_range"] = tuple(d["page_range"])
        return PipelineConfig.from_dict(d)

    # ------------------------------------------------------------ pages

    def save_page(self, result: PageResult) -> None:
        """Atomic per-page upsert; called on every extraction and edit."""
        self._conn.execute(
            "INSERT OR REPLACE INTO pages (page_number, data) VALUES (?, ?)",
            (result.page_number, json.dumps(result.to_dict())))
        self._conn.commit()

    def load_pages(self) -> dict[int, PageResult]:
        rows = self._conn.execute(
            "SELECT page_number, data FROM pages ORDER BY page_number")
        return {pno: PageResult.from_dict(json.loads(data))
                for pno, data in rows}

    def summary(self) -> tuple[int, int]:
        """(pages stored, pages marked reviewed) — cheap resume prompt info."""
        n = self._conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
        n_rev = self._conn.execute(
            "SELECT COUNT(*) FROM pages "
            "WHERE json_extract(data, '$.reviewed')").fetchone()[0]
        return n, n_rev

    def clear_pages(self) -> None:
        self._conn.execute("DELETE FROM pages")
        self._conn.commit()

    # ---------------------------------------------------------- lifecycle

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
