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

Confidentiality notes (see THREAT_MODEL.md): the session file contains
the extracted financial data in plaintext SQLite. ``secure_delete`` is
enabled so deleted rows are zeroed rather than left in free pages, the
WAL is checkpointed+truncated on close so no data lingers in ``-wal``,
and ``delete_files`` implements the "Hapus data kerja" action.

Schema history:
  v1  pages stored a single mutable ``raw`` per cell (edits overwrote
      the OCR original — audit gap).
  v2  cells carry immutable ``ocr_original`` + ``corrected_text`` +
      provenance; session binds to the source PDF by SHA-256
      fingerprint; extraction versions recorded. v1 sessions are
      migrated in place: unedited cells keep their OCR text as the
      original; edited cells have lost it and are marked
      ``legacy_audit_incomplete`` — never silently faked, never
      silently deleted.

Threading: one connection, UI-thread-only in the GUI (worker results
arrive via queued signals) or the single CLI thread.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from typing import Optional

from app import __version__ as APP_VERSION
from app.config import PipelineConfig
from app.pipeline.models import PageResult
from app.versions import (PARSER_VERSION, PIPELINE_VERSION,
                          TABLE_BUILDER_VERSION)

SCHEMA_VERSION = 2
SESSION_SUFFIX = ".p2x"


class SessionError(RuntimeError):
    pass


def pdf_fingerprint(pdf_path: str) -> dict:
    """Identity of the source PDF: size + SHA-256 (mtime only as info)."""
    h = hashlib.sha256()
    with open(pdf_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    stat = os.stat(pdf_path)
    return {"sha256": h.hexdigest(), "size": stat.st_size,
            "mtime": stat.st_mtime}


class SessionStore:
    def __init__(self, path: str):
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        # Zero out deleted content instead of leaving it in free pages —
        # the file holds confidential financial data.
        self._conn.execute("PRAGMA secure_delete=ON")
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
        elif int(stored) < SCHEMA_VERSION:
            self._migrate(int(stored))

    # -------------------------------------------------------- migration

    def _migrate(self, from_version: int) -> None:
        if from_version == 1:
            # v1 -> v2: rewrite each page JSON. Cell.from_dict handles
            # the legacy shape (single mutable "raw"), marking edited
            # cells legacy_audit_incomplete. Nothing is deleted.
            rows = self._conn.execute(
                "SELECT page_number, data FROM pages").fetchall()
            for pno, data in rows:
                page = PageResult.from_dict(json.loads(data))
                self._conn.execute(
                    "UPDATE pages SET data = ? WHERE page_number = ?",
                    (json.dumps(page.to_dict()), pno))
            self.set_meta("migrated_from", str(from_version))
        self.set_meta("schema_version", str(SCHEMA_VERSION))
        self._conn.commit()

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

    @staticmethod
    def delete_files(pdf_path: str) -> list[str]:
        """Remove the session file and its WAL/SHM siblings.

        Returns the paths removed. Best-effort secure hygiene only: on
        SSDs and journaling filesystems, deletion is NOT a forensic
        guarantee (see THREAT_MODEL.md).
        """
        base = SessionStore.path_for_pdf(pdf_path)
        removed = []
        for candidate in (base, base + "-wal", base + "-shm"):
            if os.path.exists(candidate):
                os.remove(candidate)
                removed.append(candidate)
        return removed

    # ------------------------------------------------------ fingerprint

    def bind_pdf(self, pdf_path: str) -> None:
        """Record the source PDF's identity on first use."""
        if self.get_meta("pdf_sha256") is None:
            fp = pdf_fingerprint(pdf_path)
            self.set_meta("pdf_sha256", fp["sha256"])
            self.set_meta("pdf_size", str(fp["size"]))
            self.set_meta("pdf_mtime", str(fp["mtime"]))

    def fingerprint_status(self, pdf_path: str) -> str:
        """'match' | 'mismatch' | 'unbound' for the given PDF."""
        stored = self.get_meta("pdf_sha256")
        if stored is None:
            return "unbound"
        fp = pdf_fingerprint(pdf_path)
        if fp["sha256"] == stored and str(fp["size"]) == self.get_meta("pdf_size"):
            return "match"
        return "mismatch"

    def rebind_pdf(self, pdf_path: str) -> None:
        """Explicitly re-bind after a user-confirmed mismatch."""
        fp = pdf_fingerprint(pdf_path)
        self.set_meta("pdf_sha256", fp["sha256"])
        self.set_meta("pdf_size", str(fp["size"]))
        self.set_meta("pdf_mtime", str(fp["mtime"]))

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
        self.set_meta("app_version", APP_VERSION)
        self.set_meta("parser_version", str(PARSER_VERSION))
        self.set_meta("table_builder_version", str(TABLE_BUILDER_VERSION))
        self.set_meta("pipeline_version", str(PIPELINE_VERSION))

    def load_config(self) -> Optional[PipelineConfig]:
        raw = self.get_meta("config")
        if raw is None:
            return None
        d = json.loads(raw)
        if isinstance(d.get("page_range"), list):  # JSON has no tuples
            d["page_range"] = tuple(d["page_range"])
        return PipelineConfig.from_dict(d)

    def set_model_hashes(self, hashes: dict[str, str]) -> None:
        self.set_meta("model_hashes", json.dumps(hashes, sort_keys=True))

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
        try:
            # Fold the WAL back into the main file and truncate it, so
            # no page data lingers in the -wal sidecar after exit.
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            pass
        self._conn.close()

    def __enter__(self) -> "SessionStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
