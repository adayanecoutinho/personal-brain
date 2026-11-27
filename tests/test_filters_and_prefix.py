import asyncio

import pytest

from personal_brain.search import FilterError, date_bounds, search
from personal_brain.server import create_server


@pytest.mark.parametrize(
    "date, expected",
    [
        ("2026-05-04", ("2026-05-04", "2026-05-04")),
        ("2026-05", ("2026-05-01", "2026-05-31")),
        ("2024-02", ("2024-02-01", "2024-02-29")),  # leap year
        ("2025", ("2025-01-01", "2025-12-31")),
    ],
)
def test_date_bounds(date, expected):
    assert date_bounds(date) == expected


def test_invalid_filter_values_raise(db):
    with pytest.raises(FilterError):
        search(db, "", date_from="05/2026")
    with pytest.raises(FilterError):
        search(db, "", review_status="maybe")


def test_prefix_finds_word_variants(db):
    ids = [r["id"] for r in search(db, "dermatologist")]
    assert ids == ["enc-2026-03-12-derm"]


def test_exact_matches_come_before_prefix_matches(db):
    # "gastroenterology" matches exactly; the prefix pass must not reorder them.
    exact = [r["id"] for r in search(db, "gastroenterology")]
    assert set(exact[:2]) == {"enc-2026-01-20-gastro", "enc-2026-05-08-gastro"}


def test_short_words_are_not_stemmed(db):
    assert search(db, "MRI") == []


def test_partial_date_matches_overlapping_period(db):
    # use-2026-03-moisturizer is dated 2026-03: it overlaps a filter on 2026-03-15.
    ids = {r["id"] for r in search(db, "", date_from="2026-03-15", date_to="2026-03-15")}
    assert "use-2026-03-moisturizer" in ids
    assert "enc-2026-03-12-derm" not in ids


def test_filter_only_search_lists_newest_first(db):
    results = search(db, "", limit=20, domains=["health"], date_from="2026")
    dates = [r["date"] for r in results]
    assert dates == sorted(dates, reverse=True)


def test_no_words_and_no_filter_returns_nothing(db):
    assert search(db, "   ") == []


def test_status_filter(db):
    results = search(db, "", limit=20, review_status="pending")
    assert results and {r["review_status"] for r in results} == {"pending"}


def test_filters_never_widen_scope(db):
    assert search(db, "", limit=20, domains=["training"], review_status="pending") == []


def test_tool_reports_invalid_filter(db):
    server = create_server(db)
    result = str(asyncio.run(server.call_tool("search", {"date_from": "yesterday"})))
    assert "invalid_filter" in result
