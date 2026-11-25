# 009. Public code, private data

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

The code and its design decisions are meant to be public. The records are personal health data. An earlier private repository mixed planning documents, infrastructure notes and references to real records.

## Decision

- This repository is public and contains only code, tests, documentation and **fictional** example records.
- Real records live in a separate private Git repository on the server ([ADR 002](002-git-repository-as-source-of-truth.md)) and are never committed here.
- The repository started with a fresh history; the earlier private repository is archived and stays private.
- `.gitignore` blocks data and database files, and CI runs a secret scan (gitleaks) on every push.

## Alternatives considered

- **Make the old repository public.** Its history contains infrastructure details and planning notes with real context.
- **Keep everything private.** Safer, but the code and decisions are the portfolio.

## Consequences

- Examples, tests and demos must use fictional data.
- The real evaluation question set stays private; a fictional twin runs in CI.
