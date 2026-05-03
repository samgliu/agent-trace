"""SQLite storage for traces and spans."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

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
            connection.commit()

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
                    _to_json(trace.to_dict()),
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
            connection.commit()

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
                started_at=parse_datetime(row["started_at"]),
                ended_at=parse_datetime(row["ended_at"]),
                spans=[],
            )
            for row in rows
        ]

    def get_trace(self, trace_id: str) -> Trace | None:
        with closing(self._connect()) as connection:
            trace_row = connection.execute(
                """
                SELECT trace_id, workflow_name, group_id, status, metadata_json, started_at, ended_at
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
        return self.get_span(trace_id, span_id)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection


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
