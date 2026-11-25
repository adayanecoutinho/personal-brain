# 003. SQLite FTS5 as a rebuildable index, before embeddings

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

Queries are mostly about known things: names of exams, specialties, medications, dates. The record set is small (hundreds of documents, tens of megabytes). The VPS already runs several services, and adding a database server has an operational cost.

## Decision

A SQLite database with an FTS5 full-text index (`unicode61`, diacritics removed), built from the records.

- The index is derived data: rebuilt from scratch, written to a temporary file and swapped in with an atomic rename.
- Records are validated before anything is written, so an invalid record never breaks the serving index.
- Queries use a read-only connection, and every user token is quoted so input can't become FTS5 syntax.

## Alternatives considered

- **PostgreSQL full-text search.** Used in an earlier pilot. Capable, but one more server to run, back up and monitor.
- **Embeddings with a vector store.** Better for paraphrases, but adds a model dependency, cost and opacity, and there's no evidence yet that keyword search fails on this data.

## Consequences

- Zero extra services, and the index file can be deleted at any time.
- Synonyms and paraphrases are not matched. The phase 2 evaluation decides whether semantic search is worth adding.
- Full rebuilds are fine at this size. Incremental indexing can come later if the record count grows.
