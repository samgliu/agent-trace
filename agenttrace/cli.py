"""Command line interface for AgentTrace."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from agenttrace.core.importer import load_trace_file
from agenttrace.evals.support_triage import (
    build_eval_report,
    format_eval_report,
    run_support_triage_eval_suite,
)
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
        "--format",
        choices=["agenttrace", "openai-agents"],
        default="agenttrace",
        help="Input trace format. Defaults to agenttrace.",
    )
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
    show_parser.add_argument(
        "--verbose",
        action="store_true",
        help="Include full timestamps and additional span details in the timeline.",
    )

    live_parser = subparsers.add_parser("live-sample", help="Emit a live support-triage trace to the API.")
    live_parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="AgentTrace API base URL. Defaults to http://localhost:8000.",
    )
    live_parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay between emitted spans in seconds.",
    )

    eval_parser = subparsers.add_parser("eval", help="Run eval suites and print a CI-friendly report.")
    eval_subparsers = eval_parser.add_subparsers(dest="suite", required=True)
    support_eval_parser = eval_subparsers.add_parser("support-triage", help="Run the support-triage core eval suite.")
    support_eval_parser.add_argument(
        "--mode",
        choices=["deterministic", "llm"],
        default="deterministic",
        help="Eval execution mode. Deterministic is stable; llm uses configured model provider.",
    )
    support_eval_parser.add_argument(
        "--openai-api",
        choices=["chat_completions", "responses"],
        default="chat_completions",
        help="Model API surface to use for --mode llm.",
    )
    support_eval_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the compact eval report as JSON.",
    )
    support_eval_parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Return exit code 0 even when eval checks fail.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "eval":
        if args.suite == "support-triage":
            result = run_support_triage_eval_suite(execution_mode=args.mode, openai_api=args.openai_api)
            report = build_eval_report(result)
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(format_eval_report(report))
            return 0 if args.no_fail or report["status"] == "passed" else 1

    store = SQLiteTraceStore(Path(args.db))
    store.initialize()

    if args.command == "import":
        trace = load_trace_file(Path(args.path), trace_format=args.format)
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
            print(trace.format_timeline(verbose=args.verbose))
        return 0

    if args.command == "live-sample":
        emit_live_sample(api_url=args.api_url, delay=args.delay)
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


def emit_live_sample(*, api_url: str, delay: float) -> None:
    import httpx

    started_at = datetime.now(timezone.utc)
    trace_id = "live_support_triage_" + started_at.strftime("%Y%m%d%H%M%S")
    trace_payload = {
        "trace_id": trace_id,
        "workflow_name": "support-triage",
        "status": "running",
        "started_at": _timestamp(started_at),
        "metadata": {"source": "agenttrace-live-sample"},
        "spans": [],
    }
    spans = _live_sample_spans(trace_id, started_at)
    with httpx.Client(base_url=api_url, timeout=10.0) as client:
        response = client.post("/traces", json=trace_payload)
        response.raise_for_status()
        print(f"Started live trace {trace_id}")
        for span in spans:
            time.sleep(max(0, delay))
            response = client.post(f"/traces/{trace_id}/spans", json=span)
            response.raise_for_status()
            print(f"Emitted span {span['span_id']}: {span['name']}")
        response = client.patch(
            f"/traces/{trace_id}",
            json={"status": "passed", "ended_at": _timestamp(started_at + timedelta(seconds=7))},
        )
        response.raise_for_status()
        print(f"Completed live trace {trace_id}")


def _live_sample_spans(trace_id: str, started_at: datetime) -> list[dict[str, Any]]:
    return [
        {
            "span_id": "span_live_supervisor",
            "trace_id": trace_id,
            "name": "Supervisor Agent",
            "span_type": "agent",
            "started_at": _timestamp(started_at),
            "ended_at": _timestamp(started_at + timedelta(seconds=1)),
            "input_tokens": 140,
            "output_tokens": 32,
            "estimated_cost": 0.0004,
        },
        {
            "span_id": "span_live_triage",
            "trace_id": trace_id,
            "parent_id": "span_live_supervisor",
            "name": "Triage Agent",
            "span_type": "agent",
            "started_at": _timestamp(started_at + timedelta(seconds=1)),
            "ended_at": _timestamp(started_at + timedelta(seconds=2)),
            "input_tokens": 220,
            "output_tokens": 58,
            "estimated_cost": 0.0006,
        },
        {
            "span_id": "span_live_lookup_customer",
            "trace_id": trace_id,
            "parent_id": "span_live_triage",
            "name": "lookup_customer",
            "span_type": "function_tool",
            "started_at": _timestamp(started_at + timedelta(seconds=2)),
            "ended_at": _timestamp(started_at + timedelta(seconds=3)),
            "span_data": {"tool_protocol": "mcp", "tool_server": "support-tools-mcp"},
            "estimated_cost": 0.0,
        },
        {
            "span_id": "span_live_policy",
            "trace_id": trace_id,
            "parent_id": "span_live_supervisor",
            "name": "Policy Agent",
            "span_type": "agent",
            "started_at": _timestamp(started_at + timedelta(seconds=3)),
            "ended_at": _timestamp(started_at + timedelta(seconds=4)),
            "input_tokens": 360,
            "output_tokens": 92,
            "estimated_cost": 0.0011,
        },
        {
            "span_id": "span_live_validator",
            "trace_id": trace_id,
            "parent_id": "span_live_supervisor",
            "name": "Validator Agent",
            "span_type": "validation",
            "started_at": _timestamp(started_at + timedelta(seconds=5)),
            "ended_at": _timestamp(started_at + timedelta(seconds=6)),
            "output": {"grounded": True, "supported_claims": [{"claim": "support review request created"}]},
        },
    ]


def _timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    raise SystemExit(main())
