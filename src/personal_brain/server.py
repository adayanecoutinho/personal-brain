"""MCP server exposing read-only tools over the index.

Two tools only (docs/adr/006-read-only-tools-first.md). Tool descriptions tell the
client how to treat pending records, because the model reading the result is the
one that must not present them as facts.
"""

from __future__ import annotations

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


def create_server(db_path: Path) -> MCPServer:
    # WARNING keeps request-level chatter out of the logs (docs/adr/007-no-content-in-logs.md).
    server = MCPServer("personal-brain", log_level="WARNING")

    @server.tool(
        description=f"Search personal records by keywords. {PENDING_NOTE}",
        annotations=READ_ONLY,
    )
    def search(query: str, limit: int = 5) -> list[dict]:
        return queries.search(db_path, query, limit)

    @server.tool(
        description=f"Read one full record by its id. {PENDING_NOTE}",
        annotations=READ_ONLY,
    )
    def read_entry(id: str) -> dict:
        entry = queries.read_entry(db_path, id)
        if entry is None:
            return {"error": "not_found"}
        return entry

    @server.custom_route("/health", methods=["GET"], include_in_schema=False)
    async def health(_: Request) -> PlainTextResponse:
        # Liveness only: answers without touching records.
        return PlainTextResponse("ok")

    return server
