"""GitHub is only an identity proof: exchange a code, read the numeric user id, discard the token."""

from __future__ import annotations

from typing import Protocol
from urllib.parse import urlencode

import httpx

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
TIMEOUT = 10.0


class GitHubIdentity(Protocol):
    def authorization_url(self, *, state: str, redirect_uri: str) -> str: ...

    async def exchange_code(self, *, code: str, redirect_uri: str) -> str: ...

    async def fetch_user_id(self, access_token: str) -> int: ...


class HttpxGitHubIdentity:
    """Real GitHub OAuth, used only in production. Tests inject a fake."""

    def __init__(self, client_id: str, client_secret: str, http: httpx.AsyncClient | None = None) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "allow_signup": "false",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        async with self._client() as client:
            response = await client.post(
                TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
        token = payload.get("access_token")
        if not token:
            raise RuntimeError("github token exchange failed")
        return str(token)

    async def fetch_user_id(self, access_token: str) -> int:
        async with self._client() as client:
            response = await client.get(
                USER_URL,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/json",
                    "User-Agent": "personal-brain",
                },
            )
            response.raise_for_status()
            payload = response.json()
        return int(payload["id"])

    def _client(self) -> httpx.AsyncClient:
        if self._http is not None:
            return self._http
        return httpx.AsyncClient(timeout=TIMEOUT)


class FakeGitHubIdentity:
    """In-process GitHub stand-in for tests. No network."""

    def __init__(self, user_id: int, *, fail_exchange: bool = False) -> None:
        self.user_id = user_id
        self.fail_exchange = fail_exchange
        self.exchanged_codes: list[str] = []
        self.discarded_tokens: list[str] = []

    def authorization_url(self, *, state: str, redirect_uri: str) -> str:
        query = urlencode({"state": state, "redirect_uri": redirect_uri})
        return f"https://github.example.invalid/login/oauth/authorize?{query}"

    async def exchange_code(self, *, code: str, redirect_uri: str) -> str:
        del redirect_uri
        if self.fail_exchange:
            raise RuntimeError("github token exchange failed")
        self.exchanged_codes.append(code)
        return f"gho_fake_{code}"

    async def fetch_user_id(self, access_token: str) -> int:
        self.discarded_tokens.append(access_token)
        return self.user_id
