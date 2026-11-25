"""SQLite FTS5 index built from the records directory.

The index is derived data: it can be deleted and rebuilt at any time without
losing information. A rebuild writes a new file and swaps it in atomically, so a
failed build never replaces a working index. See docs/adr/003-sqlite-fts5-index.md.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .records import load_records

SCHEMA = """
CREATE TABLE records (
    rowid INTEGER PRIMARY KEY,
    id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    date TEXT NOT NULL,
    review_status TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    source TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE VIRTUAL TABLE records_fts USING fts5(
    title,
    body,
    content='records',
    content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
"""


def build_index(records_dir: Path, db_path: Path) -> int:
    """Rebuild the index from `records_dir`. Returns the number of records indexed."""
    records = load_records(records_dir)  # validation happens before anything is written

    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = db_path.with_name(db_path.name + ".building")
    tmp_path.unlink(missing_ok=True)

    conn = sqlite3.connect(tmp_path)
    try:
        conn.executescript(SCHEMA)
        conn.executemany(
            "INSERT INTO records (id, event_type, date, review_status, title, body, source, sha256)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (r.id, r.event_type, r.date, r.review_status, r.title, r.body, r.source, r.sha256)
                for r in records
            ],
        )
        conn.execute("INSERT INTO records_fts(records_fts) VALUES ('rebuild')")
        conn.commit()
    except Exception:
        conn.close()
        tmp_path.unlink(missing_ok=True)
        raise
    conn.close()

    os.replace(tmp_path, db_path)
    return len(records)
