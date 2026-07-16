"""Trace source provenance helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agenttrace.core.models import Trace


def with_source_metadata(
    trace: Trace,
    *,
    source_format: str,
    source_kind: str,
) -> Trace:
    return Trace(
        trace_id=trace.trace_id,
        workflow_name=trace.workflow_name,
        group_id=trace.group_id,
        status=trace.status,
        metadata=enrich_source_metadata(
            trace.metadata,
            source_format=source_format,
            source_kind=source_kind,
        ),
        raw_payload=trace.raw_payload,
        started_at=trace.started_at,
        ended_at=trace.ended_at,
        spans=trace.spans,
    )


def enrich_source_metadata(
    metadata: dict[str, Any],
    *,
    source_format: str,
    source_kind: str,
) -> dict[str, Any]:
    enriched = dict(metadata)
    enriched["source_format"] = source_format
    enriched["source_kind"] = source_kind
    enriched.setdefault("ingested_at", datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"))
    return enriched
