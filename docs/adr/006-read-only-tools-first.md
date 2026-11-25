# 006. Read-only tools first

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

Every tool an MCP server exposes widens what a model can do with the data. Writes bring new risks: wrong data, overwritten history, prompt injection turning into actions.

## Decision

Phases 1 to 3 expose exactly two read-only tools: `search` and `read_entry`. The query layer opens the database read-only.

Write tools (`add_entry`, `confirm_entry`, `create_upload_link`) arrive in phase 4 and are append-only: no tool deletes or edits history, and a correction is a new commit.

## Alternatives considered

- **Generic file access** (list, read and write any path). Maximum flexibility and maximum blast radius.
- **Search only.** Snippets aren't enough to answer exam or prescription questions; `read_entry` is needed.

## Consequences

- A small surface that is easy to test and reason about.
- Capture from chat waits until phase 4, after authentication exists.
