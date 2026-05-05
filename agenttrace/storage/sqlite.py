"""SQLite storage for traces and spans."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from agenttrace.core.summary import build_trace_summary, execution_status
from agenttrace.core.models import Span, Trace, parse_datetime, serialize_datetime


class SQLiteTraceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS traces (
                    trace_id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    group_id TEXT,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    raw_json TEXT NOT NULL,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS spans (
                    span_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    parent_id TEXT,
                    name TEXT NOT NULL,
                    span_type TEXT NOT NULL,
                    started_at TEXT,
                    ended_at TEXT,
                    input_json TEXT,
                    output_json TEXT,
                    error_json TEXT,
                    span_data_json TEXT NOT NULL,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    estimated_cost REAL,
                    FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS trace_summaries (
                    trace_id TEXT PRIMARY KEY,
                    workflow_name TEXT NOT NULL,
                    group_id TEXT,
                    status TEXT NOT NULL,
                    source_format TEXT NOT NULL DEFAULT 'unknown',
                    source_kind TEXT NOT NULL DEFAULT 'unknown',
                    ingested_at TEXT,
                    started_at TEXT,
                    ended_at TEXT,
                    duration_ms INTEGER,
                    span_count INTEGER NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    estimated_cost REAL NOT NULL,
                    approval_total_count INTEGER NOT NULL,
                    approval_pending_count INTEGER NOT NULL,
                    approval_approved_count INTEGER NOT NULL,
                    approval_rejected_count INTEGER NOT NULL,
                    grounding_status TEXT NOT NULL,
                    unsupported_claim_count INTEGER NOT NULL,
                    FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
                )
                """
            )
            connection.commit()
            _ensure_columns(
                connection,
                "trace_summaries",
                {
                    "source_format": "TEXT NOT NULL DEFAULT 'unknown'",
                    "source_kind": "TEXT NOT NULL DEFAULT 'unknown'",
                    "ingested_at": "TEXT",
                },
            )
        self._backfill_trace_summaries()

    def save_trace(self, trace: Trace) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO traces (
                    trace_id, workflow_name, group_id, status, metadata_json,
                    started_at, ended_at, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    trace.workflow_name,
                    trace.group_id,
                    trace.status,
                    _to_json(trace.metadata),
                    serialize_datetime(trace.started_at),
                    serialize_datetime(trace.ended_at),
                    _to_json(trace.raw_payload or trace.to_dict()),
                ),
            )
            connection.execute("DELETE FROM spans WHERE trace_id = ?", (trace.trace_id,))
            connection.executemany(
                """
                INSERT INTO spans (
                    span_id, trace_id, parent_id, name, span_type, started_at, ended_at,
                    input_json, output_json, error_json, span_data_json,
                    input_tokens, output_tokens, estimated_cost
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_span_row(span) for span in trace.spans],
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO trace_summaries (
                    trace_id, workflow_name, group_id, status, started_at, ended_at, duration_ms,
                    source_format, source_kind, ingested_at,
                    span_count, input_tokens, output_tokens, estimated_cost,
                    approval_total_count, approval_pending_count, approval_approved_count, approval_rejected_count,
                    grounding_status, unsupported_claim_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _summary_row(build_trace_summary(trace)),
            )
            connection.commit()

    def upsert_trace(self, trace: Trace) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO traces (
                    trace_id, workflow_name, group_id, status, metadata_json,
                    started_at, ended_at, raw_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    trace.trace_id,
                    trace.workflow_name,
                    trace.group_id,
                    trace.status,
                    _to_json(trace.metadata),
                    serialize_datetime(trace.started_at),
                    serialize_datetime(trace.ended_at),
                    _to_json(trace.raw_payload or trace.to_dict()),
                ),
            )
            connection.commit()
        self._save_trace_summary(trace)

    def upsert_span(self, span: Span) -> Span:
        with closing(self._connect()) as connection:
            existing_trace = connection.execute(
                "SELECT trace_id FROM traces WHERE trace_id = ?",
                (span.trace_id,),
            ).fetchone()
            if existing_trace is None:
                raise ValueError(f"Trace not found: {span.trace_id}")
            connection.execute(
                """
                INSERT OR REPLACE INTO spans (
                    span_id, trace_id, parent_id, name, span_type, started_at, ended_at,
                    input_json, output_json, error_json, span_data_json,
                    input_tokens, output_tokens, estimated_cost
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _span_row(span),
            )
            connection.commit()
        trace = self.get_trace(span.trace_id)
        if trace is not None:
            self._save_trace_summary(trace)
        saved = self.get_span(span.trace_id, span.span_id)
        if saved is None:
            raise ValueError(f"Span not saved: {span.span_id}")
        return saved

    def update_trace_lifecycle(
        self,
        trace_id: str,
        *,
        status: str | None = None,
        ended_at: str | None = None,
    ) -> Trace | None:
        trace = self.get_trace(trace_id)
        if trace is None:
            return None
        next_status = status or trace.status
        next_ended_at = parse_datetime(ended_at) if ended_at is not None else trace.ended_at
        updated = Trace(
            trace_id=trace.trace_id,
            workflow_name=trace.workflow_name,
            group_id=trace.group_id,
            status=next_status,
            metadata=trace.metadata,
            raw_payload=trace.raw_payload,
            started_at=trace.started_at,
            ended_at=next_ended_at,
            spans=trace.spans,
        )
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE traces
                SET status = ?, ended_at = ?
                WHERE trace_id = ?
                """,
                (updated.status, serialize_datetime(updated.ended_at), trace_id),
            )
            connection.commit()
        self._save_trace_summary(updated)
        return updated

    def list_traces(self) -> list[Trace]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT trace_id, workflow_name, group_id, status, metadata_json, started_at, ended_at
                FROM traces
                ORDER BY COALESCE(started_at, created_at) DESC
                """
            ).fetchall()
        return [
            Trace(
                trace_id=row["trace_id"],
                workflow_name=row["workflow_name"],
                group_id=row["group_id"],
                status=row["status"],
                metadata=_from_json(row["metadata_json"]) or {},
                raw_payload=None,
                started_at=parse_datetime(row["started_at"]),
                ended_at=parse_datetime(row["ended_at"]),
                spans=[],
            )
            for row in rows
        ]

    def list_trace_summaries(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        workflow_name: str | None = None,
        approval_status: str | None = None,
        grounding_status: str | None = None,
        source_format: str | None = None,
        source_kind: str | None = None,
        started_after: str | None = None,
        started_before: str | None = None,
    ) -> dict[str, Any]:
        limit = min(max(limit, 1), 200)
        offset = max(offset, 0)
        where, params = _summary_filters(
            status=status,
            workflow_name=workflow_name,
            approval_status=approval_status,
            grounding_status=grounding_status,
            source_format=source_format,
            source_kind=source_kind,
            started_after=started_after,
            started_before=started_before,
        )
        with closing(self._connect()) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) AS total FROM trace_summaries {where}",
                params,
            ).fetchone()["total"]
            rows = connection.execute(
                f"""
                SELECT *
                FROM trace_summaries
                {where}
                ORDER BY COALESCE(started_at, '') DESC
                LIMIT ? OFFSET ?
                """,
                (*params, limit, offset),
            ).fetchall()
        return {
            "items": [_summary_from_row(row) for row in rows],
            "limit": limit,
            "offset": offset,
            "total": total,
        }

    def all_trace_summaries(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT * FROM trace_summaries").fetchall()
        return [_summary_from_row(row) for row in rows]

    def workflow_names(self) -> list[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT DISTINCT workflow_name
                FROM trace_summaries
                ORDER BY workflow_name
                """
            ).fetchall()
        return [row["workflow_name"] for row in rows]

    def get_trace(self, trace_id: str) -> Trace | None:
        with closing(self._connect()) as connection:
            trace_row = connection.execute(
                """
                SELECT trace_id, workflow_name, group_id, status, metadata_json, started_at, ended_at, raw_json
                FROM traces
                WHERE trace_id = ?
                """,
                (trace_id,),
            ).fetchone()
            if trace_row is None:
                return None
            span_rows = connection.execute(
                """
                SELECT span_id, trace_id, parent_id, name, span_type, started_at, ended_at,
                       input_json, output_json, error_json, span_data_json,
                       input_tokens, output_tokens, estimated_cost
                FROM spans
                WHERE trace_id = ?
                ORDER BY COALESCE(started_at, '')
                """,
                (trace_id,),
            ).fetchall()

        spans = [_span_from_row(row) for row in span_rows]
        spans.sort(key=lambda span: span.started_at or parse_datetime("0001-01-01T00:00:00Z"))
        return Trace(
            trace_id=trace_row["trace_id"],
            workflow_name=trace_row["workflow_name"],
            group_id=trace_row["group_id"],
            status=trace_row["status"],
            metadata=_from_json(trace_row["metadata_json"]) or {},
            raw_payload=_from_json(trace_row["raw_json"]),
            started_at=parse_datetime(trace_row["started_at"]),
            ended_at=parse_datetime(trace_row["ended_at"]),
            spans=spans,
        )

    def get_span(self, trace_id: str, span_id: str) -> Span | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT span_id, trace_id, parent_id, name, span_type, started_at, ended_at,
                       input_json, output_json, error_json, span_data_json,
                       input_tokens, output_tokens, estimated_cost
                FROM spans
                WHERE trace_id = ? AND span_id = ?
                """,
                (trace_id, span_id),
            ).fetchone()
        if row is None:
            return None
        return _span_from_row(row)

    def update_span_payload(
        self,
        trace_id: str,
        span_id: str,
        *,
        output: dict[str, Any] | None,
        span_data: dict[str, Any],
    ) -> Span | None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE spans
                SET output_json = ?, span_data_json = ?
                WHERE trace_id = ? AND span_id = ?
                """,
                (_to_json(output), _to_json(span_data), trace_id, span_id),
            )
            connection.commit()
        trace = self.get_trace(trace_id)
        if trace is not None:
            self._save_trace_summary(trace)
        return self.get_span(trace_id, span_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _save_trace_summary(self, trace: Trace) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO trace_summaries (
                    trace_id, workflow_name, group_id, status, started_at, ended_at, duration_ms,
                    source_format, source_kind, ingested_at,
                    span_count, input_tokens, output_tokens, estimated_cost,
                    approval_total_count, approval_pending_count, approval_approved_count, approval_rejected_count,
                    grounding_status, unsupported_claim_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _summary_row(build_trace_summary(trace)),
            )
            connection.commit()

    def _backfill_trace_summaries(self) -> None:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT t.trace_id
                FROM traces t
                LEFT JOIN trace_summaries s ON s.trace_id = t.trace_id
                WHERE s.trace_id IS NULL
                   OR s.source_format = 'unknown'
                   OR s.source_kind = 'unknown'
                   OR s.ingested_at IS NULL
                """
            ).fetchall()
        for row in rows:
            trace = self.get_trace(row["trace_id"])
            if trace is not None:
                self._save_trace_summary(trace)


def _span_row(span: Span) -> tuple[Any, ...]:
    return (
        span.span_id,
        span.trace_id,
        span.parent_id,
        span.name,
        span.span_type,
        serialize_datetime(span.started_at),
        serialize_datetime(span.ended_at),
        _to_json(span.input),
        _to_json(span.output),
        _to_json(span.error),
        _to_json(span.span_data),
        span.input_tokens,
        span.output_tokens,
        span.estimated_cost,
    )


def _span_from_row(row: sqlite3.Row) -> Span:
    return Span(
        span_id=row["span_id"],
        trace_id=row["trace_id"],
        parent_id=row["parent_id"],
        name=row["name"],
        span_type=row["span_type"],
        started_at=parse_datetime(row["started_at"]),
        ended_at=parse_datetime(row["ended_at"]),
        input=_from_json(row["input_json"]),
        output=_from_json(row["output_json"]),
        error=_from_json(row["error_json"]),
        span_data=_from_json(row["span_data_json"]) or {},
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        estimated_cost=row["estimated_cost"],
    )


def _to_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _from_json(value: str | None) -> Any:
    if value is None:
        return None
    return json.loads(value)


def _summary_row(summary: dict[str, Any]) -> tuple[Any, ...]:
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
        summary["span_count"],
        summary["input_tokens"],
        summary["output_tokens"],
        summary["estimated_cost"],
        summary["approval_total_count"],
        summary["approval_pending_count"],
        summary["approval_approved_count"],
        summary["approval_rejected_count"],
        summary["grounding_status"],
        summary["unsupported_claim_count"],
    )


def _summary_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "trace_id": row["trace_id"],
        "workflow_name": row["workflow_name"],
        "group_id": row["group_id"],
        "status": execution_status(row["status"]),
        "source_format": row["source_format"],
        "source_kind": row["source_kind"],
        "ingested_at": row["ingested_at"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "duration_ms": row["duration_ms"],
        "span_count": row["span_count"],
        "input_tokens": row["input_tokens"],
        "output_tokens": row["output_tokens"],
        "estimated_cost": row["estimated_cost"],
        "approval_total_count": row["approval_total_count"],
        "approval_pending_count": row["approval_pending_count"],
        "approval_approved_count": row["approval_approved_count"],
        "approval_rejected_count": row["approval_rejected_count"],
        "grounding_status": row["grounding_status"],
        "unsupported_claim_count": row["unsupported_claim_count"],
    }


def _summary_filters(
    *,
    status: str | None,
    workflow_name: str | None,
    approval_status: str | None,
    grounding_status: str | None,
    source_format: str | None,
    source_kind: str | None,
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
    if started_after:
        clauses.append("started_at >= ?")
        params.append(started_after)
    if started_before:
        clauses.append("started_at <= ?")
        params.append(started_before)
    if not clauses:
        return "", tuple(params)
    return "WHERE " + " AND ".join(clauses), tuple(params)


def _ensure_columns(connection: sqlite3.Connection, table_name: str, columns: dict[str, str]) -> None:
    existing = {row["name"] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}
    for column_name, column_type in columns.items():
        if column_name not in existing:
            connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
    connection.commit()
