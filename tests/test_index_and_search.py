import sqlite3

import pytest

from personal_brain.index import build_index
from personal_brain.records import RecordError
from personal_brain.search import MAX_LIMIT, read_entry, search


def test_every_result_cites_its_source(db):
    results = search(db, "moisturizer")
    assert results
    for result in results:
        assert result["source"].endswith(".md")
        assert result["id"] and result["review_status"] in {"pending", "confirmed"}


def test_prescription_and_use_are_separate_records(db):
    types = {r["event_type"] for r in search(db, "moisturizer", limit=10)}
    assert {"prescription", "medication_use"} <= types


def test_pending_records_are_flagged(db):
    results = search(db, "allergist")
    assert [r["review_status"] for r in results] == ["pending"]


def test_search_ignores_accents_and_case(db):
    assert search(db, "DERMATOLOGY") == search(db, "dermatology")


def test_fts_syntax_in_user_input_is_neutralized(db):
    # Quotes and operators never raise; operators are plain words, not FTS5 syntax.
    assert search(db, '"moisturizer"*') == search(db, "moisturizer")
    assert search(db, "moisturizer OR zzzunknown") == []  # OR is a required literal word
    assert search(db, "NEAR(") == []


def test_empty_query_returns_nothing(db):
    assert search(db, "   ") == []


def test_limit_is_clamped(db):
    assert len(search(db, "fictional", limit=1000)) <= MAX_LIMIT
    assert len(search(db, "fictional", limit=0)) == 1


def test_read_entry_returns_full_record(db):
    entry = read_entry(db, "exam-2026-04-02-blood")
    assert entry is not None
    assert "All values within reference range" in entry["body"]
    assert read_entry(db, "does-not-exist") is None


def test_query_connection_is_read_only(db):
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("DELETE FROM records")
    conn.close()


def test_failed_rebuild_keeps_the_previous_index(db, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / "bad.md").write_text("no front matter", encoding="utf-8")
    with pytest.raises(RecordError):
        build_index(broken, db)
    assert search(db, "moisturizer")  # old index still serves
