# 001. Python and the official MCP SDK

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

The server needs a mature MCP implementation, a lightweight runtime for a small VPS, and good libraries for text and data. An earlier plan used Java with Spring AI, my strongest language after 15 years of backend work.

## Decision

Python 3.12+ with the official MCP Python SDK 2.x (`MCPServer`), `sqlite3` from the standard library and PyYAML. Dependencies are managed with uv. Tools declare MCP annotations (`readOnlyHint`) so clients can tell they don't change anything.

## Alternatives considered

- **Java + Spring AI MCP.** My strongest stack, but heavier to run and less common in the AI tooling ecosystem.
- **TypeScript + the official TypeScript SDK.** Also mature. The project that inspired this one uses it, and I wanted a clearly independent implementation.

## Consequences

- Small dependency footprint: two runtime dependencies.
- The MCP SDK is still evolving (2.x renamed `FastMCP` to `MCPServer`). The dependency is pinned to `>=2.3,<3` so a major release can't break the tool API silently.
- This project is deliberately a Python one; Java experience shows in my other work.
