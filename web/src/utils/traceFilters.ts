import type { TraceFilters } from "../types";

export function filterQuery(filters: TraceFilters, activeChatSessionId: string | null): string {
  const params = new URLSearchParams();
  if (filters.status) params.set("status", filters.status);
  if (filters.workflowName) params.set("workflow_name", filters.workflowName);
  if (filters.sourceFormat) params.set("source_format", filters.sourceFormat);
  if (filters.sourceKind) params.set("source_kind", filters.sourceKind);
  if (filters.errorStatus) params.set("has_errors", filters.errorStatus);
  if (filters.approvalStatus) params.set("approval_status", filters.approvalStatus);
  if (filters.groundingStatus) params.set("grounding_status", filters.groundingStatus);
  if (filters.currentChatOnly && activeChatSessionId) params.set("chat_session_id", activeChatSessionId);
  const startedAfter = startedAfterForRange(filters.timeRange);
  if (startedAfter) params.set("started_after", startedAfter);
  params.set("limit", "25");
  params.set("offset", String(filters.offset));
  const query = params.toString();
  return query ? `?${query}` : "";
}

export function emptyFilters(): TraceFilters {
  return {
    status: "",
    workflowName: "",
    sourceFormat: "",
    sourceKind: "",
    errorStatus: "",
    approvalStatus: "",
    groundingStatus: "",
    timeRange: "",
    currentChatOnly: false,
    offset: 0,
  };
}

export function activeFilterCount(filters: TraceFilters): number {
  return [
    filters.status,
    filters.workflowName,
    filters.sourceFormat,
    filters.sourceKind,
    filters.errorStatus,
    filters.approvalStatus,
    filters.groundingStatus,
    filters.timeRange,
    filters.currentChatOnly ? "currentChatOnly" : "",
  ].filter(Boolean).length;
}

export function startedAfterForRange(value: string): string | null {
  const minutesByRange: Record<string, number> = {
    "15m": 15,
    "1h": 60,
    "24h": 1440,
  };
  const minutes = minutesByRange[value];
  if (!minutes) return null;
  return new Date(Date.now() - minutes * 60 * 1000).toISOString();
}
