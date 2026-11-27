"""Embedded OAuth 2.1 authorization server with GitHub as the identity proof (ADR 015)."""

from .config import AuthConfig, missing_auth_settings
from .scopes import (
    DOMAIN_SCOPES,
    SCOPE_TO_DOMAIN,
    domains_from_scopes,
    intersect_domains,
)

__all__ = [
    "DOMAIN_SCOPES",
    "SCOPE_TO_DOMAIN",
    "AuthConfig",
    "domains_from_scopes",
    "intersect_domains",
    "missing_auth_settings",
]
