# 010. Container deployment over Streamable HTTP

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

The server must run on a small VPS next to other services, managed by Coolify, under an existing set of entry rules: no host ports, no root, a health check, and backups for every piece of state. Local clients use stdio, but a server process needs a network transport.

## Decision

- **One container image.** It serves MCP over Streamable HTTP on port 8000, inside the private container network. No host port is published; access before OAuth goes through an SSH tunnel ([ADR 008](008-tunnel-before-oauth.md)).
- **Records come in read-only.** They are mounted at `/data/records` from the private data repository. The index lives in a separate writable volume and is rebuilt from the records at every start. It is never backed up, because it is derived ([ADR 003](003-sqlite-fts5-index.md)).
- **Runtime hardening.** The process runs as a non-root user (uid 10001). A `/health` endpoint answers without touching records and backs the container health check.
- **Logging.** The server logs at WARNING, so no request lines reach the logs. `personal-brain check-logs` verifies this against a running container ([ADR 007](007-no-content-in-logs.md)).
- **CI.** CI builds the image, runs it on fictional records, waits for it to be healthy, runs the log check and asserts the process is not root.

## Alternatives considered

- **Build the index into the image.** Couples code releases to data changes, and would put data into an image.
- **Back up the index too.** Unnecessary: it is reproducible from the records in seconds.
- **SSE transport.** Superseded by Streamable HTTP in the MCP specification.

## Consequences

- A record change becomes visible after an index rebuild, which today means a container restart. Phase 4 adds rebuild-on-commit.
- The only state worth backing up is the data repository.
