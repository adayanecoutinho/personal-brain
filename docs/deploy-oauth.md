# Public Brain access (OAuth)

This document lists the steps that only the owner of the data can take.
The code in this repository does not create a GitHub OAuth App, change DNS,
open a proxy route, or write secrets.

The deployment layout is in `docker-compose.example.yml`: two containers
from the same image. `brain-private` is unchanged (no auth, no proxy labels,
reached through the SSH tunnel). `brain-public` runs with `--auth` and is
the only service with proxy labels. `scripts/check-deploy.py` verifies that
split. Use `--stage private-only` while the public service is deployed without
proxy labels (no Brain service may have any), and the default `--stage public`
once the route is meant to open:

```
python scripts/check-deploy.py --stage private-only docker-compose.example.yml
```

(The example file itself has labels on `brain-public`, so it passes only in the
`public` stage; check the compose you actually deploy.)

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

### The `/data/auth` volume

The image creates `/data/auth` owned by uid 10001 (`brain`) with mode 700. A
**new, empty named volume** mounted at `/data/auth` inherits that owner and
mode on first use, so `docker-compose.example.yml` needs no preparation
container. Docker does not do this in these cases, and the volume then needs a
one-time `chown 10001` / `chmod 700`:

- a volume that already exists with other ownership (for example one created
  while an older image had no `/data/auth`);
- a bind mount of a host directory, which keeps the host owner;
- an orchestrator that creates the volume itself and does not copy the image
  contents (some Kubernetes volume types).

If the process cannot write `auth.db`, check the owner of `/data/auth` first.

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

