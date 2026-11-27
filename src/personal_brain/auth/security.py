"""Opaque tokens and digest-only storage."""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32  # 256 bits


def new_token() -> str:
    """Return a URL-safe opaque token with 256 bits of entropy."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def digest(pepper: str, value: str) -> str:
    """HMAC-SHA256 digest, hex-encoded. Used for tokens and client secrets at rest."""
    return hmac.new(pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def digest_equals(pepper: str, value: str, expected_hex: str) -> bool:
    return hmac.compare_digest(digest(pepper, value), expected_hex)


def new_id(nbytes: int = 16) -> str:
    return secrets.token_urlsafe(nbytes)
