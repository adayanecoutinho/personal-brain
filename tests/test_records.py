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
    record = parse_record(VALID, "health/a.md")
    assert record.id == "enc-2026-01-01-test"
    assert record.domain == "health"
    assert record.body == "Body text."
    assert record.source == "health/a.md"
    assert len(record.sha256) == 64


@pytest.mark.parametrize(
    "replace, expected",
    [
        (("event_type: encounter", "event_type: rumor"), "unknown event_type"),
        (("event_type: encounter", "event_type: methodology"), "for domain 'health'"),
        (("review_status: confirmed", "review_status: maybe"), "unknown review_status"),
        (("date: 2026-01-01", "date: 01/01/2026"), "date must be"),
        (("id: enc-2026-01-01-test", "id: Bad Id"), "invalid id"),
        (("title: Test\n", ""), "missing required fields: title"),
    ],
)
def test_rejects_invalid_records(replace, expected):
    text = VALID.replace(*replace)
    with pytest.raises(RecordError, match=expected):
        parse_record(text, "health/a.md")


def test_rejects_file_without_front_matter():
    with pytest.raises(RecordError, match="missing YAML front matter"):
        parse_record("just text", "health/a.md")


def test_partial_dates_keep_their_precision():
    record = parse_record(VALID.replace("date: 2026-01-01", "date: 2026-01"), "health/a.md")
    assert record.date == "2026-01"


def test_duplicate_ids_are_rejected(tmp_path):
    (tmp_path / "health").mkdir()
    (tmp_path / "health" / "a.md").write_text(VALID, encoding="utf-8")
    (tmp_path / "health" / "b.md").write_text(VALID, encoding="utf-8")
    with pytest.raises(RecordError, match="duplicate id"):
        load_records(tmp_path)


def test_example_records_are_valid(examples_dir):
    records = load_records(examples_dir)
    assert len(records) == 8
    assert {r.review_status for r in records} == {"pending", "confirmed"}


def test_domain_comes_from_the_first_folder():
    record = parse_record(
        VALID.replace("event_type: encounter", "event_type: rule"), "training/x/a.md"
    )
    assert record.domain == "training"


@pytest.mark.parametrize(
    "source, expected",
    [("a.md", "inside a domain folder"), ("finance/a.md", "unknown domain")],
)
def test_records_outside_known_domains_are_rejected(source, expected):
    with pytest.raises(RecordError, match=expected):
        parse_record(VALID, source)
