"""GitHub callback and consent routes (custom_route, not behind bearer auth)."""

from __future__ import annotations

import hmac
from urllib.parse import urlparse

import httpx
from mcp.server.auth.provider import construct_redirect_uri
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response

from . import logging as authlog
from .pages import apply_auth_headers, consent_page, denied_page, html_auth_response
from .provider import BrainOAuthProvider
from .scopes import SCOPE_TO_DOMAIN
from .security import new_id


def denied_response() -> HTMLResponse:
    authlog.event(authlog.LOGIN_DENIED, "denied")
    return html_auth_response(denied_page(), status_code=403)


def register_auth_pages(server, provider: BrainOAuthProvider) -> None:
    @server.custom_route("/oauth/github/callback", methods=["GET"], include_in_schema=False)
    async def github_callback(request: Request) -> Response:
        state = request.query_params.get("state") or ""
        if not state:
            return denied_response()
        pending = provider.store.get_pending_by_state(state)
        if pending is None or not provider.store.is_pending_fresh(pending):
            return denied_response()
        if not provider.store.mark_state_used(state):
            return denied_response()
        if request.query_params.get("error"):
            return denied_response()
        code = request.query_params.get("code") or ""
        if not code:
            return denied_response()
        github_token = None
        try:
            github_token = await provider.github.exchange_code(
                code=code, redirect_uri=provider.config.github_callback_url
            )
            user_id = await provider.github.fetch_user_id(github_token)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, httpx.HTTPError):
            return denied_response()
        finally:
            github_token = None
            del github_token
        if user_id != provider.config.allowed_github_user_id:
            return denied_response()
        csrf = new_id()
        provider.store.mark_github_ok(pending.id, csrf, subject=str(user_id))
        action = f"/oauth/consent?request={pending.id}"
        host = urlparse(pending.redirect_uri).hostname or ""
        return html_auth_response(
            consent_page(
                action=action,
                csrf=csrf,
                scopes=pending.scopes,
                client_id=pending.client_id,
                redirect_host=host,
            )
        )

    @server.custom_route("/oauth/consent", methods=["POST"], include_in_schema=False)
    async def consent(request: Request) -> Response:
        pending_id = request.query_params.get("request") or ""
        pending = provider.store.get_pending(pending_id)
        if (
            pending is None
            or not pending.github_ok
            or not provider.store.is_pending_fresh(pending)
            or not pending.consent_csrf
            or not pending.subject
        ):
            return denied_response()
        form = await request.form()
        csrf = str(form.get("csrf") or "")
        if not hmac.compare_digest(csrf, pending.consent_csrf):
            return denied_response()
        requested = set(pending.scopes)
        granted: list[str] = []
        for raw in form.getlist("scope"):
            scope = str(raw)
            if scope in requested and scope in SCOPE_TO_DOMAIN:
                granted.append(scope)
        granted = list(dict.fromkeys(granted))
        if not granted:
            return denied_response()
        code = provider.issue_authorization_code(pending, granted, pending.subject)
        authlog.event(authlog.LOGIN_OK, "ok")
        redirect = construct_redirect_uri(
            pending.redirect_uri,
            code=code,
            state=pending.client_state,
        )
        return apply_auth_headers(RedirectResponse(url=redirect, status_code=302))
