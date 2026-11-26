"""Command line: build the index, run the MCP server, search, or check log privacy."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from collections import Counter

from .index import build_index
from .records import validate_records
from .search import search


def _report(records: Path, show_paths: bool) -> int:
    """Print a validation summary. Returns the number of invalid records.

    By default only fixed error codes and counts are printed: file names can be
    sensitive and this output may end up in server logs (ADR 007).
    """
    valid, errors = validate_records(records)
    print(f"valid: {len(valid)}  invalid: {len(errors)}", file=sys.stderr)
    for code, count in sorted(Counter(e.code for e in errors).items()):
        print(f"  {code}: {count}", file=sys.stderr)
    if show_paths:
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
    return len(errors)


def _build(records: Path, db: Path, show_paths: bool = False) -> int:
    if _report(records, show_paths):
        print("BUILD_FAILED: index not changed", file=sys.stderr)
        return 1
    count = build_index(records, db)
    print(f"indexed {count} records", file=sys.stderr)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="personal-brain")
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="rebuild the index from a records directory")
    build.add_argument("--records", type=Path, required=True)
    build.add_argument("--db", type=Path, required=True)
    build.add_argument("--show-paths", action="store_true", help="name invalid files (local use only)")

    check_records = sub.add_parser("validate", help="validate records without building")
    check_records.add_argument("--records", type=Path, required=True)
    check_records.add_argument("--show-paths", action="store_true", help="name invalid files (local use only)")

    serve = sub.add_parser("serve", help="run the MCP server")
    serve.add_argument("--db", type=Path, required=True)
    serve.add_argument("--records", type=Path, help="rebuild the index from here before serving")
    serve.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--domains",
        help="comma-separated scope, e.g. 'training'; default: all domains",
    )

    find = sub.add_parser("search", help="search the index and print JSON")
    find.add_argument("--db", type=Path, required=True)
    find.add_argument("query")
    find.add_argument("--limit", type=int, default=5)
    find.add_argument("--domain")

    run_eval = sub.add_parser("eval", help="run the retrieval evaluation")
    run_eval.add_argument("--cases", type=Path, required=True)
    run_eval.add_argument("--records", type=Path, required=True)
    run_eval.add_argument("--markdown", type=Path, help="write the summary table here")
    run_eval.add_argument("--json", type=Path, help="write the full report here")

    check = sub.add_parser("check-logs", help="verify that query terms never reach the logs")
    check.add_argument("--url", required=True, help="MCP endpoint, e.g. http://127.0.0.1:8000/mcp")
    source = check.add_mutually_exclusive_group(required=True)
    source.add_argument("--log-file", type=Path)
    source.add_argument("--logs-command", help='e.g. "docker logs personal-brain"')

    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page

    if args.command == "build":
        return _build(args.records, args.db, args.show_paths)

    if args.command == "validate":
        return 1 if _report(args.records, args.show_paths) else 0

    if args.command == "serve":
        from .server import create_server

        if args.records is not None and _build(args.records, args.db) != 0:
            # Keep serving the last good index rather than going down (ADR 012).
            if not args.db.exists():
                return 1
            print("SERVING_PREVIOUS_INDEX", file=sys.stderr)
        domains = None
        if args.domains:
            from .records import DOMAINS

            domains = [d.strip() for d in args.domains.split(",") if d.strip()]
            unknown = sorted(set(domains) - DOMAINS)
            if unknown:
                print(f"error: unknown domain(s): {', '.join(unknown)}", file=sys.stderr)
                return 1
        server = create_server(args.db, domains)
        if args.transport == "http":
            server.run("streamable-http", host=args.host, port=args.port)
        else:
            server.run()
        return 0

    if args.command == "eval":
        import tempfile

        from .evaluation import evaluate, is_passing, load_cases, to_markdown

        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "eval.db"
            if _build(args.records, db) != 0:
                return 1
            report = evaluate(db, load_cases(args.cases))
        summary = to_markdown(report)
        print(summary)
        # Failures list case ids and reason codes only, never queries or record content.
        for failure in report["failures"]:
            tag = "FAIL" if failure["gating"] else "info"
            print(f"{tag} {failure['id']}: {', '.join(failure['reasons'])}")
        if args.markdown:
            args.markdown.write_text(summary, encoding="utf-8")
        if args.json:
            args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0 if is_passing(report) else 1

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

    domains = [args.domain] if args.domain else None
    results = search(args.db, args.query, args.limit, domains)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
