"""Auth logs: event names and outcomes only (ADR 007 / ADR 015)."""

from __future__ import annotations

import logging

logger = logging.getLogger("personal_brain.auth")

LOGIN_DENIED = "auth.login.denied"
LOGIN_OK = "auth.login.ok"
TOKEN_REFRESHED = "auth.token.refreshed"
REFRESH_REUSE_REVOKED = "auth.refresh.reuse_revoked"
CLIENT_UNKNOWN = "auth.client.unknown"


def event(name: str, result: str = "ok") -> None:
    """Log an auth event without tokens, codes, state, secrets or GitHub payloads."""
    logger.info("%s %s", name, result)
