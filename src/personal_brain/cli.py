"""Command line: build the index, run the MCP server, search, or check log privacy."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .index import build_index
from .records import RecordError
from .search import search


def _build(records: Path, db: Path) -> int:
    try:
        count = build_index(records, db)
    except RecordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"indexed {count} records", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="personal-brain")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="rebuild the index from a records directory")
    build.add_argument("--records", type=Path, required=True)
    build.add_argument("--db", type=Path, required=True)

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--db", type=Path, required=True)
    serve.add_argument("--records", type=Path, help="rebuild the index from here before serving")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    find = sub.add_parser("search", help="search the index and print JSON")
    find.add_argument("--db", type=Path, required=True)
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=5)

    check = sub.add_parser("check-logs", help="verify that query terms never reach the logs")
    check.add_argument("--url", required=True, help="MCP endpoint, e.g. http://127.0.0.1:8000/mcp")
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument("--log-file", type=Path)
    source.add_argument("--logs-command", help='e.g. "docker logs personal-brain"')

    args = parser.parse_args(argv)

    if args.command == "build":
        return _build(args.records, args.db)

    if args.command == "serve":
        from .server import create_server

        if args.records is not None and _build(args.records, args.db) != 0:
            return 1
        server = create_server(args.db)
        if args.transport == "http":
            server.run("streamable-http", host=args.host, port=args.port)
        else:
            server.run()
        return 0

    if args.command == "check-logs":
        from .logcheck import run_check

        def read_logs() -> str:
            if args.log_file is not None:
                return args.log_file.read_text(encoding="utf-8", errors="replace")
            done = subprocess.run(
                args.logs_command, shell=True, capture_output=True, text=True, check=True
            )
            return done.stdout + done.stderr

        leaks = run_check(args.url, read_logs)
        if leaks:
            print(f"FAIL: {len(leaks)} query term(s) found in the logs", file=sys.stderr)
            return 1
        print("PASS: no query terms found in the logs")
        return 0

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
    print(json.dumps(search(args.db, args.query, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
