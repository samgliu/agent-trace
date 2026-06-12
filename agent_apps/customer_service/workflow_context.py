"""Trace context helpers for customer-service workflow runs."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from agenttrace.core.models import Span, Trace
from agent_apps.customer_service.trace_builder import SpanClock, span_id, trace


def support_triage_span_ids(trace_id: str) -> dict[str, str]:
    return {
        "supervisor": span_id(trace_id, "supervisor"),
        "handoff_triage": span_id(trace_id, "handoff_triage"),
        "handoff_response": span_id(trace_id, "handoff_response"),
        "triage": span_id(trace_id, "triage"),
        "working_memory_write": span_id(trace_id, "working_memory_write"),
        "handoff_investigation": span_id(trace_id, "handoff_investigation"),
        "investigation_agent": span_id(trace_id, "investigation_agent"),
        "lookup_customer": span_id(trace_id, "lookup_customer"),
        "lookup_charge": span_id(trace_id, "lookup_charge"),
        "lookup_order": span_id(trace_id, "lookup_order"),
        "verify_order_owner": span_id(trace_id, "verify_order_owner"),
        "verify_account_access": span_id(trace_id, "verify_account_access"),
        "lookup_subscription": span_id(trace_id, "lookup_subscription"),
        "handoff_policy": span_id(trace_id, "handoff_policy"),
        "policy_agent": span_id(trace_id, "policy_agent"),
        "retrieve_policy": span_id(trace_id, "retrieve_policy"),
        "customer_memory_read": span_id(trace_id, "customer_memory_read"),
        "action_agent": span_id(trace_id, "action_agent"),
        "agent_state_update": span_id(trace_id, "agent_state_update"),
        "create_action": span_id(trace_id, "create_action"),
        "validator": span_id(trace_id, "validator"),
        "handoff_escalation": span_id(trace_id, "handoff_escalation"),
        "escalation_agent": span_id(trace_id, "escalation_agent"),
        "approval_required": span_id(trace_id, "approval_required"),
        "customer_response": span_id(trace_id, "customer_response"),
    }


@dataclass
class WorkflowRunContext:
    trace_id: str
    conversation_history_count: int
    clock: SpanClock = field(default_factory=lambda: SpanClock(datetime.now(timezone.utc)))
    spans: list[Span] = field(default_factory=list)
    on_span: Callable[[Span], None] | None = None
    emitted_span_ids: set[str] = field(default_factory=set)

    @classmethod
    def create(
        cls,
        *,
        trace_id: str | None,
        conversation_history_count: int,
        on_span: Callable[[Span], None] | None,
    ) -> "WorkflowRunContext":
        return cls(
            trace_id=trace_id or f"trace_support_triage_{uuid.uuid4().hex[:12]}",
            conversation_history_count=conversation_history_count,
            on_span=on_span,
        )

    @property
    def span_ids(self) -> dict[str, str]:
        return support_triage_span_ids(self.trace_id)

    def emit(self, span: Span) -> Span:
        self.spans.append(span)
        if self.on_span is not None and span.span_id not in self.emitted_span_ids:
            self.emitted_span_ids.add(span.span_id)
            self.on_span(span)
        return span

    def finish(self, *, status: str, llm_provider: str, agent_decision_mode: str, supervisor_route: str) -> Trace:
        return trace(
            trace_id=self.trace_id,
            status=status,
            started_at=self.spans[0].started_at,
            ended_at=self.spans[-1].ended_at,
            spans=self.spans,
            llm_provider=llm_provider,
            agent_decision_mode=agent_decision_mode,
            supervisor_route=supervisor_route,
            conversation_history_count=self.conversation_history_count,
        )
