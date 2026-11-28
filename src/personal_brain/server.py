"""MCP server exposing read-only tools over the index.

Two tools only (docs/adr/006-read-only-tools-first.md). Tool descriptions tell the
client how to treat pending records, because the model reading the result is the
one that must not present them as facts.

`allowed_domains` is the server's deployment scope (docs/adr/011-domains-and-scopes.md).
When OAuth is on, the token scopes narrow that scope (docs/adr/015-oauth-with-github-login.md).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from . import search as queries
from .auth.scopes import domains_from_scopes, intersect_domains

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

PENDING_NOTE = (
    "Records with review_status 'pending' were not confirmed by the owner yet: "
    "never present them as facts. Always cite the 'source' of each record you use."
)


def _effective_request_domains(deployment: list[str] | None, auth_enabled: bool) -> list[str] | None:
    """Resolve the caller's domain scope for this request."""
    if not auth_enabled:
        return None if deployment is None else list(deployment)
    token = get_access_token()
    token_domains = domains_from_scopes(token.scopes if token else [])
    return intersect_domains(deployment, token_domains)


def create_server(
    db_path: Path,
    allowed_domains: Iterable[str] | None = None,
    *,
    auth_settings: AuthSettings | None = None,
    auth_provider: Any | None = None,
) -> MCPServer:
    scope = None if allowed_domains is None else sorted(set(allowed_domains))
    scope_note = f" Domains available: {', '.join(scope)}." if scope is not None else ""
    auth_enabled = auth_provider is not None

    # WARNING keeps request-level chatter out of the logs (docs/adr/007-no-content-in-logs.md).
    server = MCPServer(
        "personal-brain",
        log_level="WARNING",
        auth=auth_settings,
        auth_server_provider=auth_provider,
    )

    @server.tool(
        description=(
            "Search personal records by keywords, optionally within one domain "
            "(for example 'health' or 'training'). Optional filters: date_from and "
            "date_to (YYYY, YYYY-MM or YYYY-MM-DD; a record with a partial date matches "
            "when its period overlaps), and review_status ('pending' or 'confirmed'). "
            "The query may be empty when a filter is given: results are then listed "
            f"newest first.{scope_note} {PENDING_NOTE}"
        ),
        annotations=READ_ONLY,
    )
    def search(
        query: str = "",
        limit: int = 5,
        domain: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        review_status: str | None = None,
    ) -> list[dict] | dict:
        try:
            return queries.search(
                db_path,
                query,
                limit,
                queries.effective_domains(_effective_request_domains(scope, auth_enabled), domain),
                date_from=date_from,
                date_to=date_to,
                review_status=review_status,
            )
        except queries.FilterError as exc:
            return {"error": "invalid_filter", "detail": str(exc)}

    @server.tool(
        description=f"Read one full record by its id.{scope_note} {PENDING_NOTE}",
        annotations=READ_ONLY,
    )
    def read_entry(id: str) -> dict:
        entry = queries.read_entry(db_path, id, _effective_request_domains(scope, auth_enabled))
        if entry is None:
            # Same answer for "missing" and "outside your scope": existence is not leaked.
            return {"error": "not_found"}
        return entry

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> PlainTextResponse:
        # Liveness only: answers without touching records.
        return PlainTextResponse("ok")

    return server
