"""Record format: Markdown files with a YAML front matter header.

A record is the unit of memory. The front matter carries the structured fields
the index needs; the Markdown body carries the human-readable content.
See docs/adr/004-markdown-yaml-records.md and docs/adr/005-pending-before-confirmed.md.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

EVENT_TYPES = frozenset(
    {"encounter", "exam", "prescription", "medication_use", "follow_up"}
)
REVIEW_STATUSES = frozenset({"pending", "confirmed"})
REQUIRED_FIELDS = ("id", "event_type", "date", "review_status", "title")

# A date keeps the precision it was recorded with: year, year-month or full date.
# Nothing is inferred (a record dated "2026-03" never becomes "2026-03-01").
DATE_PATTERN = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")


class RecordError(ValueError):
    """Raised when a file is not a valid record. The message names the source file."""


@dataclass(frozen=True)
class Record:
    id: str
    event_type: str
    date: str
    review_status: str
    title: str
    body: str
    source: str
    sha256: str


def _split_front_matter(text: str, source: str) -> tuple[dict, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise RecordError(f"{source}: missing YAML front matter")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration:
        raise RecordError(f"{source}: unterminated YAML front matter") from None
    try:
        meta = yaml.safe_load("\n".join(lines[1:end])) or {}
    except yaml.YAMLError as exc:
        raise RecordError(f"{source}: invalid YAML front matter") from exc
    if not isinstance(meta, dict):
        raise RecordError(f"{source}: front matter must be a mapping")
    body = "\n".join(lines[end + 1 :]).strip()
    return meta, body


def parse_record(text: str, source: str) -> Record:
    """Parse one record. `source` is the path relative to the records root."""
    meta, body = _split_front_matter(text, source)

    missing = [field for field in REQUIRED_FIELDS if meta.get(field) in (None, "")]
    if missing:
        raise RecordError(f"{source}: missing required fields: {', '.join(missing)}")

    record_id = str(meta["id"])
    event_type = str(meta["event_type"])
    date = str(meta["date"])
    review_status = str(meta["review_status"])

    if not ID_PATTERN.match(record_id):
        raise RecordError(f"{source}: invalid id {record_id!r}")
    if event_type not in EVENT_TYPES:
        raise RecordError(f"{source}: unknown event_type {event_type!r}")
    if review_status not in REVIEW_STATUSES:
        raise RecordError(f"{source}: unknown review_status {review_status!r}")
    if not DATE_PATTERN.match(date):
        raise RecordError(f"{source}: date must be YYYY, YYYY-MM or YYYY-MM-DD")

    return Record(
        id=record_id,
        event_type=event_type,
        date=date,
        review_status=review_status,
        title=str(meta["title"]),
        body=body,
        source=source,
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
    )


def load_records(root: Path) -> list[Record]:
    """Load every `*.md` record under `root`. Duplicate ids are an error."""
    records: list[Record] = []
    seen: dict[str, str] = {}
    for path in sorted(root.rglob("*.md")):
        source = path.relative_to(root).as_posix()
        record = parse_record(path.read_text(encoding="utf-8"), source)
        if record.id in seen:
            raise RecordError(
                f"{source}: duplicate id {record.id!r} (also in {seen[record.id]})"
            )
        seen[record.id] = source
        records.append(record)
    return records
