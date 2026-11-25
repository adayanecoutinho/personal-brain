# 002. A Git repository on the server is the source of truth

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

Records used to live only in an Obsidian vault on a laptop. The phone can't reach a laptop that is turned off, and a laptop is a single point of failure. Records will also be written from chat (phase 4), so the store must accept writes without a laptop in the loop.

## Decision

Records live in a Git repository on my server. The service reads it and, from phase 4, writes to it: one commit per change. A laptop is optional: `git clone` when I want to edit in Obsidian. The repository is never hosted on GitHub or any third-party Git service.

## Alternatives considered

- **Laptop as source, one-way sync to the server.** Writes from chat would need a manual inbox step, and the phone depends on the last sync.
- **Server as source, laptop as a read-only mirror.** Simple, but loses editing in Obsidian.
- **A database as source.** Loses plain-text readability, diffs and the existing Obsidian workflow.

## Consequences

- Full history and revert for every record, which matters for health data.
- Git history is not a backup. The repository is included in the encrypted off-site backup, and a restore drill is a gate before real data arrives.
- There is a single writer in practice, so merge conflicts are rare; the service still refuses to overwrite on conflict.
