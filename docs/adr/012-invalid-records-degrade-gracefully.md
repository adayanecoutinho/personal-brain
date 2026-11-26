# 012. Invalid records degrade gracefully and are reported as codes

- **Status:** Accepted
- **Date:** 2026-11-26

## Context

Real records come from years of hand-written notes that don't follow the record format yet. Two problems showed up before migrating them:

1. **One bad file could take the service down.** The container rebuilds the index at start ([ADR 010](010-container-deployment.md)). Before this decision, one invalid record made the rebuild fail and the server exit, so the memory became unavailable.
2. **Errors leaked file names.** Validation errors included the file path. In the health domain a file name can be sensitive (an exam or a medication), and those errors went to the container logs, which [ADR 007](007-no-content-in-logs.md) forbids.

## Decision

- **Fixed error codes.** Every validation error has a stable code: `missing_front_matter`, `invalid_yaml`, `missing_fields`, `invalid_id`, `unknown_event_type`, `unknown_review_status`, `invalid_date`, `outside_domain`, `unknown_domain`, `duplicate_id`, `not_utf8`.
- **Counts only by default.** `validate` and `build` print counts per code. File names appear only with `--show-paths`, which is meant for local use on the owner's machine.
- **Validation is all-or-nothing.** Validation collects every error, not just the first one. If any record is invalid, the index is not changed.
- **No outage on a bad rebuild.** `serve --records` keeps serving the previous index when a rebuild fails, and logs `SERVING_PREVIOUS_INDEX`. It refuses to start only if no index exists yet.

## Alternatives considered

- **Index the valid records and skip the invalid ones.** The memory would silently miss records, and an answer like "no exam on that date" could be wrong without any signal. A failed build is visible; a partial index is not.
- **Keep paths in errors and scrub logs later.** Fragile, for the reasons in ADR 007.

## Consequences

- Fixing data is a local loop: `validate --show-paths` on the owner's machine, fix, repeat until `invalid: 0`, then publish.
- After a bad publish, the server keeps answering from the last good state. The `SERVING_PREVIOUS_INDEX` line is the signal to fix the data.
