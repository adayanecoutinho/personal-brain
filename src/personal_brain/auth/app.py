"""Assemble the MCP server and the public ASGI app when --auth is on."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from mcp.server.auth.settings import (
    AuthSettings,
    ClientRegistrationOptions,
    RevocationOptions,
)
from mcp.server.mcpserver import MCPServer
from pydantic import AnyHttpUrl
from starlette.types import ASGIApp

from personal_brain.server import create_server

from .config import AuthConfig
from .github import GitHubIdentity, HttpxGitHubIdentity
from .middleware import ClientSecretDigestMiddleware, RateLimitMiddleware
from .provider import BrainOAuthProvider
from .routes import register_auth_pages
from .scopes import ALL_SCOPES
from .store import AuthStore


def build_auth_settings(config: AuthConfig) -> AuthSettings:
    return AuthSettings(
        issuer_url=AnyHttpUrl(config.issuer_url),
        resource_server_url=AnyHttpUrl(config.resource_server_url),
        validate_token_resource=True,
        client_registration_options=ClientRegistrationOptions(
            enabled=False,
            valid_scopes=list(ALL_SCOPES),
        ),
        revocation_options=RevocationOptions(enabled=True),
        identity_assertion_enabled=False,
    )


def build_provider(
    config: AuthConfig, github: GitHubIdentity | None = None
) -> BrainOAuthProvider:
    store = AuthStore(config.auth_db)
    identity = github or HttpxGitHubIdentity(config.github_client_id, config.github_client_secret)
    return BrainOAuthProvider(config, store, identity)


def build_authenticated_server(
    db_path: Path,
    config: AuthConfig,
    allowed_domains: Iterable[str] | None = None,
    github: GitHubIdentity | None = None,
) -> tuple[MCPServer, BrainOAuthProvider]:
    provider = build_provider(config, github)
    server = create_server(
        db_path,
        allowed_domains,
        auth_settings=build_auth_settings(config),
        auth_provider=provider,
    )
    register_auth_pages(server, provider)
    return server, provider


def wrap_app(app: ASGIApp, pepper: str) -> ASGIApp:
    app = ClientSecretDigestMiddleware(app, pepper)
    app = RateLimitMiddleware(app)
    return app
