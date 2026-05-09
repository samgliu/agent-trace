import { formatCost, formatDuration, formatTokens } from "./format";

export type SpanFactInput = {
  duration_ms: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: number | null;
  span_data: Record<string, unknown>;
};

export type SpanFact = {
  label: string;
  value: string;
};

export function buildSpanFacts(span: SpanFactInput): SpanFact[] {
  const facts: SpanFact[] = [{ label: "Duration", value: formatDuration(span.duration_ms) }];

  if (span.input_tokens !== null || span.output_tokens !== null) {
    facts.push({ label: "Tokens", value: formatTokens(span.input_tokens ?? 0, span.output_tokens ?? 0) });
  }

  if (span.estimated_cost !== null) {
    facts.push({ label: "Cost", value: formatCost(span.estimated_cost) });
  }

  const decisionSource = stringValue(span.span_data.decision_source);
  if (decisionSource) {
    facts.push({ label: "Decision", value: formatDecisionSource(decisionSource) });
  }

  const promptVersion = stringValue(span.span_data.prompt_version);
  if (promptVersion) {
    facts.push({ label: "Prompt", value: promptVersion });
  }

  const fallbackReason = stringValue(span.span_data.fallback_reason);
  if (fallbackReason) {
    facts.push({ label: "Fallback", value: formatFallbackReason(fallbackReason) });
  }

  const provider = stringValue(span.span_data.model_provider);
  if (provider) {
    facts.push({ label: "Provider", value: provider });
  }

  const model = stringValue(span.span_data.model);
  if (model) {
    facts.push({ label: "Model", value: model });
  }

  const toolName = stringValue(span.span_data.tool_name);
  const toolServer = stringValue(span.span_data.tool_server);
  if (toolName || toolServer) {
    facts.push({ label: "Tool", value: [toolName, toolServer].filter(Boolean).join(" · ") });
  }

  const memoryStore = stringValue(span.span_data.memory_store);
  const memoryKey = stringValue(span.span_data.memory_key);
  if (memoryStore || memoryKey) {
    facts.push({ label: "Memory", value: [memoryStore, memoryKey].filter(Boolean).join(" · ") });
  }

  const relevance = numberValue(span.span_data.memory_relevance_score);
  if (relevance !== null) {
    facts.push({ label: "Relevance", value: relevance.toFixed(2) });
  }

  const memoryUsed = booleanValue(span.span_data.memory_used_in_response);
  if (memoryUsed !== null) {
    facts.push({ label: "Used in response", value: memoryUsed ? "yes" : "no" });
  }

  return facts;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === "boolean" ? value : null;
}

function formatDecisionSource(value: string): string {
  if (value === "llm") {
    return "LLM";
  }
  return value.replaceAll("_", " ");
}

function formatFallbackReason(value: string): string {
  return value.replaceAll("_", " ");
}
