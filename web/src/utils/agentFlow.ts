import { extractAgentContract } from "./agentContract";

export type AgentFlowSpan = {
  span_id: string;
  parent_id: string | null;
  name: string;
  span_type: string;
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: number | null;
  span_data: Record<string, unknown>;
  error: unknown;
};

export type AgentFlowStep = {
  role: string;
  label: string;
  spanId: string;
  spanType: string;
  model: string | null;
  modelFallbackUsed: boolean;
  decisionSource: string | null;
  route: string | null;
  durationMs: number | null;
  tokenTotal: number;
  estimatedCost: number | null;
  toolCount: number;
  handoffCount: number;
  approvalPending: boolean;
  errorCount: number;
  agentContractStatus: string | null;
};

export function buildAgentFlow(spans: AgentFlowSpan[]): AgentFlowStep[] {
  return spans
    .filter(isAgentFlowSpan)
    .map((span) => {
      const related = spans.filter((candidate) => candidate.parent_id === span.span_id);
      const toolCount = related.filter((candidate) =>
        ["function_tool", "rag_retrieval", "memory_read", "memory_write"].includes(candidate.span_type),
      ).length;
      const handoffCount = related.filter((candidate) => candidate.span_type === "handoff").length;
      const approvalPending = related.some(
        (candidate) => candidate.span_type === "approval" && candidate.span_data.approval_status === "blocked",
      );
      const errorCount = Number(Boolean(span.error)) + related.filter((candidate) => Boolean(candidate.error)).length;
      return {
        role: agentRole(span),
        label: agentLabel(span),
        spanId: span.span_id,
        spanType: span.span_type,
        model: stringValue(span.span_data.model),
        modelFallbackUsed: span.span_data.model_fallback_used === true,
        decisionSource: stringValue(span.span_data.decision_source),
        route: stringValue(span.span_data.supervisor_route),
        durationMs: span.duration_ms,
        tokenTotal: (span.input_tokens ?? 0) + (span.output_tokens ?? 0),
        estimatedCost: span.estimated_cost,
        toolCount,
        handoffCount,
        approvalPending,
        errorCount,
        agentContractStatus: extractAgentContract(span.span_data)?.status ?? null,
      };
    });
}

function isAgentFlowSpan(span: AgentFlowSpan): boolean {
  return (
    span.span_type === "agent" ||
    span.span_type === "guardrail" ||
    span.span_type === "generation" ||
    typeof span.span_data.agent_role === "string"
  );
}

function agentRole(span: AgentFlowSpan): string {
  const role = stringValue(span.span_data.agent_role);
  if (role) return role;
  if (span.span_type === "generation") return "response";
  if (span.span_type === "guardrail") return "validator";
  return span.name.toLowerCase().replace(/\s+/g, "_");
}

function agentLabel(span: AgentFlowSpan): string {
  const role = agentRole(span);
  const labels: Record<string, string> = {
    supervisor: "Supervisor",
    triage: "Triage",
    policy: "Policy",
    action: "Action",
    validator: "Validator",
    response: "Customer Response",
  };
  return labels[role] ?? span.name.replace(/\s+Agent$/, "");
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
