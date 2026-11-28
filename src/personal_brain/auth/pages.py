"""User-facing HTML for login denial and consent. No third-party JavaScript."""

from __future__ import annotations

import html
from urllib.parse import urlparse

from starlette.responses import HTMLResponse, Response

from .scopes import SCOPE_TO_DOMAIN

_DEFAULT_PORTS = {"http": 80, "https": 443}
_CSP_UNSAFE = frozenset(" \t\r\n;,'\"\\")


def safe_form_action_origin(redirect_uri: str) -> str | None:
    """Return a CSP origin for form-action, or None if the URI is not safe.

    Only https, or http with hostname localhost, is accepted. The result is
    scheme, host and port (when not the default) — never path, query or fragment.
    """
    if not redirect_uri or any(ch in redirect_uri for ch in "\t\r\n"):
        return None
    try:
        parsed = urlparse(redirect_uri)
    except ValueError:
        return None
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if parsed.username is not None or parsed.password is not None:
        return None
    if not host or scheme not in _DEFAULT_PORTS:
        return None
    if scheme == "http" and host != "localhost":
        return None
    try:
        host.encode("ascii")
        port = parsed.port
    except (UnicodeEncodeError, ValueError):
        return None
    if port == 0:
        return None
    host_part = f"[{host}]" if ":" in host else host
    if port is not None and port != _DEFAULT_PORTS[scheme]:
        origin = f"{scheme}://{host_part}:{port}"
    else:
        origin = f"{scheme}://{host_part}"
    if any(ch in origin for ch in _CSP_UNSAFE):
        return None
    return origin


def _auth_csp(form_action_origin: str | None = None) -> str:
    form_action = "form-action 'self'"
    if form_action_origin:
        form_action = f"form-action 'self' {form_action_origin}"
    return (
        "default-src 'none'; style-src 'unsafe-inline'; "
        f"{form_action}; frame-ancestors 'none'; base-uri 'none'"
    )


AUTH_PAGE_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": _auth_csp(),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def apply_auth_headers(
    response: Response, *, form_action_origin: str | None = None
) -> Response:
    """Attach the anti-clickjacking and cache headers used on every auth page."""
    for name, value in AUTH_PAGE_HEADERS.items():
        response.headers[name] = value
    if form_action_origin is not None:
        response.headers["Content-Security-Policy"] = _auth_csp(form_action_origin)
    return response


def html_auth_response(
    content: str,
    status_code: int = 200,
    *,
    form_action_origin: str | None = None,
) -> HTMLResponse:
    return apply_auth_headers(
        HTMLResponse(content, status_code=status_code),
        form_action_origin=form_action_origin,
    )


DENIED_HTML = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acesso negado</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; }
  </style>
</head>
<body>
  <h1>Acesso negado</h1>
  <p>Não foi possível concluir o acesso.</p>
</body>
</html>
"""


def denied_page() -> str:
    return DENIED_HTML


def consent_page(
    *,
    action: str,
    csrf: str,
    scopes: list[str],
    client_id: str,
    redirect_host: str,
) -> str:
    boxes = []
    for scope in scopes:
        domain = SCOPE_TO_DOMAIN.get(scope)
        if domain is None:
            continue
        label = html.escape(domain)
        value = html.escape(scope)
        boxes.append(
            f'<label><input type="checkbox" name="scope" value="{value}"> {label}</label>'
        )
    fields = "\n      ".join(boxes) or "<p>Nenhum domínio solicitado.</p>"
    action_esc = html.escape(action, quote=True)
    csrf_esc = html.escape(csrf, quote=True)
    client_esc = html.escape(client_id)
    host_esc = html.escape(redirect_host)
    return f"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Conceder acesso</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1a1a1a; max-width: 32rem; }}
    label {{ display: block; margin: 0.5rem 0; }}
    button {{ margin-top: 1rem; }}
  </style>
</head>
<body>
  <h1>Conceder acesso</h1>
  <p>Cliente: {client_esc}</p>
  <p>Retorno: {host_esc}</p>
  <p>Marque os domínios que este cliente pode ler. Nada é concedido por padrão.</p>
  <form method="post" action="{action_esc}">
    <input type="hidden" name="csrf" value="{csrf_esc}">
    {fields}
    <button type="submit">Conceder</button>
  </form>
</body>
</html>
"""
