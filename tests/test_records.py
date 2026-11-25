import pytest

from personal_brain.records import RecordError, load_records, parse_record

VALID = """---
id: enc-2026-01-01-test
event_type: encounter
date: 2026-01-01
review_status: confirmed
title: Test
---
Body text.
"""


def test_parses_valid_record():
    record = parse_record(VALID, "a.md")
    assert record.id == "enc-2026-01-01-test"
    assert record.body == "Body text."
    assert record.source == "a.md"
    assert len(record.sha256) == 64


@pytest.mark.parametrize(
    "replace, expected",
    [
        (("event_type: encounter", "event_type: rumor"), "unknown event_type"),
        (("review_status: confirmed", "review_status: maybe"), "unknown review_status"),
        (("date: 2026-01-01", "date: 01/01/2026"), "date must be"),
        (("id: enc-2026-01-01-test", "id: Bad Id"), "invalid id"),
        (("title: Test\n", ""), "missing required fields: title"),
    ],
)
def test_rejects_invalid_records(replace, expected):
    text = VALID.replace(*replace)
    with pytest.raises(RecordError, match=expected):
        parse_record(text, "a.md")


def test_rejects_file_without_front_matter():
    with pytest.raises(RecordError, match="missing YAML front matter"):
        parse_record("just text", "a.md")


def test_partial_dates_keep_their_precision():
    record = parse_record(VALID.replace("date: 2026-01-01", "date: 2026-01"), "a.md")
    assert record.date == "2026-01"


def test_duplicate_ids_are_rejected(tmp_path):
    (tmp_path / "a.md").write_text(VALID, encoding="utf-8")
    (tmp_path / "b.md").write_text(VALID, encoding="utf-8")
    with pytest.raises(RecordError, match="duplicate id"):
        load_records(tmp_path)


def test_example_records_are_valid(examples_dir):
    records = load_records(examples_dir)
    assert len(records) == 6
    assert {r.review_status for r in records} == {"pending", "confirmed"}
