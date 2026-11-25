"""Log privacy check (docs/adr/007-no-content-in-logs.md).

Sends queries made of random canary terms to a running server, then searches the
server logs for those terms. Any hit means query content reached the logs.
"""

from __future__ import annotations

import asyncio
import secrets

from mcp import Client


def make_canaries(count: int = 3) -> list[str]:
    # Letters only, so the tokenizer keeps each canary as one word.
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return ["canary" + "".join(secrets.choice(alphabet) for _ in range(16)) for _ in range(count)]


async def send_canaries(url: str, canaries: list[str]) -> None:
    async with Client(url) as client:
        for term in canaries:
            for name, arguments in (("search", {"query": term}), ("read_entry", {"id": term})):
                result = await client.call_tool(name, arguments)
                # A failed call would make the check pass without exercising the server.
                if getattr(result, "is_error", False) or getattr(result, "isError", False):
                    raise RuntimeError(f"tool call failed: {name}")


def find_leaks(log_text: str, canaries: list[str]) -> list[str]:
    lowered = log_text.lower()
    return [term for term in canaries if term.lower() in lowered]


def run_check(url: str, read_logs) -> list[str]:
    """Send canaries, then call `read_logs()` and return the canaries found in it."""
    canaries = make_canaries()
    asyncio.run(send_canaries(url, canaries))
    return find_leaks(read_logs(), canaries)
