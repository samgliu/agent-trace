"""SQLite row mapping and query helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

from agenttrace.core.models import Span, parse_datetime, serialize_datetime
from agenttrace.core.summary import execution_status


def span_row(span: Span) -> tuple[Any, ...]:
    return (
        span.span_id,
        span.trace_id,
        span.parent_id,
        span.name,
        span.span_type,
        serialize_datetime(span.started_at),
        serialize_datetime(span.ended_at),
        to_json(span.input),
        to_json(span.output),
        to_json(span.error),
        to_json(span.span_data),
        span.input_tokens,
        span.output_tokens,
        span.estimated_cost,
    )


def span_from_row(row: sqlite3.Row) -> Span:
    return Span(
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_id=row["parent_id"],
        name=row["name"],
        span_type=row["span_type"],
        started_at=parse_datetime(row["started_at"]),
        ended_at=parse_datetime(row["ended_at"]),
        input=from_json(row["input_json"]),
        output=from_json(row["output_json"]),
        error=from_json(row["error_json"]),
        span_data=from_json(row["span_data_json"]) or {},
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        estimated_cost=row["estimated_cost"],
    )


def to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def from_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def summary_row(summary: dict[str, Any]) -> tuple[Any, ...]:
    return (
        summary["trace_id"],
        summary["workflow_name"],
        summary["group_id"],
        summary["status"],
        summary["started_at"],
        summary["ended_at"],
        summary["duration_ms"],
        summary["source_format"],
        summary["source_kind"],
        summary["ingested_at"],
        to_json(summary["metadata"]),
        summary["span_count"],
        summary["input_tokens"],
        summary["output_tokens"],
        summary["estimated_cost"],
        summary["error_count"],
        summary["approval_total_count"],
        summary["approval_pending_count"],
        summary["approval_approved_count"],
        summary["approval_rejected_count"],
        summary["grounding_status"],
        summary["unsupported_claim_count"],
        summary["memory_read_count"],
        summary["memory_write_count"],
        summary["memory_retrieved_count"],
        summary["memory_ignored_count"],
        summary["memory_stale_count"],
        summary["memory_warning_count"],
        summary["memory_average_relevance"],
    )


def summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "trace_id": row["trace_id"],
        "workflow_name": row["workflow_name"],
        "group_id": row["group_id"],
        "status": execution_status(row["status"]),
        "source_format": row["source_format"],
        "source_kind": row["source_kind"],
        "metadata": from_json(row["metadata_json"]) or {},
        "ingested_at": row["ingested_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_ms": row["duration_ms"],
        "span_count": row["span_count"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "estimated_cost": row["estimated_cost"],
        "error_count": row["error_count"],
        "approval_total_count": row["approval_total_count"],
        "approval_pending_count": row["approval_pending_count"],
        "approval_approved_count": row["approval_approved_count"],
        "approval_rejected_count": row["approval_rejected_count"],
        "grounding_status": row["grounding_status"],
        "unsupported_claim_count": row["unsupported_claim_count"],
        "memory_read_count": row["memory_read_count"],
        "memory_write_count": row["memory_write_count"],
        "memory_retrieved_count": row["memory_retrieved_count"],
        "memory_ignored_count": row["memory_ignored_count"],
        "memory_stale_count": row["memory_stale_count"],
        "memory_warning_count": row["memory_warning_count"],
        "memory_average_relevance": row["memory_average_relevance"],
    }


def chat_session_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "session_id": row["session_id"],
        "customer_email": row["customer_email"],
        "title": row["title"],
        "metadata": from_json(row["metadata_json"]) or {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def chat_message_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "message_id": row["message_id"],
        "session_id": row["session_id"],
        "role": row["role"],
        "content": row["content"],
        "trace_id": row["trace_id"],
        "metadata": from_json(row["metadata_json"]) or {},
        "created_at": row["created_at"],
    }


def workflow_run_row(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run["run_id"],
        run["workflow_name"],
        run["status"],
        run["trace_id"],
        run["error"],
        1 if run["cancel_requested"] else 0,
        to_json(run["input"]),
        run["started_at"],
        run["updated_at"],
        run["completed_at"],
    )


def workflow_run_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "workflow_name": row["workflow_name"],
        "status": row["status"],
        "trace_id": row["trace_id"],
        "error": row["error"],
        "cancel_requested": bool(row["cancel_requested"]),
        "input": from_json(row["input_json"]) or {},
        "started_at": row["started_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
    }


def eval_run_row(run: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run["run_id"],
        run["suite_id"],
        run["name"],
        run["execution_mode"],
        run["model_provider"],
        run["model_name"],
        run["status"],
        run["error"],
        run["total"],
        run["passed"],
        run["failed"],
        run["pass_rate"],
        run["created_at"],
    )


def eval_case_result_row(run_id: str, result: dict[str, Any]) -> tuple[Any, ...]:
    return (
        run_id,
        result["case_id"],
        result["name"],
        result["trace_id"],
        1 if result["passed"] else 0,
        result["score"],
        to_json(result["checks"]),
        to_json(result.get("model_events", [])),
    )


def eval_run_summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": row["run_id"],
        "suite_id": row["suite_id"],
        "name": row["name"],
        "execution_mode": row["execution_mode"],
        "model_provider": row["model_provider"],
        "model_name": row["model_name"],
        "status": row["status"],
        "error": row["error"],
        "total": row["total"],
        "passed": row["passed"],
        "failed": row["failed"],
        "pass_rate": row["pass_rate"],
        "created_at": row["created_at"],
    }


def eval_run_from_row(run_row: sqlite3.Row, case_rows: list[sqlite3.Row]) -> dict[str, Any]:
    return {
        **eval_run_summary_from_row(run_row),
        "results": [
            {
                "case_id": row["case_id"],
                "name": row["name"],
                "trace_id": row["trace_id"],
                "passed": bool(row["passed"]),
                "score": row["score"],
                "checks": from_json(row["checks_json"]) or [],
                "model_events": from_json(row["model_events_json"]) or [],
            }
            for row in case_rows
        ],
    }


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def summary_filters(
    *,
    status: str | None,
    workflow_name: str | None,
    approval_status: str | None,
    grounding_status: str | None,
    source_format: str | None,
    source_kind: str | None,
    chat_session_id: str | None,
    has_errors: bool | None,
    started_after: str | None,
    started_before: str | None,
) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        if status == "passed":
            clauses.append("status IN (?, ?, ?)")
            params.extend(["passed", "grounded", "recovered"])
        else:
            clauses.append("status = ?")
            params.append(status)
    if workflow_name:
        clauses.append("workflow_name = ?")
        params.append(workflow_name)
    if approval_status:
        if approval_status == "pending":
            clauses.append("approval_pending_count > 0")
        elif approval_status == "approved":
            clauses.append("approval_approved_count > 0")
        elif approval_status == "rejected":
            clauses.append("approval_rejected_count > 0")
        elif approval_status == "none":
            clauses.append("approval_total_count = 0")
    if grounding_status:
        clauses.append("grounding_status = ?")
        params.append(grounding_status)
    if source_format:
        clauses.append("source_format = ?")
        params.append(source_format)
    if source_kind:
        clauses.append("source_kind = ?")
        params.append(source_kind)
    if chat_session_id:
        clauses.append("metadata_json LIKE ? ESCAPE '\\'")
        params.append(f'%"chat_session_id": "{escape_like(chat_session_id)}"%')
    if has_errors is True:
        clauses.append("error_count > 0")
    elif has_errors is False:
        clauses.append("error_count = 0")
    if started_after:
        clauses.append("started_at >= ?")
        params.append(started_after)
    if started_before:
        clauses.append("started_at <= ?")
        params.append(started_before)
    if not clauses:
        return "", tuple(params)
    return "WHERE " + " AND ".join(clauses), tuple(params)


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def ensure_columns(connection: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column_name, column_type in columns.items():
        if column_name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
    connection.commit()
