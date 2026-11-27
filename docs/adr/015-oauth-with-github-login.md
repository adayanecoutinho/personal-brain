# 015. Remote access with OAuth 2.1 and GitHub login

- **Status:** Proposed
- **Date:** 2026-11-27
- **Amends:** [ADR 008](008-tunnel-before-oauth.md) (details the phase 3 exposure it announced), [ADR 011](011-domains-and-scopes.md) (scopes now come from the token)

## Context

The Brain only answers through an SSH tunnel. A tunnel works from my PC. It does not work from the Claude app on my phone, which is where I want to ask about my health records.

The Claude app connects to remote MCP servers that follow the MCP authorization specification:
- the MCP server is an OAuth 2.1 **resource server**;
- it publishes Protected Resource Metadata (RFC 9728), which points to an authorization server;
- the client gets a client id, either dynamically (RFC 7591, or a Client ID Metadata Document) or pre-registered, and runs the authorization code flow with PKCE;
- the token is bound to the server it was requested for (resource indicators, RFC 8707).

GitHub can prove who I am, but it cannot be the authorization server for this flow:
- it does not issue clients on request for an MCP connector;
- its tokens are not bound to the Brain as a resource;
- its scopes describe GitHub, not my domains.

There is one user. The service holds health data. A mistake here exposes medical records to the internet.

## Decision

### 1. The Brain is its own authorization server, and GitHub only proves identity

The Brain runs an embedded authorization server through the official SDK (`OAuthAuthorizationServerProvider` with `AuthSettings`), next to the resource server. It issues its own tokens. GitHub is an upstream login step only:

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
- **Stored as HMAC-SHA256 digests**, keyed with `TOKEN_PEPPER`, in a separate SQLite file (`auth.db`) on a persistent volume. It is never mixed with the search index, which is rebuilt and replaced atomically (ADR 003).
- **Access token:** 1 hour.
- **Refresh token:** 30 days, rotated on every use.
- **Reuse detection with a grace window.** Clients retry, and sometimes send the same refresh token twice. For 60 seconds after a rotation, the previous refresh token returns the same new pair. After that window, a reused refresh token means a stolen one, and the Brain revokes the whole family.
- **Bound to the resource:** `validate_token_resource=True`. A token issued for another resource is refused.
- **Revocation** endpoint enabled.
- **Kill switch:** deleting `auth.db`, or rotating `TOKEN_PEPPER`, signs out every client at once.

### 3. Scopes are the domains from ADR 011

- **One scope per domain:** `brain:health:read`, `brain:training:read`.
- **No default grant.** A token without a domain scope reads nothing.
- **The scope filter does not change.** The SQL scope filter of ADR 011 now takes its domains from the token. The deployment flag (`--domains`) still sets the maximum: a token can narrow it, never widen it.
- **Out of scope still looks like missing** (`not_found`).

### 4. One pre-registered client, no open registration

Claude accepts three ways to get a client id: dynamic registration (RFC 7591), a Client ID Metadata Document, or a client pre-registered by the server's owner, whose id and secret are entered in the connector's advanced settings.

The Brain uses **a pre-registered client only**:
- **No registration endpoint.** Registration is disabled (`ClientRegistrationOptions(enabled=False)`), and the metadata does not advertise Client ID Metadata Documents. Nobody can create a client on the public route.
- **One confidential client** for the Claude app, created by a CLI command on the server (`personal-brain auth create-client`). Its secret is shown once, entered by me in the connector settings, and stored only as a digest.
- **The redirect URI is fixed** to Claude's published callback, `https://claude.ai/api/mcp/auth_callback`. Any other redirect URI is refused.
- **A second client** (for example another assistant) is a deliberate command, with its own redirect URI and its own maximum scopes.

### 5. Exposure

- **HTTPS on a subdomain**, through the reverse proxy already on the server, managed by Coolify (ADR 010). No new host port is opened.
- **The resource URL is exact.** The `resource` in the Protected Resource Metadata matches the MCP URL entered in Claude, path included. The route does not redirect to another host, which would drop the `Authorization` header.
- **Public routes:**
  - the MCP endpoint;
  - the OAuth endpoints;
  - the metadata documents;
  - `/health`, which answers only `ok` and nothing else.
- **Rate limits** on `/authorize`, `/token` and the GitHub callback.
- **Secrets stay out of Git.** The GitHub client secret, `TOKEN_PEPPER` and the allowed user id live only in the server's environment.
- **Logs follow ADR 007.** No tokens, codes, `state` values or GitHub responses. Only event names and outcomes: `auth.login.denied`, `auth.token.refreshed`, `auth.refresh.reuse_revoked`.

### 6. The tunnel path stays, as a separate private listener

The CLI, the private eval and maintenance from my PC keep working without tokens:
- **Two containers from the same image**, reading the same data read-only:
  - `brain-private`: the current service, without auth, on the private network only, reached through the SSH tunnel (ADR 008);
  - `brain-public`: auth on, the only one attached to the reverse proxy.
- **Auth is not a runtime switch inside one process.** It is a deployment choice. The public container refuses to start if auth settings are missing.
- The private container keeps the `--domains` limit of its deployment.

### 7. Gate before going public

The route is opened only after all of these are true:
- automated tests cover:
  - a request without a token returns 401, with `WWW-Authenticate` pointing to the resource metadata;
  - a wrong GitHub account is denied;
  - a wrong `state` is refused;
  - a token for another resource is refused;
  - an expired token is refused;
  - a reused refresh token revokes the family;
  - a scope narrows the results;
  - a redirect URI other than the registered one is refused;
  - an unknown client id is refused;
  - the private listener is not reachable through the reverse proxy;
- the log privacy check (ADR 010) passes with the auth events;
- a security review, done by a reviewer other than the one who wrote the code, has no open high finding;
- the owner of the data approves opening the route.

## Alternatives considered

- **GitHub as the authorization server directly.** Not possible for the reasons in Context: no dynamic registration, no resource binding, no domain scopes.
- **A managed identity provider (Auth0, Clerk, WorkOS) in front of the Brain.** It supports the MCP flow out of the box. But it puts a third party in the trust path of a health data service, adds another account to secure, and hides the part of the system that most needs to be understood.
- **A self-hosted identity provider (Keycloak, Authentik).** Full control. But it is another service to run, patch and back up, for a single user.
- **Open dynamic registration.** It is what most remote MCP servers do, and Claude supports it. But it lets anyone create clients on a public route that guards health data. With one user, a pre-registered client costs one command and removes that surface.
- **A static bearer token behind HTTPS.** Simple. But the Claude app does not accept it, and a static token has no expiry, rotation or scope. ADR 008 already rejected it.
- **Cloudflare Access or a VPN in front of the server.** It protects the route. But the Claude app connects from Anthropic's servers, not from my phone, so device-based access does not fit the flow.
- **JWT access tokens.** Stateless. But revoking one before it expires needs a deny-list anyway, and there is no second service to verify them.

## Consequences

- I can query the Brain from the Claude app on my phone and my PC.
- The service now holds credentials, `auth.db`. It joins the backup with its own restore test. Losing it only signs everyone out; no data is lost.
- New security-sensitive code: the provider, the GitHub callback and the token store. This code is the main subject of the security review.
- Two containers to run instead of one. A deployment check confirms that only `brain-public` has proxy labels.
- Record snippets now pass through Anthropic's servers when I use the Claude app. I accepted this earlier for this data.
- A future MCP Gateway can reuse this authorization server for other servers, with the same scopes.
- Write tools (phase 4) will need their own scopes, `brain:<domain>:write`, and their own ADR.
