"""Command line: build the index, run the MCP server, or search from the terminal."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .index import build_index
from .records import RecordError
from .search import search
from .server import create_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="personal-brain")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="rebuild the index from a records directory")
    build.add_argument("--records", type=Path, required=True)
    build.add_argument("--db", type=Path, required=True)

    serve = sub.add_parser("serve", help="run the MCP server over stdio")
    serve.add_argument("--db", type=Path, required=True)

    find = sub.add_parser("search", help="search the index and print JSON")
    find.add_argument("--db", type=Path, required=True)
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=5)

    args = parser.parse_args(argv)

    if args.command == "build":
        try:
            count = build_index(args.records, args.db)
        except RecordError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"indexed {count} records")
        return 0

    if args.command == "serve":
        create_server(args.db).run()
        return 0

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
    print(json.dumps(search(args.db, args.query, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
