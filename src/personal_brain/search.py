"""Read-only queries over the index. Every result carries its source.

`allowed_domains` is the scope of the caller: records outside it are invisible,
including whether they exist (docs/adr/011-domains-and-scopes.md).
Queries are never logged (docs/adr/007-no-content-in-logs.md).
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
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


def _domain_filter(domains: Iterable[str] | None) -> tuple[str, list[str]]:
    if domains is None:
        return "", []
    domains = sorted(set(domains))
    if not domains:
        return " AND 0", []  # an empty scope sees nothing
    return f" AND r.domain IN ({', '.join('?' for _ in domains)})", domains


def effective_domains(
    allowed: Iterable[str] | None, requested: str | None
) -> list[str] | None:
    """Intersect the caller's scope with an optional requested domain."""
    if requested is None:
        return None if allowed is None else sorted(set(allowed))
    if allowed is not None and requested not in set(allowed):
        return []
    return [requested]


def search(
    db_path: Path,
    query: str,
    limit: int = 5,
    domains: Iterable[str] | None = None,
) -> list[dict]:
    """Full-text search, ordered by relevance (bm25). `domains=None` means no restriction."""
    fts_query = _fts_query(query)
    if fts_query is None:
        return []
    limit = max(1, min(int(limit), MAX_LIMIT))
    where, params = _domain_filter(domains)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT r.id, r.domain, r.event_type, r.date, r.review_status, r.title,
                   r.source, r.sha256,
                   snippet(records_fts, 1, '[', ']', '…', 16) AS snippet
            FROM records_fts
            JOIN records r ON r.rowid = records_fts.rowid
            WHERE records_fts MATCH ?{where}
            ORDER BY bm25(records_fts)
            LIMIT ?
            """,
            (fts_query, *params, limit),
        ).fetchall()
    return [dict(row) for row in rows]


def read_entry(
    db_path: Path, record_id: str, domains: Iterable[str] | None = None
) -> dict | None:
    """One full record by id, or None if it doesn't exist or is outside `domains`."""
    where, params = _domain_filter(domains)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT r.id, r.domain, r.event_type, r.date, r.review_status, r.title, r.body,"
            f" r.source, r.sha256 FROM records r WHERE r.id = ?{where}",
            (record_id, *params),
        ).fetchone()
    return dict(row) if row else None
