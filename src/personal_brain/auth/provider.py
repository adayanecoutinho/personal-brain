"""OAuthAuthorizationServerProvider backed by auth.db."""

from __future__ import annotations

import time

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    AuthorizeError,
    RefreshToken,
    TokenError,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyUrl

from . import logging as authlog
from .config import AuthConfig
from .github import GitHubIdentity
from .security import digest, new_id, new_token
from .store import (
    ACCESS_TTL_SECONDS,
    AUTH_CODE_TTL_SECONDS,
    REFRESH_TTL_SECONDS,
    REUSE_GRACE_SECONDS,
    AuthCodeRow,
    AuthStore,
    PendingRequest,
    TokenRow,
)

CODE_TTL = AUTH_CODE_TTL_SECONDS


class BrainOAuthProvider:
    """Authorization server for the Brain. GitHub is used only after authorize() redirects."""

    def __init__(self, config: AuthConfig, store: AuthStore, github: GitHubIdentity) -> None:
        self.config = config
        self.store = store
        self.github = github

    def _client_info(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.store.get_client(client_id)
        if row is None:
            authlog.event(authlog.CLIENT_UNKNOWN, "denied")
            return None
        return OAuthClientInformationFull(
            client_id=row.client_id,
            client_secret=row.secret_digest,
            redirect_uris=[AnyUrl(uri) for uri in row.redirect_uris],
            token_endpoint_auth_method="client_secret_post",
            grant_types=["authorization_code", "refresh_token"],
            scope=" ".join(row.max_scopes),
        )

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        return self._client_info(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        raise NotImplementedError("dynamic client registration is disabled")

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        self.store.purge_idle_clients()
        pending_id = new_id()
        github_state = new_id(24)
        scopes = list(params.scopes or [])
        resource = str(self.config.resource_server_url)
        if params.resource and params.resource != resource:
            raise AuthorizeError(error="invalid_target", error_description="invalid resource")
        now = int(time.time())
        self.store.save_pending(
            PendingRequest(
                id=pending_id,
                github_state=github_state,
                client_id=client.client_id,
                code_challenge=params.code_challenge,
                redirect_uri=str(params.redirect_uri),
                redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
                resource=resource,
                scopes=scopes,
                client_state=params.state,
                created_at=now,
                state_used=False,
                github_ok=False,
                consent_csrf=None,
            )
        )
        self.store.touch_client(client.client_id, now)
        return self.github.authorization_url(
            state=github_state,
            redirect_uri=self.config.github_callback_url,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        row = self.store.get_auth_code(digest(self.config.token_pepper, authorization_code))
        if row is None or row.consumed or row.client_id != client.client_id:
            return None
        if row.expires_at < int(time.time()):
            return None
        return AuthorizationCode(
            code=authorization_code,
            scopes=row.scopes,
            expires_at=float(row.expires_at),
            client_id=row.client_id,
            code_challenge=row.code_challenge,
            redirect_uri=AnyUrl(row.redirect_uri),
            redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
            resource=row.resource,
            subject=row.subject,
        )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        code_digest = digest(self.config.token_pepper, authorization_code.code)
        if not self.store.consume_auth_code(code_digest):
            raise TokenError(error="invalid_grant", error_description="invalid authorization code")
        family_id = new_id()
        return self._issue_pair(
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
            family_id=family_id,
        )

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        row = self.store.get_refresh_token(digest(self.config.token_pepper, refresh_token))
        if row is None or row.client_id != client.client_id:
            return None
        return RefreshToken(
            token=refresh_token,
            client_id=row.client_id,
            scopes=row.scopes,
            expires_at=row.expires_at,
            resource=row.resource,
            subject=row.subject,
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        pepper = self.config.token_pepper
        old_digest = digest(pepper, refresh_token.token)
        row = self.store.get_refresh_token(old_digest)
        now = int(time.time())
        if row is None:
            raise TokenError(error="invalid_grant", error_description="invalid refresh token")

        if row.revoked and row.rotated_at is not None:
            grace = self.store.get_grace(old_digest)
            if grace is not None and now - grace.rotated_at <= REUSE_GRACE_SECONDS:
                authlog.event(authlog.TOKEN_REFRESHED, "grace")
                return OAuthToken(
                    access_token=grace.new_access_token,
                    token_type="bearer",
                    expires_in=ACCESS_TTL_SECONDS,
                    scope=" ".join(scopes) if scopes else None,
                    refresh_token=grace.new_refresh_token,
                )
            self.store.revoke_family(row.family_id)
            authlog.event(authlog.REFRESH_REUSE_REVOKED, "revoked")
            raise TokenError(error="invalid_grant", error_description="refresh token reuse")

        if row.revoked or row.expires_at < now:
            raise TokenError(error="invalid_grant", error_description="invalid refresh token")

        new_tokens = self._issue_pair(
            client_id=client.client_id,
            scopes=scopes,
            resource=row.resource,
            subject=row.subject,
            family_id=row.family_id,
        )
        self.store.rotate_refresh(
            old_digest,
            row.family_id,
            new_tokens.access_token,
            new_tokens.refresh_token or "",
            now,
        )
        authlog.event(authlog.TOKEN_REFRESHED, "ok")
        return new_tokens

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self.store.get_access_token(digest(self.config.token_pepper, token))
        if row is None or row.revoked:
            return None
        if row.expires_at < int(time.time()):
            return None
        return AccessToken(
            token=token,
            client_id=row.client_id,
            scopes=row.scopes,
            expires_at=row.expires_at,
            resource=row.resource,
            subject=row.subject,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        self.store.revoke_token_digest(digest(self.config.token_pepper, token.token))

    def issue_authorization_code(self, pending: PendingRequest, granted_scopes: list[str], subject: str) -> str:
        code = new_token()
        now = int(time.time())
        self.store.save_auth_code(
            AuthCodeRow(
                code_digest=digest(self.config.token_pepper, code),
                client_id=pending.client_id,
                scopes=granted_scopes,
                expires_at=now + CODE_TTL,
                code_challenge=pending.code_challenge,
                redirect_uri=pending.redirect_uri,
                redirect_uri_provided_explicitly=pending.redirect_uri_provided_explicitly,
                resource=pending.resource,
                subject=subject,
                consumed=False,
            )
        )
        self.store.delete_pending(pending.id)
        return code

    def _issue_pair(
        self,
        *,
        client_id: str,
        scopes: list[str],
        resource: str | None,
        subject: str | None,
        family_id: str,
    ) -> OAuthToken:
        now = int(time.time())
        access = new_token()
        refresh = new_token()
        self.store.save_access_token(
            TokenRow(
                token_digest=digest(self.config.token_pepper, access),
                client_id=client_id,
                scopes=scopes,
                expires_at=now + ACCESS_TTL_SECONDS,
                resource=resource,
                subject=subject,
                family_id=family_id,
                revoked=False,
            )
        )
        self.store.save_refresh_token(
            TokenRow(
                token_digest=digest(self.config.token_pepper, refresh),
                client_id=client_id,
                scopes=scopes,
                expires_at=now + REFRESH_TTL_SECONDS,
                resource=resource,
                subject=subject,
                family_id=family_id,
                revoked=False,
            )
        )
        self.store.touch_client(client_id, now)
        return OAuthToken(
            access_token=access,
            token_type="bearer",
            expires_in=ACCESS_TTL_SECONDS,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh,
        )

