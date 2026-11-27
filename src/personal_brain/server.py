"""MCP server exposing read-only tools over the index.

Two tools only (docs/adr/006-read-only-tools-first.md). Tool descriptions tell the
client how to treat pending records, because the model reading the result is the
one that must not present them as facts.

`allowed_domains` is the server's scope (docs/adr/011-domains-and-scopes.md). Today
it is set per deployment; from phase 3 it comes from the OAuth client's scopes.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations
from starlette.requests import Request
from starlette.responses import PlainTextResponse

from . import search as queries

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

PENDING_NOTE = (
    "Records with review_status 'pending' were not confirmed by the owner yet: "
    "never present them as facts. Always cite the 'source' of each record you use."
)


def create_server(db_path: Path, allowed_domains: Iterable[str] | None = None) -> MCPServer:
    scope = None if allowed_domains is None else sorted(set(allowed_domains))
    scope_note = f" Domains available: {', '.join(scope)}." if scope is not None else ""

    # WARNING keeps request-level chatter out of the logs (docs/adr/007-no-content-in-logs.md).
    server = MCPServer("personal-brain", log_level="WARNING")

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
                queries.effective_domains(scope, domain),
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
        entry = queries.read_entry(db_path, id, scope)
        if entry is None:
            # Same answer for "missing" and "outside your scope": existence is not leaked.
            return {"error": "not_found"}
        return entry

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> PlainTextResponse:
        # Liveness only: answers without touching records.
        return PlainTextResponse("ok")

    return server
