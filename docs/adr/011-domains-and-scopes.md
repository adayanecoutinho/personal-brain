# 011. Domains and per-client scopes

- **Status:** Accepted
- **Date:** 2026-11-25
- **Amends:** [ADR 004](004-markdown-yaml-records.md) (event types are now declared per domain)

## Context

The memory will hold more than health records. A training coach needs my training methodology; a finance assistant will need finance notes; a general assistant on my phone may need several of them. These consumers should not see each other's data. A training coach has no reason to read my medical history.

Structured, numeric data (sets, loads, transactions) stays in each application's own database. The Brain holds knowledge that an AI must read and cite: methodologies, rules, records and decisions.

## Decision

- **A domain per top-level folder.** The first folder of a record's path is its domain: `records/health/...`, `records/training/...`. A record outside a known domain folder is rejected.
- **Event types per domain.** Each domain declares its own event types:
  - `health`: `encounter`, `exam`, `prescription`, `medication_use`, `follow_up`;
  - `training`: `methodology`, `rule`, `restriction`.

  Adding a domain is a deliberate code change.
- **A scope for every caller.** A caller has a scope: the set of domains it may read. Queries filter by scope inside SQL, before anything is returned.
- **Out of scope looks like missing.** A record outside the scope behaves exactly like a record that doesn't exist (`read_entry` returns the same `not_found`), so the scope doesn't leak existence.
- **The `domain` argument narrows, never widens.** `search` accepts an optional `domain`. It is intersected with the scope.
- **Where the scope comes from:**
  - *Today:* per deployment (`personal-brain serve --domains training`).
  - *Phase 3:* from the OAuth client's granted scopes, for example `brain:training:read`.
- **No sharing by default.** When something must cross domains, it is published as a new record in the target domain, for example a `training/restriction` stating only what the coach needs to know. The source domain is never opened to the other consumer.

## Alternatives considered

- **One server per domain.** Strong isolation, but duplicated deployment and operations for a single user.
- **An MCP gateway in front of several servers now.** It would centralize routing, scopes and audit. Today there is only one server, so the gateway would route to itself. Domains and scopes keep the door open: a gateway can later enforce the same scopes across several servers.
- **A `domain` field in the front matter.** Redundant with the folder, and the two could drift apart. The folder is the single source.

## Consequences

- Least privilege per consumer, enforced and covered by tests.
- Reorganizing the data repository means moving files between domain folders, which Git tracks as renames.
- Cross-domain answers need an explicitly published record, which is intentional friction.
