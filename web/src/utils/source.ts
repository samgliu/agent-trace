export function stringMetadata(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

export function privacyLabel(metadata: Record<string, unknown>): string | null {
  if (metadata.redaction_applied === true) return "Redacted";
  if (metadata.contains_pii === true) return "Sensitive";
  return null;
}

export function sourceLabel(sourceFormat: string): string {
  if (sourceFormat === "openai-agents") return "OpenAI Agents";
  if (sourceFormat === "agenttrace") return "AgentTrace";
  return sourceFormat;
}

export function sourceKindLabel(sourceKind: string): string {
  if (sourceKind === "trace_export") return "trace export";
  if (sourceKind === "event_stream") return "event stream";
  if (sourceKind === "live_api") return "live API";
  return sourceKind;
}
