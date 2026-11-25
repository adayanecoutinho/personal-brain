# 004. Records as Markdown with YAML front matter

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

Records must stay readable and editable by a human in Obsidian, and structured enough for an index and for safety rules. Health data has traps: a prescription is not proof of use, and an approximate date must not become a precise one.

## Decision

One Markdown file per record, with a YAML front matter header holding `id`, `event_type`, `date`, `review_status` and `title`.

- Event types for the first version: `encounter`, `exam`, `prescription`, `medication_use` and `follow_up`.
- `prescription` and `medication_use` are separate types.
- Dates accept `YYYY`, `YYYY-MM` or `YYYY-MM-DD` and keep that precision.
- Ids are opaque and stable; relationships reference ids, not file names.

## Alternatives considered

- **JSON files.** Strict, but unpleasant to read and edit by hand.
- **One big file or a database.** Loses per-record history and the Obsidian workflow.
- **A full JSON Schema per event type** (an earlier design). Rich, but too much ceremony for the first version; it can return when the types stabilize.

## Consequences

- Validation lives in code and is covered by tests; invalid files are rejected with the file name in the error.
- Moving or renaming a file doesn't break references, because ids are independent of paths.
- New domains beyond health need new event types, which is a deliberate change.
