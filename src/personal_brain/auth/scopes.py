"""Domain scopes from ADR 011 / ADR 015."""

from __future__ import annotations

from collections.abc import Iterable

from personal_brain.records import DOMAINS

DOMAIN_SCOPES: dict[str, str] = {
    domain: f"brain:{domain}:read" for domain in sorted(DOMAINS)
}
SCOPE_TO_DOMAIN: dict[str, str] = {scope: domain for domain, scope in DOMAIN_SCOPES.items()}
ALL_SCOPES: tuple[str, ...] = tuple(DOMAIN_SCOPES.values())


def domains_from_scopes(scopes: Iterable[str]) -> list[str]:
    """Return the domains granted by a token. Unknown scopes are ignored."""
    found = {SCOPE_TO_DOMAIN[scope] for scope in scopes if scope in SCOPE_TO_DOMAIN}
    return sorted(found)


def intersect_domains(
    deployment: Iterable[str] | None, token_domains: Iterable[str]
) -> list[str]:
    """A token can narrow the deployment scope, never widen it.

    No domain scope means the caller reads nothing.
    """
    granted = set(token_domains)
    if not granted:
        return []
    if deployment is None:
        return sorted(granted)
    return sorted(granted & set(deployment))
