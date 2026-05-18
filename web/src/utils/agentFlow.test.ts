import { describe, expect, it } from "vitest";
import { buildAgentFlow, type AgentFlowSpan } from "./agentFlow";

const baseSpan = {
  parent_id: null,
  duration_ms: 100,
  input_tokens: null,
  output_tokens: null,
  estimated_cost: null,
  span_data: {},
  error: null,
};

describe("buildAgentFlow", () => {
  it("groups multi-agent orchestration spans with operational badges", () => {
    const spans: AgentFlowSpan[] = [
      {
        ...baseSpan,
        span_id: "supervisor",
        name: "Supervisor Agent",
        span_type: "agent",
        span_data: { agent_role: "supervisor", decision_source: "llm", model: "gemini-primary" },
        input_tokens: 10,
        output_tokens: 4,
      },
      {
        ...baseSpan,
        span_id: "handoff",
        parent_id: "supervisor",
        name: "Supervisor -> Triage Agent",
        span_type: "handoff",
      },
      {
        ...baseSpan,
        span_id: "triage",
        name: "Triage Agent",
        span_type: "agent",
        span_data: { agent_role: "triage", model: "gemini-fallback", model_fallback_used: true },
      },
      {
        ...baseSpan,
        span_id: "lookup",
        parent_id: "triage",
        name: "lookup_customer",
        span_type: "function_tool",
      },
      {
        ...baseSpan,
        span_id: "validator",
        name: "Validator Agent",
        span_type: "guardrail",
        span_data: { agent_role: "validator" },
      },
      {
        ...baseSpan,
        span_id: "approval",
        parent_id: "validator",
        name: "Human Approval Gate",
        span_type: "approval",
        span_data: { approval_status: "blocked" },
      },
    ];

    expect(buildAgentFlow(spans)).toEqual([
      expect.objectContaining({
        role: "supervisor",
        label: "Supervisor",
        spanId: "supervisor",
        model: "gemini-primary",
        decisionSource: "llm",
        tokenTotal: 14,
        handoffCount: 1,
      }),
      expect.objectContaining({
        role: "triage",
        label: "Triage",
        model: "gemini-fallback",
        modelFallbackUsed: true,
        toolCount: 1,
      }),
      expect.objectContaining({
        role: "validator",
        label: "Validator",
        approvalPending: true,
      }),
    ]);
  });
});
