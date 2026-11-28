# Public Brain access (OAuth)

This document lists the steps that only the owner of the data can take.
The code in this repository does not create a GitHub OAuth App, change DNS,
open a proxy route, or write secrets.

The deployment layout is in `docker-compose.example.yml`: two containers
from the same image. `brain-private` is unchanged (no auth, no proxy labels,
reached through the SSH tunnel). `brain-public` runs with `--auth` and is
the only service with proxy labels. `scripts/check-deploy.py` verifies that
split.

## 1. GitHub OAuth App

Create a GitHub OAuth App with **no scopes** beyond the public profile.

- Homepage URL: the public origin you will use, for example `https://brain.example.invalid`.
- Authorization callback URL: `https://<your-subdomain>/oauth/github/callback`.

Copy the client id and the client secret into the server environment. They
must never be committed.

## 2. Subdomain and DNS

Choose a subdomain and point it at the existing reverse proxy. The public MCP
URL entered in Claude must be exact, path included (by default `/mcp`). Do
not redirect that URL to another host, or the `Authorization` header is lost.

## 3. Environment on the public container

Set these variables on `brain-public` only (see `.env.example` for placeholders):

- `GITHUB_CLIENT_ID`
- `GITHUB_CLIENT_SECRET`
- `ALLOWED_GITHUB_USER_ID` (the numeric GitHub user id, not the login name)
- `TOKEN_PEPPER` (a long random string)

Pass `--public-url` (the public origin, no trailing slash) and `--auth-db`
(a persistent volume). The process refuses to start if any of these is missing.

## 4. Create the Claude client

On the server, with `TOKEN_PEPPER` already in the environment:

```
personal-brain auth create-client \
  --auth-db /data/auth/auth.db \
  --redirect-uri https://claude.ai/api/mcp/auth_callback \
  --max-scopes brain:health:read,brain:training:read
```

The command prints the client id and the client secret once. Put both in the
Claude connector's advanced settings. The server stores only a digest of the
secret.

## 5. Opening the route

A later, separate change applies the public service and opens the proxy route.
That step is outside this document and happens only after a security review
and an explicit approval. `personal-brain auth revoke-all` signs every client
out without deleting the pre-registered client.

## 6. Rate limit

The public process applies a simple in-process limit of 60 requests per minute,
per client address, on `/authorize`, `/token` and `/oauth/github/callback`.
A request over the limit receives `429` with `Retry-After: 60`. This is not a
substitute for limits at the reverse proxy.

