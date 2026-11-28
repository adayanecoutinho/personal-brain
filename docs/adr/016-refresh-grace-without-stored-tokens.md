# 016. Refresh grace window without stored tokens

- **Status:** Accepted
- **Date:** 2026-11-27
- **Amends:** [ADR 015](015-oauth-with-github-login.md) (refresh token reuse grace)

## Context

ADR 015 said that, for 60 seconds after a rotation, presenting the previous refresh token returns the same new pair. Honouring that literally means the authorization server must be able to give those exact token strings back. Keeping them in plaintext in `auth.db` contradicts the same ADR, which stores tokens only as HMAC-SHA256 digests. Reversible encryption would still leave a recoverable secret on disk, including in backups.

## Decision

- Inside the 60-second grace window, a repeated refresh with the previous token issues a **new** token pair in the same family, instead of returning the previous pair. Both pairs remain valid during the window.
- After the window, a reused refresh token still revokes the whole family.
- No access or refresh token is stored in plaintext. The `refresh_graces` table keeps only `old_digest`, `family_id` and `rotated_at`. Rows older than 60 seconds are deleted on the next rotation.
- If an existing `auth.db` still has the old grace table with plaintext columns, that table is dropped and recreated. There is no production database yet.
- If `revoke-all` has already revoked the family, a request inside the window is refused and does not issue a new pair.
- A rotation claims the previous refresh token with an atomic `UPDATE ... WHERE revoked = 0`, so two concurrent renewals cannot both treat it as unused.

## Consequences

- A client that retries a refresh within 60 seconds receives a different pair than the first response. Both work until the family is revoked or the tokens expire.
- The sentence in ADR 015 about "returns the same new pair" is superseded by this decision. The rest of ADR 015 stands.
