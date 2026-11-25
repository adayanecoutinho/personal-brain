"""Read-only queries over the index. Every result carries its source.

Queries are never logged (docs/adr/007-no-content-in-logs.md).
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

MAX_LIMIT = 20
_TOKEN = re.compile(r"\w+", re.UNICODE)


def _fts_query(text: str) -> str | None:
    """Turn free text into a safe FTS5 query: every word quoted, all words required.

    Quoting each token means user input can never be interpreted as FTS5 syntax.
    """
    tokens = _TOKEN.findall(text)
    if not tokens:
        return None
    return " ".join(f'"{token}"' for token in tokens)


def _connect(db_path: Path) -> sqlite3.Connection:
    # Read-only connection: the query layer cannot modify the index.
    conn = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def search(db_path: Path, query: str, limit: int = 5) -> list[dict]:
    """Full-text search. Results are ordered by relevance (bm25)."""
    fts_query = _fts_query(query)
    if fts_query is None:
        return []
    limit = max(1, min(int(limit), MAX_LIMIT))
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT r.id, r.event_type, r.date, r.review_status, r.title, r.source, r.sha256,
                   snippet(records_fts, 1, '[', ']', '…', 16) AS snippet
            FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ?
            ORDER BY bm25(records_fts)
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def read_entry(db_path: Path, record_id: str) -> dict | None:
    """Return one full record by id, or None if it does not exist."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT id, event_type, date, review_status, title, body, source, sha256"
            " FROM records WHERE id = ?",
            (record_id,),
        ).fetchone()
    return dict(row) if row else None
