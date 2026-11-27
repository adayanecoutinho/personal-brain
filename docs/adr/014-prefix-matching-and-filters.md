# 014. Prefix matching, period and status filters

- **Status:** Accepted
- **Date:** 2026-11-26
- **Amends:** [ADR 003](003-sqlite-fts5-index.md) (search behaviour)

## Context

The private evaluation on real records ([ADR 013](013-evaluation.md)) passed every gating case but exposed three gaps:

1. **Word variants.** In Portuguese, the word a person uses often differs from the word in the note only by its ending: "ginecologista" versus "ginecologia". Exact keyword search misses these.
2. **Time ranges.** "Show my history from August to October" can't be answered by keywords.
3. **Review status.** "What is still pending?" needs to filter by `review_status`, not by a word.

SQLite's FTS5 has no Portuguese stemmer, and the Porter tokenizer is English-only.

## Decision

- **Prefix pass after the exact pass.** A search runs the exact query first (every word required, ranked by bm25). If that returns fewer results than the limit, a second pass runs where each word of 6 or more letters becomes a prefix of its first `max(5, length - 4)` letters, and the results are appended without duplicates.
  - Exact matches always come first, so precision on the original words is unchanged.
  - Words shorter than 6 letters are never shortened.
  - This is language-agnostic and needs no dictionary.
- **Period filter (`date_from`, `date_to`).** It accepts `YYYY`, `YYYY-MM` or `YYYY-MM-DD`.
  - Each record stores the first and last day its own date can mean, so `2026-05` covers 1 to 31 May.
  - A record matches when that period overlaps the filter. A partial date is never turned into an invented day ([ADR 004](004-markdown-yaml-records.md)).
- **Status filter (`review_status`).** `pending` or `confirmed`.
- **Filter-only searches.** The query may be empty when at least one filter is given. Results are then listed newest first. An empty query with no filter returns nothing.
- **Scope still comes first.** Every filter is applied inside the caller's domain scope and can only narrow it ([ADR 011](011-domains-and-scopes.md)).
- **Errors.** An invalid filter value returns a fixed `invalid_filter` error, never a stack trace.

## Alternatives considered

- **A Portuguese stemmer (for example a Snowball implementation).** More accurate, but it's a dependency, it needs a custom FTS5 tokenizer or stemming at index time, and it's tied to one language while the memory may mix languages.
- **Prefix matching on every query, in a single pass.** Simpler, but it ranks loose matches together with exact ones and lowers precision.
- **Semantic search.** It still isn't justified: the paraphrases that remain are true synonyms ("stomach doctor"), a small share of the cases.

## Consequences

- **Fictional evaluation:** 26 cases, 23/23 gating, 0 scope violations, MRR 0.972. Word variants: 2/2. Timeline: 3/3. Pending list: passes.
- **Remaining limit:** true synonyms (paraphrases) still fail, as expected. They remain informational and are the measured case for any future semantic layer.
- **Index schema:** the index gained `date_start` and `date_end`. The index is rebuilt at every start ([ADR 010](010-container-deployment.md)), so no migration is needed.
