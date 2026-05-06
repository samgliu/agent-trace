export type ChatTraceMetadataInput = {
  trace_id: string;
  metadata?: Record<string, unknown>;
};

export type ChatTraceSummaryInput = {
  trace_id: string;
  approval_pending_count: number;
  error_count: number;
  status: string;
};

export function isChatTrace(trace: ChatTraceMetadataInput, sessionId: string | null): boolean {
  return Boolean(sessionId && trace.metadata?.chat_session_id === sessionId);
}

export function isLatestChatTrace(traceId: string, latestTraceId: string | null): boolean {
  return Boolean(latestTraceId && traceId === latestTraceId);
}

export function chatTurnBadges(
  _trace: ChatTraceSummaryInput,
  options: { isChatTurn: boolean; isLatest: boolean },
): string[] {
  const badges: string[] = [];
  if (options.isChatTurn) badges.push("Chat turn");
  if (options.isLatest) badges.push("Latest");
  return badges;
}
