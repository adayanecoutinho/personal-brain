import asyncio

from personal_brain.server import create_server


def test_server_exposes_only_read_tools(db):
    server = create_server(db)
    tools = asyncio.run(server.list_tools())
    names = sorted(tool.name for tool in tools)
    assert names == ["read_entry", "search"]
    for tool in tools:
        assert "pending" in tool.description
        assert "source" in tool.description
        assert tool.annotations.read_only_hint is True


def test_search_tool_returns_sourced_results(db):
    server = create_server(db)
    result = asyncio.run(server.call_tool("search", {"query": "blood"}))
    assert "exam-2026-04-02-blood" in str(result)
    assert ".md" in str(result)


def test_scoped_server_never_returns_other_domains(db):
    server = create_server(db, allowed_domains=["training"])
    found = str(asyncio.run(server.call_tool("search", {"query": "fictional", "limit": 20})))
    assert "train-method-progressive-overload" in found
    assert "exam-2026-04-02-blood" not in found
    # Asking explicitly for a domain outside the scope returns nothing.
    asked = str(asyncio.run(server.call_tool("search", {"query": "blood", "domain": "health"})))
    assert "exam-2026-04-02-blood" not in asked
    # Records outside the scope look exactly like missing ones.
    hidden = str(asyncio.run(server.call_tool("read_entry", {"id": "exam-2026-04-02-blood"})))
    missing = str(asyncio.run(server.call_tool("read_entry", {"id": "does-not-exist"})))
    assert hidden == missing
