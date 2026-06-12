"""Shared eval result models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from agenttrace.core.models import Trace

EvalExecutionMode = Literal["deterministic", "llm"]


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    name: str
    message: str
    customer_email: str
    expected_trace_status: str
    conversation_history: tuple[dict[str, Any], ...] = ()
    expected_supervisor_route: str | None = None
    expected_issue_type: str | None = None
    expected_policy_id: str | None = None
    expected_action_type: str | None = None
    expected_approval_required: bool | None = None
    expected_grounding_status: str | None = None
    expected_memory_warning_count: int | None = None
    expected_error_count: int | None = None
    expected_tool_names: tuple[str, ...] = ()
    expected_investigation_evidence: tuple[str, ...] = ()
    expected_evidence_ids: tuple[str, ...] = ()
    expected_next_required_step: str | None = None
    expected_missing_fields: tuple[str, ...] = ()
    expected_risk_signals: tuple[str, ...] = ()
    expected_escalation_type: str | None = None
    expected_escalation_owner: str | None = None
    expected_escalation_reason_contains: str | None = None
    expected_approval_reason_contains: str | None = None
    expected_response_contains: tuple[str, ...] = ()
    expected_response_excludes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "name": self.name,
            "message": self.message,
            "customer_email": self.customer_email,
            "turn_count": len(self.conversation_history) + 1,
        }


@dataclass(frozen=True)
class EvalCheck:
    name: str
    expected: Any
    actual: Any
    passed: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "expected": self.expected,
            "actual": self.actual,
            "passed": self.passed,
        }


@dataclass(frozen=True)
class EvalCaseResult:
    case: EvalCase
    trace: Trace
    checks: list[EvalCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    @property
    def score(self) -> float:
        if not self.checks:
            return 0.0
        passed_count = sum(1 for check in self.checks if check.passed)
        return round(passed_count / len(self.checks), 4)

    def to_dict(self) -> dict[str, Any]:
        from agenttrace.evals.trace_assertions import model_events

        return {
            "case_id": self.case.case_id,
            "name": self.case.name,
            "trace_id": self.trace.trace_id,
            "passed": self.passed,
            "score": self.score,
            "checks": [check.to_dict() for check in self.checks],
            "model_events": model_events(self.trace),
        }


@dataclass(frozen=True)
class EvalSuiteResult:
    suite_id: str
    name: str
    results: list[EvalCaseResult]
    execution_mode: EvalExecutionMode = "deterministic"
    model_provider: str = "static"
    model_name: str = "deterministic"

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def failed(self) -> int:
        return self.total - self.passed

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.passed / self.total, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite_id": self.suite_id,
            "name": self.name,
            "execution_mode": self.execution_mode,
            "model_provider": self.model_provider,
            "model_name": self.model_name,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "pass_rate": self.pass_rate,
            "results": [result.to_dict() for result in self.results],
        }
