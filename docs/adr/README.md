# Architecture Decision Records

Each ADR records one decision: the context, what was decided, the alternatives considered and the consequences. ADRs are immutable once accepted; a change of direction is a new ADR that supersedes the old one.

| # | Decision | Status |
|---|---|---|
| [001](001-python-and-official-mcp-sdk.md) | Python and the official MCP SDK | Accepted |
| [002](002-git-repository-as-source-of-truth.md) | A Git repository on the server is the source of truth | Accepted |
| [003](003-sqlite-fts5-index.md) | SQLite FTS5 as a rebuildable index, before embeddings | Accepted, amended by 014 |
| [004](004-markdown-yaml-records.md) | Records as Markdown with YAML front matter | Accepted, amended by 011 |
| [005](005-pending-before-confirmed.md) | Pending before confirmed | Accepted |
| [006](006-read-only-tools-first.md) | Read-only tools first | Accepted |
| [007](007-no-content-in-logs.md) | No record content or query terms in logs | Accepted |
| [008](008-tunnel-before-oauth.md) | Tunnel-only access until OAuth exists | Accepted, amended by 015 |
| [009](009-public-code-private-data.md) | Public code, private data | Accepted |
| [010](010-container-deployment.md) | Container deployment over Streamable HTTP | Accepted |
| [011](011-domains-and-scopes.md) | Domains and per-client scopes | Accepted, amended by 015 |
| [012](012-invalid-records-degrade-gracefully.md) | Invalid records degrade gracefully and are reported as codes | Accepted |
| [013](013-evaluation.md) | Retrieval evaluation with a fictional twin of the private set | Accepted |
| [014](014-prefix-matching-and-filters.md) | Prefix matching, period and status filters | Accepted |
| [015](015-oauth-with-github-login.md) | Remote access with OAuth 2.1 and GitHub login | Accepted |
