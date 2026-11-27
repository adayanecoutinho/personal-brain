# 015. Remote access with OAuth 2.1 and GitHub login

- **Status:** Proposed
- **Date:** 2026-11-27
- **Amends:** [ADR 008](008-tunnel-before-oauth.md) (details the phase 3 exposure it announced), [ADR 011](011-domains-and-scopes.md) (scopes now come from the token)

## Context

The Brain only answers through an SSH tunnel. A tunnel works from my PC. It does not work from the Claude app on my phone, which is where I want to ask about my health records.

The Claude app connects to remote MCP servers that follow the MCP authorization specification:
- the MCP server is an OAuth 2.1 **resource server**;
- it publishes Protected Resource Metadata (RFC 9728), which points to an authorization server;
- the client registers itself dynamically (RFC 7591) and runs the authorization code flow with PKCE;
- the token is bound to the server it was requested for (resource indicators, RFC 8707).

GitHub can prove who I am, but it cannot be the authorization server for this flow:
- it does not support dynamic client registration;
- its tokens are not bound to the Brain as a resource;
- its scopes describe GitHub, not my domains.

There is one user. The service holds health data. A mistake here exposes medical records to the internet.

## Decision

### 1. The Brain is its own authorization server, and GitHub only proves identity

The Brain runs an embedded authorization server through the official SDK (`OAuthAuthorizationServerProvider` with `AuthSettings`). It issues its own tokens. GitHub is an upstream login step only:

1. The client calls `/authorize` on the Brain, with PKCE (S256) and a `resource`.
2. The Brain stores the pending request and redirects to GitHub, with a random `state` bound to that request.
3. GitHub calls back a Brain route (`/oauth/github/callback`). The Brain:
   - checks the `state`;
   - exchanges the GitHub code;
   - reads the GitHub user's **numeric id**.
4. Only one numeric id is allowed (`ALLOWED_GITHUB_USER_ID`). The login name is not checked, because it can be renamed and reclaimed by someone else. Any other account gets the same generic denial.
5. A consent page lists the domains the client asked for. I pick which ones to grant.
6. The Brain issues its own authorization code to the client, and then its own tokens.

The GitHub access token is used once, to read the user id. It is discarded and never stored. The GitHub OAuth App asks for no scopes beyond the public profile.

### 2. Tokens

- **Opaque random tokens** (256 bits), not JWTs. Only the Brain verifies them, so there is no reason to make them self-describing.
- **Stored as SHA-256 hashes** in a separate SQLite file (`auth.db`) on a persistent volume. It is never mixed with the search index, which is rebuilt and replaced atomically (ADR 003).
- **Access token:** 1 hour.
- **Refresh token:** 30 days, rotated on every use. If a refresh token is used twice, the Brain revokes the whole family, because a reused token means a stolen one.
- **Bound to the resource:** `validate_token_resource=True`. A token issued for another resource is refused.
- **Revocation** endpoint enabled.
- **Kill switch:** deleting `auth.db`, or rotating `TOKEN_PEPPER`, signs out every client at once.

### 3. Scopes are the domains from ADR 011

- **One scope per domain:** `brain:health:read`, `brain:training:read`.
- **No default grant.** A token without a domain scope reads nothing.
- **The scope filter does not change.** The SQL scope filter of ADR 011 now takes its domains from the token. The deployment flag (`--domains`) still sets the maximum: a token can narrow it, never widen it.
- **Out of scope still looks like missing** (`not_found`).

### 4. Dynamic registration, limited

Dynamic client registration stays on, because the Claude app needs it. Registration alone gives nothing: a token still needs my GitHub login and my consent. On top of that:
- **Redirect URIs are allow-listed.** Only HTTPS redirect URIs from an allow-list are accepted: Claude's published callbacks, confirmed at implementation. `localhost` is accepted only in the development profile. An attacker who registers a client cannot receive a code.
- **Registered clients expire.** A client unused for 90 days is deleted.

### 5. Exposure

- **HTTPS on a subdomain**, through the reverse proxy already on the server (Coolify and Traefik). No new host port is opened.
- **Public routes:**
  - the MCP endpoint;
  - the OAuth endpoints;
  - the metadata documents;
  - `/health`, which answers only `ok` and nothing else.
- **Rate limits** on `/authorize`, `/token`, `/register` and the GitHub callback.
- **Secrets stay out of Git.** The GitHub client secret, `TOKEN_PEPPER` and the allowed user id live only in the server's environment.
- **Logs follow ADR 007.** No tokens, codes, `state` values or GitHub responses. Only event names and outcomes: `auth.login.denied`, `auth.token.refreshed`, `auth.refresh.reuse_revoked`.

### 6. Gate before going public

The route is opened only after all of these are true:
- automated tests cover:
  - a request without a token returns 401, with `WWW-Authenticate` pointing to the resource metadata;
  - a wrong GitHub account is denied;
  - a wrong `state` is refused;
  - a token for another resource is refused;
  - an expired token is refused;
  - a reused refresh token revokes the family;
  - a scope narrows the results;
  - a redirect URI outside the allow-list is refused;
- the log privacy check (ADR 010) passes with the auth events;
- a security review, done by a reviewer other than the one who wrote the code, has no open high finding;
- the owner of the data approves opening the route.

## Alternatives considered

- **GitHub as the authorization server directly.** Not possible for the reasons in Context: no dynamic registration, no resource binding, no domain scopes.
- **A managed identity provider (Auth0, Clerk, WorkOS) in front of the Brain.** It supports the MCP flow out of the box. But it puts a third party in the trust path of a health data service, adds another account to secure, and hides the part of the system that most needs to be understood.
- **A self-hosted identity provider (Keycloak, Authentik).** Full control. But it is another service to run, patch and back up, for a single user.
- **A static bearer token behind HTTPS.** Simple. But the Claude app does not accept it, and a static token has no expiry, rotation or scope. ADR 008 already rejected it.
- **Cloudflare Access or a VPN in front of the server.** It protects the route. But the Claude app connects from Anthropic's servers, not from my phone, so device-based access does not fit the flow.
- **JWT access tokens.** Stateless. But revoking one before it expires needs a deny-list anyway, and there is no second service to verify them.

## Consequences

- I can query the Brain from the Claude app on my phone and my PC.
- The service now holds credentials, `auth.db`. It joins the backup with its own restore test. Losing it only signs everyone out; no data is lost.
- About 400 lines of security-sensitive code. Most of them are tests. This code is the main subject of the security review.
- Record snippets now pass through Anthropic's servers when I use the Claude app. I accepted this earlier for this data.
- A future MCP Gateway can reuse this authorization server for other servers, with the same scopes.
- Write tools (phase 4) will need their own scopes, `brain:<domain>:write`, and their own ADR.
