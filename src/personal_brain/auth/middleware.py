"""Adapters the SDK needs: hash client secrets before the SDK compares them, and rate-limit."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.requests import Request
from starlette.types import ASGIApp, Receive, Scope, Send

from .security import digest

LIMITED_PATHS = ("/authorize", "/token", "/oauth/github/callback")
WINDOW_SECONDS = 60
MAX_REQUESTS = 60


class ClientSecretDigestMiddleware:
    """The SDK compares client_secret in constant time against get_client().

    We store only a digest, so this middleware hashes the presented secret with
    TOKEN_PEPPER before the SDK sees it. The database never holds the raw secret.
    """

    def __init__(self, app: ASGIApp, pepper: str) -> None:
        self.app = app
        self.pepper = pepper

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path not in ("/token", "/revoke") or scope.get("method") != "POST":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        auth = request.headers.get("authorization")
        new_headers = [
            (k, v) for k, v in scope["headers"] if k.lower() not in (b"authorization", b"content-length")
        ]
        if auth and auth.lower().startswith("basic "):
            import base64
            import binascii
            from urllib.parse import unquote

            try:
                decoded = base64.b64decode(auth[6:].encode("ascii")).decode("utf-8")
                client_id, secret = decoded.split(":", 1)
                client_id, secret = unquote(client_id), unquote(secret)
                hashed = digest(self.pepper, secret)
                token = base64.b64encode(f"{client_id}:{hashed}".encode()).decode("ascii")
                new_headers.append((b"authorization", f"Basic {token}".encode("ascii")))
            except (ValueError, UnicodeDecodeError, binascii.Error):
                new_headers.append((b"authorization", auth.encode("latin-1")))
        elif auth:
            new_headers.append((b"authorization", auth.encode("latin-1")))

        form = await request.form()
        items: list[tuple[bytes, bytes]] = []
        for key, value in form.multi_items():
            text = value if isinstance(value, str) else str(value)
            if key == "client_secret":
                text = digest(self.pepper, text)
            items.append((key.encode("utf-8"), text.encode("utf-8")))
        body = b"&".join(k + b"=" + _quote(v) for k, v in items)
        new_headers.append((b"content-type", b"application/x-www-form-urlencoded"))
        new_headers.append((b"content-length", str(len(body)).encode("ascii")))

        sent = False

        async def new_receive() -> dict:
            nonlocal sent
            if sent:
                return {"type": "http.request", "body": b"", "more_body": False}
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}

        new_scope = dict(scope)
        new_scope["headers"] = new_headers
        await self.app(new_scope, new_receive, send)


def _quote(value: bytes) -> bytes:
    from urllib.parse import quote

    return quote(value.decode("utf-8"), safe="").encode("ascii")


class RateLimitMiddleware:
    """Simple in-process limit on /authorize, /token and the GitHub callback."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        max_requests: int = MAX_REQUESTS,
        window_seconds: int = WINDOW_SECONDS,
    ) -> None:
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if path not in LIMITED_PATHS:
            await self.app(scope, receive, send)
            return
        client = (scope.get("client") or ("unknown", 0))[0]
        key = (client, path)
        now = time.monotonic()
        bucket = self._hits[key]
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_requests:
            body = b'{"error":"temporarily_unavailable"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 429,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"retry-after", b"60"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        bucket.append(now)
        await self.app(scope, receive, send)
