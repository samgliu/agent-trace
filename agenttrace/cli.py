"""Command line interface for AgentTrace."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agenttrace.core.importer import load_trace_file
from agenttrace.storage.sqlite import SQLiteTraceStore

DEFAULT_DB_PATH = Path(".agenttrace") / "agenttrace.db"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttrace",
        description="Import and inspect multi-agent workflow traces.",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="SQLite database path. Defaults to .agenttrace/agenttrace.db.",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="Import a trace JSON file.")
    import_parser.add_argument("path", help="Path to trace JSON.")
    import_parser.add_argument(
        "--pretty",
        action="store_true",
        help="Print imported trace metadata as JSON.",
    )

    subparsers.add_parser("list", help="List imported traces.")

    show_parser = subparsers.add_parser("show", help="Show a trace timeline.")
    show_parser.add_argument("trace_id", help="Trace ID to inspect.")
    show_parser.add_argument(
        "--json",
        action="store_true",
        help="Print spans as JSON instead of a text timeline.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = SQLiteTraceStore(Path(args.db))
    store.initialize()

    if args.command == "import":
        trace = load_trace_file(Path(args.path))
        store.save_trace(trace)
        if args.pretty:
            print(json.dumps(trace.to_dict(), indent=2, sort_keys=True))
        else:
            print(f"Imported trace {trace.trace_id} with {len(trace.spans)} spans.")
        return 0

    if args.command == "list":
        traces = store.list_traces()
        if not traces:
            print("No traces imported.")
            return 0
        for trace in traces:
            duration = ""
            if trace.duration_ms is not None:
                duration = f" ({trace.duration_ms}ms)"
            print(f"{trace.trace_id}\t{trace.workflow_name}\t{trace.status}{duration}")
        return 0

    if args.command == "show":
        trace = store.get_trace(args.trace_id)
        if trace is None:
            print(f"Trace not found: {args.trace_id}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(trace.to_dict(), indent=2, sort_keys=True))
        else:
            print(trace.format_timeline())
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
