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
