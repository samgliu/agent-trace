"""Default-safe redaction helpers for trace payloads."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
PHONE_RE = re.compile(r"(?<!\d)(?:\+?1[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}(?!\d)")
PAYMENT_RE = re.compile(r"(?<!\d)\d(?:[ -]?\d){12,18}(?!\d)")
SAFE_IDENTIFIER_KEYS = {
    "case_id",
    "group_id",
    "id",
    "name",
    "parent_id",
    "parent_span_id",
    "resource_id",
    "run_id",
    "session_id",
    "span_id",
    "span_type",
    "status",
    "trace_id",
    "type",
    "workflow_name",
}


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    types: list[str]

    @property
    def contains_pii(self) -> bool:
        return bool(self.types)


def redact_value(value: Any) -> RedactionResult:
    redacted, pii_types = _redact(value)
    return RedactionResult(value=redacted, types=sorted(pii_types))


def redact_trace_dict(trace: dict[str, Any]) -> dict[str, Any]:
    trace_copy = dict(trace)
    spans = [redact_span_dict(span) for span in trace_copy.get("spans") or [] if isinstance(span, dict)]
    trace_copy["spans"] = spans

    metadata_result = redact_value(trace_copy.get("metadata") or {})
    raw_result = redact_value({key: value for key, value in trace_copy.items() if key not in {"metadata", "spans"}})
    pii_types = set(metadata_result.types) | set(raw_result.types)
    for span in spans:
        span_data = span.get("span_data") if isinstance(span, dict) else None
        if isinstance(span_data, dict):
            pii_types.update(str(item) for item in span_data.get("redaction_types") or [])

    metadata = dict(metadata_result.value)
    metadata.update(_privacy_metadata(pii_types))
    trace_copy.update(raw_result.value)
    trace_copy["metadata"] = metadata
    trace_copy["spans"] = spans
    return trace_copy


def redact_span_dict(span: dict[str, Any]) -> dict[str, Any]:
    span_copy = dict(span)
    pii_types: set[str] = set()
    for key in ("input", "output", "error"):
        result = redact_value(span_copy.get(key))
        span_copy[key] = result.value
        pii_types.update(result.types)

    span_data_result = redact_value(span_copy.get("span_data") or {})
    span_data = dict(span_data_result.value)
    pii_types.update(span_data_result.types)
    span_data.update(_privacy_metadata(pii_types))
    span_copy["span_data"] = span_data
    return span_copy


def redact_raw_payload(payload: dict[str, Any] | list[Any] | None) -> dict[str, Any] | list[Any] | None:
    result = redact_value(payload)
    return result.value


def _privacy_metadata(pii_types: set[str]) -> dict[str, Any]:
    return {
        "contains_pii": bool(pii_types),
        "redaction_applied": bool(pii_types),
        "redaction_types": sorted(pii_types),
    }


def _redact(value: Any) -> tuple[Any, set[str]]:
    if isinstance(value, str):
        return _redact_string(value)
    if isinstance(value, list):
        redacted_items = []
        pii_types: set[str] = set()
        for item in value:
            redacted_item, item_types = _redact(item)
            redacted_items.append(redacted_item)
            pii_types.update(item_types)
        return redacted_items, pii_types
    if isinstance(value, dict):
        redacted_dict: dict[str, Any] = {}
        pii_types: set[str] = set()
        for key, item in value.items():
            if key in SAFE_IDENTIFIER_KEYS:
                redacted_dict[key] = item
                continue
            redacted_item, item_types = _redact(item)
            redacted_dict[key] = redacted_item
            pii_types.update(item_types)
        return redacted_dict, pii_types
    return value, set()


def _redact_string(value: str) -> tuple[str, set[str]]:
    pii_types: set[str] = set()
    redacted = EMAIL_RE.sub(_mark("email", "[REDACTED_EMAIL]", pii_types), value)
    redacted = PAYMENT_RE.sub(_mark("payment", "[REDACTED_PAYMENT]", pii_types), redacted)
    redacted = PHONE_RE.sub(_mark("phone", "[REDACTED_PHONE]", pii_types), redacted)
    return redacted, pii_types


def _mark(pii_type: str, replacement: str, pii_types: set[str]):
    def replace(_match: re.Match[str]) -> str:
        pii_types.add(pii_type)
        return replacement

    return replace
