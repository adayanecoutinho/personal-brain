"""Read-only queries over the index. Every result carries its source.

`allowed_domains` is the scope of the caller: records outside it are invisible,
including whether they exist (docs/adr/011-domains-and-scopes.md).
Queries are never logged (docs/adr/007-no-content-in-logs.md).
Prefix matching, period and status filters: docs/adr/014-prefix-matching-and-filters.md.
"""

from __future__ import annotations

import calendar
import re
import sqlite3
from collections.abc import Iterable
from contextlib import closing
from pathlib import Path

from .records import DATE_PATTERN, REVIEW_STATUSES

MAX_LIMIT = 20
_TOKEN = re.compile(r"\w+", re.UNICODE)

# Prefix matching: a word of PREFIX_MIN_WORD or more letters also matches words that
# share its first max(PREFIX_MIN_STEM, len - PREFIX_TRIM) letters. This lets
# "ginecologista" find "ginecologia" without a language-specific stemmer.
PREFIX_MIN_WORD = 6
PREFIX_MIN_STEM = 5
PREFIX_TRIM = 4


class FilterError(ValueError):
    """Invalid filter value. The message is safe to return to a client."""


def date_bounds(date: str) -> tuple[str, str]:
    """First and last day a partial date can mean: '2026-05' -> ('2026-05-01', '2026-05-31')."""
    if not DATE_PATTERN.match(date):
        raise FilterError("dates must be YYYY, YYYY-MM or YYYY-MM-DD")
    parts = date.split("-")
    if len(parts) == 3:
        return date, date
    year = int(parts[0])
    if len(parts) == 2:
        month = int(parts[1])
        last = calendar.monthrange(year, month)[1]
        return f"{date}-01", f"{date}-{last:02d}"
    return f"{date}-01-01", f"{date}-12-31"


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text)


def _exact_query(tokens: list[str]) -> str:
    """Every word quoted and required. Quoting keeps user input out of FTS5 syntax."""
    return " ".join(f'"{token}"' for token in tokens)


def _prefix_query(tokens: list[str]) -> str | None:
    """Same words, long ones shortened to a stem with a prefix wildcard."""
    parts = []
    changed = False
    for token in tokens:
        if len(token) >= PREFIX_MIN_WORD:
            stem = token[: max(PREFIX_MIN_STEM, len(token) - PREFIX_TRIM)]
            parts.append(f'"{stem}"*')
            changed = True
        else:
            parts.append(f'"{token}"')
    return " ".join(parts) if changed else None


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


def _extra_filters(
    date_from: str | None, date_to: str | None, review_status: str | None
) -> tuple[str, list[str]]:
    where, params = "", []
    # A record matches a period when its own (possibly partial) date overlaps it.
    if date_from:
        where += " AND r.date_end >= ?"
        params.append(date_bounds(date_from)[0])
    if date_to:
        where += " AND r.date_start <= ?"
        params.append(date_bounds(date_to)[1])
    if review_status:
        if review_status not in REVIEW_STATUSES:
            raise FilterError("review_status must be 'pending' or 'confirmed'")
        where += " AND r.review_status = ?"
        params.append(review_status)
    return where, params


def effective_domains(
    allowed: Iterable[str] | None, requested: str | None
) -> list[str] | None:
    """Intersect the caller's scope with an optional requested domain."""
    if requested is None:
        return None if allowed is None else sorted(set(allowed))
    if allowed is not None and requested not in set(allowed):
        return []
    return [requested]


_COLUMNS = (
    "r.id, r.domain, r.event_type, r.date, r.review_status, r.title, r.source, r.sha256"
)


def search(
    db_path: Path,
    query: str,
    limit: int = 5,
    domains: Iterable[str] | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    review_status: str | None = None,
) -> list[dict]:
    """Search records within a scope.

    With words: exact matches first (bm25), then prefix matches to fill the limit.
    Without words but with a filter: every matching record, newest first.
    `domains=None` means no domain restriction.
    """
    limit = max(1, min(int(limit), MAX_LIMIT))
    scope_where, scope_params = _domain_filter(domains)
    filter_where, filter_params = _extra_filters(date_from, date_to, review_status)
    where = scope_where + filter_where
    params = [*scope_params, *filter_params]
    tokens = _tokens(query)

    with closing(_connect(db_path)) as conn:  # sqlite3's own context manager doesn't close
        if not tokens:
            if not filter_where:
                return []  # no words and no filter: nothing to look for
            rows = conn.execute(
                f"SELECT {_COLUMNS}, '' AS snippet FROM records r WHERE 1{where}"
                " ORDER BY r.date_start DESC, r.id LIMIT ?",
                (*params, limit),
            ).fetchall()
            return [dict(row) for row in rows]

        results: list[dict] = []
        seen: set[str] = set()
        for match in (_exact_query(tokens), _prefix_query(tokens)):
            if match is None or len(results) >= limit:
                continue
            rows = conn.execute(
                f"""
                SELECT {_COLUMNS},
                       snippet(records_fts, 1, '[', ']', '…', 16) AS snippet
                FROM records_fts
                JOIN records r ON r.rowid = records_fts.rowid
                WHERE records_fts MATCH ?{where}
                ORDER BY bm25(records_fts)
                LIMIT ?
                """,
                (match, *params, limit),
            ).fetchall()
            for row in rows:
                if row["id"] not in seen and len(results) < limit:
                    seen.add(row["id"])
                    results.append(dict(row))
    return results


def read_entry(
    db_path: Path, record_id: str, domains: Iterable[str] | None = None
) -> dict | None:
    """One full record by id, or None if it doesn't exist or is outside `domains`."""
    where, params = _domain_filter(domains)
    with closing(_connect(db_path)) as conn:  # sqlite3's own context manager doesn't close
        row = conn.execute(
            "SELECT r.id, r.domain, r.event_type, r.date, r.review_status, r.title, r.body,"
            f" r.source, r.sha256 FROM records r WHERE r.id = ?{where}",
            (record_id, *params),
        ).fetchone()
    return dict(row) if row else None
