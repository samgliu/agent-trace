import type { ChatMessage, ChatSession } from "./chat";
import type { TraceSummary } from "../types";

export type ServerEvent = {
  type: string;
  resource_type?: string;
  resource_id?: string;
  session_id?: string;
  message_id?: string;
  trace_id?: string;
  run_id?: string;
};

export function traceSummaryQuery(traceIds: string[]): string {
  const params = new URLSearchParams();
  params.set("trace_ids", traceIds.join(","));
  return `?${params.toString()}`;
}

export function latestTraceFromMessages(messages: ChatMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const traceId = messages[index].trace_id;
    if (traceId) return traceId;
  }
  return null;
}

export function replacePendingChatMessage(
  messages: ChatMessage[],
  pendingMessageId: string,
  userMessage: ChatMessage,
  assistantMessage: ChatMessage,
): ChatMessage[] {
  return [...messages.filter((message) => message.message_id !== pendingMessageId), userMessage, assistantMessage];
}

export function uniqueTraceIds(messages: ChatMessage[]): string[] {
  return Array.from(new Set(messages.map((message) => message.trace_id).filter((traceId): traceId is string => Boolean(traceId))));
}

export function summaryMap(summaries: TraceSummary[]): Record<string, TraceSummary> {
  return Object.fromEntries(summaries.map((summary) => [summary.trace_id, summary]));
}

export function parseServerEvent(event: Event): ServerEvent | null {
  if (!("data" in event) || typeof event.data !== "string") return null;
  try {
    return JSON.parse(event.data) as ServerEvent;
  } catch {
    return null;
  }
}

export function upsertChatSession(sessions: ChatSession[], session: ChatSession): ChatSession[] {
  const next = sessions.filter((item) => item.session_id !== session.session_id);
  return [session, ...next];
}
