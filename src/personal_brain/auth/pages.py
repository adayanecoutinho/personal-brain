"""User-facing HTML for login denial and consent. No third-party JavaScript."""

from __future__ import annotations

import html

from starlette.responses import HTMLResponse, Response

from .scopes import SCOPE_TO_DOMAIN

AUTH_PAGE_HEADERS = {
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'unsafe-inline'; "
        "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
    ),
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
}


def apply_auth_headers(response: Response) -> Response:
    """Attach the anti-clickjacking and cache headers used on every auth page."""
    for name, value in AUTH_PAGE_HEADERS.items():
        response.headers[name] = value
    return response


def html_auth_response(content: str, status_code: int = 200) -> HTMLResponse:
    return apply_auth_headers(HTMLResponse(content, status_code=status_code))


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
