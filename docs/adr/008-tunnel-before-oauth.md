# 008. Tunnel-only access until OAuth exists

- **Status:** Accepted
- **Date:** 2026-11-25

## Context

The service holds health records. A public endpoint with a static token is one leaked config file away from exposure.

## Decision

Until OAuth is in place (phase 3), the service listens only on a private network and is reached through an SSH tunnel. In phase 3 it is exposed through the existing reverse proxy, with OAuth 2.1 (PKCE) and GitHub login restricted to a single account.

## Alternatives considered

- **Public endpoint with a bearer token from day one.** Faster to reach the phone, unacceptable for this data.
- **Self-hosted identity provider.** More control, but more to run; GitHub login is enough for one user.

## Consequences

- Mobile use waits until phase 3.
- No new host port is opened; the service follows the server's existing entry rules.
