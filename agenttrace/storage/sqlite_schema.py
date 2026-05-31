"""SQLite schema creation and lightweight migrations."""

from __future__ import annotations

import sqlite3

from agenttrace.storage.sqlite_helpers import ensure_columns


def initialize_schema(connection: sqlite3.Connection) -> None:
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
            metadata_json TEXT NOT NULL DEFAULT '{}',
            ingested_at TEXT,
            started_at TEXT,
            ended_at TEXT,
            duration_ms INTEGER,
            span_count INTEGER NOT NULL,
            input_tokens INTEGER NOT NULL,
            output_tokens INTEGER NOT NULL,
            estimated_cost REAL NOT NULL,
            error_count INTEGER NOT NULL DEFAULT 0,
            approval_total_count INTEGER NOT NULL,
            approval_pending_count INTEGER NOT NULL,
            approval_approved_count INTEGER NOT NULL,
            approval_rejected_count INTEGER NOT NULL,
            grounding_status TEXT NOT NULL,
            unsupported_claim_count INTEGER NOT NULL,
            memory_read_count INTEGER NOT NULL DEFAULT 0,
            memory_write_count INTEGER NOT NULL DEFAULT 0,
            memory_retrieved_count INTEGER NOT NULL DEFAULT 0,
            memory_ignored_count INTEGER NOT NULL DEFAULT 0,
            memory_stale_count INTEGER NOT NULL DEFAULT 0,
            memory_warning_count INTEGER NOT NULL DEFAULT 0,
            memory_average_relevance REAL,
            escalation_count INTEGER,
            escalation_human_review_count INTEGER,
            escalation_risk_review_count INTEGER,
            escalation_technical_recovery_count INTEGER,
            escalation_types_json TEXT,
            escalation_next_owners_json TEXT,
            FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY,
            customer_email TEXT NOT NULL,
            title TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_messages (
            message_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            trace_id TEXT,
            metadata_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES chat_sessions(session_id),
            FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS workflow_runs (
            run_id TEXT PRIMARY KEY,
            workflow_name TEXT NOT NULL,
            status TEXT NOT NULL,
            trace_id TEXT,
            error TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0,
            input_json TEXT NOT NULL,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_runs (
            run_id TEXT PRIMARY KEY,
            suite_id TEXT NOT NULL,
            name TEXT NOT NULL,
            execution_mode TEXT NOT NULL DEFAULT 'deterministic',
            model_provider TEXT NOT NULL DEFAULT 'static',
            model_name TEXT NOT NULL DEFAULT 'deterministic',
            status TEXT NOT NULL,
            error TEXT,
            total INTEGER NOT NULL,
            passed INTEGER NOT NULL,
            failed INTEGER NOT NULL,
            pass_rate REAL NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS eval_case_results (
            run_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            name TEXT NOT NULL,
            trace_id TEXT NOT NULL,
            passed INTEGER NOT NULL,
            score REAL NOT NULL,
            checks_json TEXT NOT NULL,
            model_events_json TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY(run_id, case_id),
            FOREIGN KEY(run_id) REFERENCES eval_runs(run_id),
            FOREIGN KEY(trace_id) REFERENCES traces(trace_id)
        )
        """
    )
    connection.commit()
    ensure_columns(
        connection,
        "trace_summaries",
        {
            "source_format": "TEXT NOT NULL DEFAULT 'unknown'",
            "source_kind": "TEXT NOT NULL DEFAULT 'unknown'",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "ingested_at": "TEXT",
            "error_count": "INTEGER NOT NULL DEFAULT 0",
            "memory_read_count": "INTEGER NOT NULL DEFAULT 0",
            "memory_write_count": "INTEGER NOT NULL DEFAULT 0",
            "memory_retrieved_count": "INTEGER NOT NULL DEFAULT 0",
            "memory_ignored_count": "INTEGER NOT NULL DEFAULT 0",
            "memory_stale_count": "INTEGER NOT NULL DEFAULT 0",
            "memory_warning_count": "INTEGER NOT NULL DEFAULT 0",
            "memory_average_relevance": "REAL",
            "escalation_count": "INTEGER",
            "escalation_human_review_count": "INTEGER",
            "escalation_risk_review_count": "INTEGER",
            "escalation_technical_recovery_count": "INTEGER",
            "escalation_types_json": "TEXT",
            "escalation_next_owners_json": "TEXT",
        },
    )
    ensure_columns(
        connection,
        "eval_runs",
        {
            "execution_mode": "TEXT NOT NULL DEFAULT 'deterministic'",
            "model_provider": "TEXT NOT NULL DEFAULT 'static'",
            "model_name": "TEXT NOT NULL DEFAULT 'deterministic'",
            "error": "TEXT",
        },
    )
    ensure_columns(
        connection,
        "eval_case_results",
        {
            "model_events_json": "TEXT NOT NULL DEFAULT '[]'",
        },
    )
