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

  const model = stringValue(span.span_data.model);
  if (model) {
    facts.push({ label: "Model", value: model });
  }

  const toolName = stringValue(span.span_data.tool_name);
  const toolServer = stringValue(span.span_data.tool_server);
  if (toolName || toolServer) {
    facts.push({ label: "Tool", value: [toolName, toolServer].filter(Boolean).join(" · ") });
  }

  return facts;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
