"""Public-mode configuration. Secrets come from the environment, never from flags."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REQUIRED_ENV = (
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "ALLOWED_GITHUB_USER_ID",
    "TOKEN_PEPPER",
)


@dataclass(frozen=True)
class AuthConfig:
    github_client_id: str
    github_client_secret: str
    allowed_github_user_id: int
    token_pepper: str
    public_url: str
    auth_db: Path
    issuer_url: str
    resource_server_url: str

    @property
    def github_callback_url(self) -> str:
        return f"{self.public_url.rstrip('/')}/oauth/github/callback"


def _normalize_public_url(url: str) -> str:
    return url.strip().rstrip("/")


def missing_auth_settings(
    *,
    public_url: str | None,
    auth_db: Path | str | None,
    env: dict[str, str] | None = None,
) -> list[str]:
    """Names of the required settings that are missing. Used to refuse start-up."""
    source = os.environ if env is None else env
    missing: list[str] = []
    for name in REQUIRED_ENV:
        if not (source.get(name) or "").strip():
            missing.append(name)
    if not (public_url or "").strip():
        missing.append("--public-url")
    if not auth_db:
        missing.append("--auth-db")
    return missing


def load_auth_config(*, public_url: str, auth_db: Path, env: dict[str, str] | None = None) -> AuthConfig:
    source = os.environ if env is None else env
    missing = missing_auth_settings(public_url=public_url, auth_db=auth_db, env=dict(source))
    if missing:
        raise ValueError("missing auth settings: " + ", ".join(missing))

    raw_id = source["ALLOWED_GITHUB_USER_ID"].strip()
    try:
        allowed = int(raw_id)
    except ValueError as exc:
        raise ValueError("ALLOWED_GITHUB_USER_ID must be a numeric GitHub user id") from exc

    base = _normalize_public_url(public_url)
    return AuthConfig(
        github_client_id=source["GITHUB_CLIENT_ID"].strip(),
        github_client_secret=source["GITHUB_CLIENT_SECRET"].strip(),
        allowed_github_user_id=allowed,
        token_pepper=source["TOKEN_PEPPER"],
        public_url=base,
        auth_db=Path(auth_db),
        issuer_url=base,
        resource_server_url=f"{base}/mcp",
    )
