"""Eval report and improvement-plan helpers."""

from __future__ import annotations

from typing import Any

from agenttrace.evals.models import EvalSuiteResult


def build_eval_report(result: EvalSuiteResult) -> dict[str, Any]:
    failed_cases = []
    category_counts: dict[str, int] = {}
    for case_result in result.results:
        failed_checks = [check for check in case_result.checks if not check.passed]
        if not failed_checks:
            continue
        failed_cases.append(
            {
                "case_id": case_result.case.case_id,
                "name": case_result.case.name,
                "trace_id": case_result.trace.trace_id,
                "score": case_result.score,
                "failed_checks": [check.to_dict() for check in failed_checks],
            }
        )
        for check in failed_checks:
            category = eval_check_category(check.name)
            category_counts[category] = category_counts.get(category, 0) + 1
    return {
        "suite_id": result.suite_id,
        "name": result.name,
        "execution_mode": result.execution_mode,
        "model_provider": result.model_provider,
        "model_name": result.model_name,
        "status": "passed" if result.failed == 0 else "failed",
        "total": result.total,
        "passed": result.passed,
        "failed": result.failed,
        "pass_rate": result.pass_rate,
        "failed_cases": failed_cases,
        "failed_check_categories": category_counts,
        "improvement_plan": build_improvement_plan(failed_cases, category_counts),
    }


def build_improvement_plan(failed_cases: list[dict[str, Any]], category_counts: dict[str, int]) -> list[dict[str, Any]]:
    if not failed_cases:
        return []
    cases_by_category: dict[str, list[dict[str, Any]]] = {}
    for case in failed_cases:
        for check in case["failed_checks"]:
            category = eval_check_category(check["name"])
            cases_by_category.setdefault(category, []).append(
                {
                    "case_id": case["case_id"],
                    "trace_id": case["trace_id"],
                    "check": check["name"],
                    "expected": check["expected"],
                    "actual": check["actual"],
                }
            )

    return [
        {
            "category": category,
            "failed_check_count": category_counts[category],
            "owner_area": _improvement_owner_area(category),
            "recommended_action": _improvement_recommended_action(category),
            "suggested_files": _improvement_suggested_files(category),
            "cases": cases_by_category.get(category, []),
        }
        for category in sorted(category_counts, key=lambda item: (-category_counts[item], item))
    ]


def format_eval_report(report: dict[str, Any]) -> str:
    lines = [
        f"Eval suite: {report['name']} ({report['suite_id']})",
        f"Mode: {report['execution_mode']} ({report['model_provider']}/{report['model_name']})",
        f"Status: {report['status']}",
        f"Cases: {report['passed']}/{report['total']} passed",
        f"Pass rate: {report['pass_rate']:.1%}",
    ]
    failed_cases = report.get("failed_cases", [])
    if not failed_cases:
        lines.append("Failed cases: none")
        return "\n".join(lines)

    lines.append("Failed cases:")
    for case in failed_cases:
        lines.append(f"- {case['case_id']} ({case['score']:.1%}) trace={case['trace_id']}")
        for check in case["failed_checks"]:
            lines.append(f"  - {check['name']}: expected {check['expected']}, got {check['actual']}")
    categories = report.get("failed_check_categories") or {}
    if categories:
        lines.append("Failed check categories:")
        for category, count in sorted(categories.items()):
            lines.append(f"- {category}: {count}")
    improvement_plan = report.get("improvement_plan") or []
    if improvement_plan:
        lines.append("Improvement workflow:")
        lines.append("1. Open each listed trace and inspect Agent Flow, failed spans, model output, and evidence.")
        lines.append("2. Patch the smallest prompt, policy, domain, or guardrail surface that explains the failure.")
        lines.append("3. Add or update a focused eval/test for the case before rerunning deterministic and LLM evals.")
        for item in improvement_plan:
            files = ", ".join(item["suggested_files"])
            lines.append(f"- {item['category']} ({item['failed_check_count']}): {item['recommended_action']}")
            lines.append(f"  owner={item['owner_area']} files={files}")
    return "\n".join(lines)


def eval_check_category(name: str) -> str:
    if name in {"trace_status", "error_count"}:
        return "Reliability"
    if name in {"supervisor_route", "issue_type", "policy_id", "action_type"}:
        return "Routing"
    if name.startswith("tool_used") or name.startswith("evidence_id") or name.startswith("agent_state"):
        return "Evidence"
    if name.startswith("escalation_"):
        return "Escalation"
    if name == "approval_required" or name == "approval_reason":
        return "Governance"
    if name == "grounding_status" or name.startswith("response_"):
        return "Response"
    if name.startswith("memory_"):
        return "Memory"
    return "Other"


def _improvement_owner_area(category: str) -> str:
    return {
        "Routing": "multi-agent routing and policy/action planning",
        "Evidence": "tool usage, memory state, and evidence propagation",
        "Escalation": "human handoff routing and escalation ownership",
        "Governance": "approval policy and validator guardrails",
        "Response": "customer-facing response generation and grounding",
        "Memory": "short-term continuity and long-term customer memory",
        "Reliability": "tool failure handling and workflow recovery",
    }.get(category, "support-triage workflow")


def _improvement_recommended_action(category: str) -> str:
    return {
        "Routing": "tighten supervisor routing, triage, policy retrieval, or action prompts so the selected workflow path and outcome match the request.",
        "Evidence": "verify required tool calls and carry evidence ids into agent state, validation, and final action output.",
        "Escalation": "verify the escalation agent is emitted with the right escalation type, next owner, and handoff reason.",
        "Governance": "align validator approval decisions and approval reasons with policy requirements.",
        "Response": "adjust response instructions so the answer contains required facts and avoids prohibited claims.",
        "Memory": "preserve active issue state across turns and avoid topic drift unless the customer clearly switches topic.",
        "Reliability": "make failure paths explicit and ensure tool errors become recovered or failed traces as expected.",
    }.get(category, "inspect the failed trace and add the smallest targeted regression check.")


def _improvement_suggested_files(category: str) -> list[str]:
    common = ["agent_apps/customer_service/runner.py", "agenttrace/evals/support_triage.py"]
    extra = {
        "Routing": ["agent_apps/customer_service/routing.py", "agent_apps/customer_service/domain.py"],
        "Evidence": ["agent_apps/customer_service/domain.py"],
        "Escalation": ["agent_apps/customer_service/domain.py", "agent_apps/customer_service/policy_logic.py"],
        "Governance": ["agent_apps/customer_service/domain.py"],
        "Response": [],
        "Memory": ["agent_apps/customer_service/domain.py"],
        "Reliability": ["agent_apps/customer_service/domain.py", "agenttrace/mcp_tools/tools.py"],
    }.get(category, [])
    return [*common, *extra]
