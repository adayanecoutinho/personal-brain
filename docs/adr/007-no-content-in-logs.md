# 007. No record content or query terms in logs

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

A search for a medication name is itself health information. Logs, reverse-proxy access lines and monitoring systems are often retained longer and protected less than the data itself.

## Decision

- The service never logs queries, tool arguments or record content. Errors use fixed codes.
- Tool arguments travel in the MCP request body, never in URLs, so reverse-proxy access logs can't capture them.
- Before real data is migrated, an automated test runs fictional queries and asserts that none of their terms appear in the container or proxy logs.

## Alternatives considered

- **Log everything at debug level.** Convenient for development, but debug logs leak into production.
- **Redact logs after the fact.** Fragile: redaction rules miss new fields.

## Consequences

- Debugging uses fictional data locally, not production logs.
- The log test is part of the gate before real data (phase 1).
