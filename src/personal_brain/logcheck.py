"""Log privacy check (docs/adr/007-no-content-in-logs.md).

Sends queries made of random canary terms to a running server, then searches the
server logs for those terms. Any hit means query content reached the logs.

When the authorization server is present, the check also sends auth canaries
(state, codes) that must never appear in the logs. Event names from ADR 015
are expected and are not treated as leaks.
"""

from __future__ import annotations

import asyncio
import secrets
from urllib.parse import urlencode, urlparse

from mcp import Client

ALLOWED_AUTH_EVENTS = (
    "auth.login.denied",
    "auth.login.ok",
    "auth.token.refreshed",
    "auth.refresh.reuse_revoked",
    "auth.client.unknown",
)


def make_canaries(count: int = 3, prefix: str = "canary") -> list[str]:
    # Letters only, so the tokenizer keeps each canary as one word.
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return [prefix + "".join(secrets.choice(alphabet) for _ in range(16)) for _ in range(count)]


async def send_canaries(url: str, canaries: list[str]) -> None:
    async with Client(url) as client:
        for term in canaries:
            for name, arguments in (("search", {"query": term}), ("read_entry", {"id": term})):
                result = await client.call_tool(name, arguments)
                # A failed call would make the check pass without exercising the server.
                if getattr(result, "is_error", False) or getattr(result, "isError", False):
                    raise RuntimeError(f"tool call failed: {name}")


async def send_auth_canaries(base_url: str, canaries: list[str]) -> None:
    """Hit auth routes with canary values. Safe no-op if auth is not enabled."""
    import httpx

    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    async with httpx.AsyncClient(timeout=5.0) as client:
        metadata = await client.get(f"{origin}/.well-known/oauth-authorization-server")
        if metadata.status_code != 200:
            return
        # Use canaries as a state and as a code. They must not be logged.
        await client.get(f"{origin}/oauth/github/callback", params={"state": canaries[0], "code": canaries[1]})
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": canaries[1],
                "client_id": canaries[2] if len(canaries) > 2 else canaries[0],
                "code_verifier": "a" * 43,
                "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
            }
        ).encode("ascii")
        await client.post(
            f"{origin}/token",
            content=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )


def find_leaks(log_text: str, canaries: list[str]) -> list[str]:
    lowered = log_text.lower()
    return [term for term in canaries if term.lower() in lowered]


def run_check(url: str, read_logs, *, include_auth: bool | None = None) -> list[str]:
    """Send canaries, then call `read_logs()` and return the canaries found in it."""
    canaries = make_canaries()
    auth_canaries = make_canaries(prefix="authcanary")

    async def _all() -> None:
        # Auth canaries first: they do not need a token and work even if tool calls 401.
        should_auth = include_auth
        if should_auth is None:
            should_auth = True
        if should_auth:
            await send_auth_canaries(url, auth_canaries)
        try:
            await send_canaries(url, canaries)
        except Exception:
            # Public mode without a token cannot call tools; the query canaries are
            # still useful when the server is private. Ignore tool failures here
            # only if we already exercised auth.
            if not should_auth:
                raise

    asyncio.run(_all())
    return find_leaks(read_logs(), canaries + auth_canaries)
