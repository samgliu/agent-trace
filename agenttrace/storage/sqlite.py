"""SQLite storage for traces and spans."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

from agenttrace.core.summary import build_trace_summary
from agenttrace.core.models import Span, Trace, parse_datetime, serialize_datetime
from agenttrace.storage.sqlite_schema import initialize_schema
from agenttrace.storage.sqlite_helpers import (
    chat_message_from_row as _chat_message_from_row,
    chat_session_from_row as _chat_session_from_row,
    eval_case_result_row as _eval_case_result_row,
    eval_run_from_row as _eval_run_from_row,
    eval_run_row as _eval_run_row,
    eval_run_summary_from_row as _eval_run_summary_from_row,
    from_json as _from_json,
    span_from_row as _span_from_row,
    span_row as _span_row,
    summary_filters as _summary_filters,
    summary_from_row as _summary_from_row,
    summary_row as _summary_row,
    to_json as _to_json,
    utc_now as _utc_now,
    workflow_run_from_row as _workflow_run_from_row,
    workflow_run_row as _workflow_run_row,
)


class SQLiteTraceStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as connection:
            initialize_schema(connection)
        self._backfill_trace_summaries()

    def save_eval_run(self, result: dict[str, Any], *, run_id: str | None = None) -> dict[str, Any]:
        created_at = _utc_now()
        saved_run = {
            "run_id": run_id or f"eval_{uuid.uuid4().hex[:12]}",
            "suite_id": result["suite_id"],
            "name": result["name"],
            "execution_mode": result.get("execution_mode", "deterministic"),
            "model_provider": result.get("model_provider", "static"),
            "model_name": result.get("model_name", "deterministic"),
            "status": result.get("status") or ("passed" if result["failed"] == 0 else "failed"),
            "error": result.get("error"),
            "total": result["total"],
            "passed": result["passed"],
            "failed": result["failed"],
            "pass_rate": result["pass_rate"],
            "created_at": result.get("created_at") or created_at,
            "results": result["results"],
        }
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO eval_runs (
                    run_id, suite_id, name, execution_mode, model_provider, model_name,
                    status, error, total, passed, failed, pass_rate, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _eval_run_row(saved_run),
            )
            connection.execute("DELETE FROM eval_case_results WHERE run_id = ?", (saved_run["run_id"],))
            connection.executemany(
                """
                INSERT INTO eval_case_results (
                    run_id, case_id, name, trace_id, passed, score, checks_json, model_events_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [_eval_case_result_row(saved_run["run_id"], case_result) for case_result in saved_run["results"]],
            )
            connection.commit()
        saved = self.get_eval_run(saved_run["run_id"])
        if saved is None:
            raise ValueError(f"Eval run not saved: {saved_run['run_id']}")
        return saved

    def get_eval_run(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            run_row = connection.execute(
                """
                SELECT run_id, suite_id, name, execution_mode, model_provider, model_name,
                    status, error, total, passed, failed, pass_rate, created_at
                FROM eval_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if run_row is None:
                return None
            case_rows = connection.execute(
                """
                SELECT case_id, name, trace_id, passed, score, checks_json, model_events_json
                FROM eval_case_results
                WHERE run_id = ?
                ORDER BY rowid ASC
                """,
                (run_id,),
            ).fetchall()
        return _eval_run_from_row(run_row, case_rows)

    def list_eval_runs(self, *, limit: int = 10, offset: int = 0) -> dict[str, Any]:
        limit = min(max(limit, 1), 100)
        offset = max(offset, 0)
        with closing(self._connect()) as connection:
            total = connection.execute("SELECT COUNT(*) AS total FROM eval_runs").fetchone()["total"]
            rows = connection.execute(
                """
                SELECT run_id, suite_id, name, execution_mode, model_provider, model_name,
                    status, error, total, passed, failed, pass_rate, created_at
                FROM eval_runs
                ORDER BY created_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        return {
            "items": [_eval_run_summary_from_row(row) for row in rows],
            "limit": limit,
            "offset": offset,
            "total": total,
        }

    def get_latest_eval_run(self, *, suite_id: str, execution_mode: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT run_id
                FROM eval_runs
                WHERE suite_id = ? AND execution_mode = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (suite_id, execution_mode),
            ).fetchone()
        if row is None:
            return None
        return self.get_eval_run(row["run_id"])

    def create_workflow_run(
        self,
        *,
        run_id: str,
        workflow_name: str,
        trace_id: str | None,
        input_data: dict[str, Any],
    ) -> dict[str, Any]:
        now = _utc_now()
        run = {
            "run_id": run_id,
            "workflow_name": workflow_name,
            "status": "pending",
            "trace_id": trace_id,
            "error": None,
            "cancel_requested": False,
            "input": dict(input_data),
            "started_at": now,
            "updated_at": now,
            "completed_at": None,
        }
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO workflow_runs (
                    run_id, workflow_name, status, trace_id, error, cancel_requested,
                    input_json, started_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _workflow_run_row(run),
            )
            connection.commit()
        return run

    def get_workflow_run(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT run_id, workflow_name, status, trace_id, error, cancel_requested,
                       input_json, started_at, updated_at, completed_at
                FROM workflow_runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return _workflow_run_from_row(row)

    def list_active_workflow_runs(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT run_id, workflow_name, status, trace_id, error, cancel_requested,
                       input_json, started_at, updated_at, completed_at
                FROM workflow_runs
                WHERE status IN ('pending', 'running', 'cancel_requested')
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [_workflow_run_from_row(row) for row in rows]

    def update_workflow_run(self, run_id: str, **updates: Any) -> dict[str, Any] | None:
        existing = self.get_workflow_run(run_id)
        if existing is None:
            return None
        next_run = {**existing, **updates, "updated_at": _utc_now()}
        with closing(self._connect()) as connection:
            connection.execute(
                """
                UPDATE workflow_runs
                SET workflow_name = ?, status = ?, trace_id = ?, error = ?, cancel_requested = ?,
                    input_json = ?, started_at = ?, updated_at = ?, completed_at = ?
                WHERE run_id = ?
                """,
                (
                    next_run["workflow_name"],
                    next_run["status"],
                    next_run["trace_id"],
                    next_run["error"],
                    1 if next_run["cancel_requested"] else 0,
                    _to_json(next_run["input"]),
                    next_run["started_at"],
                    next_run["updated_at"],
                    next_run["completed_at"],
                    run_id,
                ),
            )
            connection.commit()
        return self.get_workflow_run(run_id)

    def create_chat_session(
        self,
        *,
        customer_email: str,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        now = _utc_now()
        session = {
            "session_id": session_id or f"chat_{uuid.uuid4().hex[:12]}",
            "customer_email": customer_email,
            "title": title,
            "metadata": metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO chat_sessions (
                    session_id, customer_email, title, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    session["customer_email"],
                    session["title"],
                    _to_json(session["metadata"]),
                    session["created_at"],
                    session["updated_at"],
                ),
            )
            connection.commit()
        return session

    def get_chat_session(self, session_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT session_id, customer_email, title, metadata_json, created_at, updated_at
                FROM chat_sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return _chat_session_from_row(row)

    def list_chat_sessions(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT session_id, customer_email, title, metadata_json, created_at, updated_at
                FROM chat_sessions
                ORDER BY updated_at DESC
                """
            ).fetchall()
        return [_chat_session_from_row(row) for row in rows]

    def add_chat_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        if self.get_chat_session(session_id) is None:
            raise ValueError(f"Chat session not found: {session_id}")
        now = _utc_now()
        message = {
            "message_id": message_id or f"msg_{uuid.uuid4().hex[:12]}",
            "session_id": session_id,
            "role": role,
            "content": content,
            "trace_id": trace_id,
            "metadata": metadata or {},
            "created_at": now,
        }
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO chat_messages (
                    message_id, session_id, role, content, trace_id, metadata_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message["message_id"],
                    message["session_id"],
                    message["role"],
                    message["content"],
                    message["trace_id"],
                    _to_json(message["metadata"]),
                    message["created_at"],
                ),
            )
            connection.execute(
                """
                UPDATE chat_sessions
                SET updated_at = ?
                WHERE session_id = ?
                """,
                (now, session_id),
            )
            connection.commit()
        return message

    def list_chat_messages(self, session_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT message_id, session_id, role, content, trace_id, metadata_json, created_at
                FROM chat_messages
                WHERE session_id = ?
                ORDER BY created_at ASC
                """,
                (session_id,),
            ).fetchall()
        return [_chat_message_from_row(row) for row in rows]

    def update_chat_message(
        self,
        message_id: str,
        *,
        content: str | None = None,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                """
                SELECT message_id, session_id, role, content, trace_id, metadata_json, created_at
                FROM chat_messages
                WHERE message_id = ?
                """,
                (message_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Chat message not found: {message_id}")
            current = _chat_message_from_row(row)
            next_content = current["content"] if content is None else content
            next_trace_id = current["trace_id"] if trace_id is None else trace_id
            next_metadata = current["metadata"] if metadata is None else metadata
            connection.execute(
                """
                UPDATE chat_messages
                SET content = ?, trace_id = ?, metadata_json = ?
                WHERE message_id = ?
                """,
                (next_content, next_trace_id, _to_json(next_metadata), message_id),
            )
            connection.execute(
                """
                UPDATE chat_sessions
                SET updated_at = ?
                WHERE session_id = ?
                """,
                (_utc_now(), current["session_id"]),
            )
            connection.commit()
        return {
            **current,
            "content": next_content,
            "trace_id": next_trace_id,
            "metadata": next_metadata,
        }

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
                    metadata_json,
                    span_count, input_tokens, output_tokens, estimated_cost, error_count,
                    approval_total_count, approval_pending_count, approval_approved_count, approval_rejected_count,
                    grounding_status, unsupported_claim_count,
                    memory_read_count, memory_write_count, memory_retrieved_count, memory_ignored_count,
                    memory_stale_count, memory_warning_count, memory_average_relevance,
                    escalation_count, escalation_human_review_count, escalation_risk_review_count,
                    escalation_technical_recovery_count, escalation_types_json, escalation_next_owners_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        chat_session_id: str | None = None,
        has_errors: bool | None = None,
        has_escalation: bool | None = None,
        escalation_type: str | None = None,
        escalation_owner: str | None = None,
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
            chat_session_id=chat_session_id,
            has_errors=has_errors,
            has_escalation=has_escalation,
            escalation_type=escalation_type,
            escalation_owner=escalation_owner,
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

    def trace_summaries_by_ids(self, trace_ids: list[str]) -> list[dict[str, Any]]:
        unique_trace_ids = list(dict.fromkeys(trace_id for trace_id in trace_ids if trace_id))
        if not unique_trace_ids:
            return []
        placeholders = ", ".join("?" for _ in unique_trace_ids)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT *
                FROM trace_summaries
                WHERE trace_id IN ({placeholders})
                ORDER BY COALESCE(started_at, '') DESC
                """,
                tuple(unique_trace_ids),
            ).fetchall()
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
                    metadata_json,
                    span_count, input_tokens, output_tokens, estimated_cost, error_count,
                    approval_total_count, approval_pending_count, approval_approved_count, approval_rejected_count,
                    grounding_status, unsupported_claim_count,
                    memory_read_count, memory_write_count, memory_retrieved_count, memory_ignored_count,
                    memory_stale_count, memory_warning_count, memory_average_relevance,
                    escalation_count, escalation_human_review_count, escalation_risk_review_count,
                    escalation_technical_recovery_count, escalation_types_json, escalation_next_owners_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                   OR s.error_count IS NULL
                   OR s.escalation_count IS NULL
                """
            ).fetchall()
        for row in rows:
            trace = self.get_trace(row["trace_id"])
            if trace is not None:
                self._save_trace_summary(trace)
