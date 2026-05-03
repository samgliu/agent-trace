"""Grounding analysis helpers."""

from __future__ import annotations

from typing import Any

from agenttrace.core.models import Span, Trace


def build_grounding_summary(trace: Trace) -> dict[str, Any]:
    grounding_spans = [
        span
        for span in trace.spans
        if span.span_type in {"guardrail", "validation"} and isinstance(span.output, dict)
    ]
    unsupported_claims = []
    supported_claims = []
    grounded_values = []

    for span in grounding_spans:
        output = span.output if isinstance(span.output, dict) else {}
        if "grounded" in output:
            grounded_values.append(bool(output["grounded"]))
        for claim in _claims_from_output(output.get("unsupported_claims")):
            unsupported_claims.append({**claim, "span_id": span.span_id, "span_name": span.name})
        for claim in _claims_from_output(output.get("supported_claims")):
            supported_claims.append({**claim, "span_id": span.span_id, "span_name": span.name})

    has_ungrounded_step = any(value is False for value in grounded_values)
    final_grounded = _final_grounded_value(grounded_values)

    return {
        "trace_id": trace.trace_id,
        "status": _grounding_status(trace.status, final_grounded, has_ungrounded_step, unsupported_claims),
        "final_grounded": final_grounded,
        "recovered": has_ungrounded_step and final_grounded is True,
        "unsupported_claim_count": len(unsupported_claims),
        "supported_claim_count": len(supported_claims),
        "validation_span_count": len(grounding_spans),
        "unsupported_claims": unsupported_claims,
        "supported_claims": supported_claims,
    }


def _grounding_status(
    trace_status: str,
    final_grounded: bool | None,
    has_ungrounded_step: bool,
    unsupported_claims: list[dict[str, Any]],
) -> str:
    if final_grounded is True and has_ungrounded_step:
        return "recovered"
    if final_grounded is False or unsupported_claims:
        return "failed"
    if final_grounded is True:
        return "grounded"
    return trace_status


def _final_grounded_value(values: list[bool]) -> bool | None:
    if not values:
        return None
    return values[-1]


def _claims_from_output(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    claims: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, str):
            claims.append({"claim": item})
        elif isinstance(item, dict) and "claim" in item:
            claims.append({key: item[key] for key in item})
    return claims
