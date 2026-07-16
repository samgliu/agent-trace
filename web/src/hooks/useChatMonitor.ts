import { useCallback, useEffect, useState } from "react";
import type { ChatInput, ChatStatus, TraceSummary } from "../types";
import { apiPostJson, fetchJson } from "../utils/apiClient";
import {
  latestTraceFromMessages,
  replacePendingChatMessage,
  summaryMap,
  traceSummaryQuery,
  uniqueTraceIds,
  upsertChatSession,
} from "../utils/appState";
import {
  createChatSession,
  createPendingUserMessage,
  getChatMessages,
  getChatSession,
  listChatSessions,
  markPendingMessageFailed,
  sendChatMessageAsync,
  type ChatMessage,
  type ChatSession,
} from "../utils/chat";

type UseChatMonitorOptions = {
  refreshKey: number;
  isCurrentChatOnly: boolean;
  onClearCurrentChatFilter: () => void;
  onRefresh: () => void;
  onSelectTrace: (traceId: string) => void;
};

export function useChatMonitor({
  refreshKey,
  isCurrentChatOnly,
  onClearCurrentChatFilter,
  onRefresh,
  onSelectTrace,
}: UseChatMonitorOptions) {
  const [session, setSession] = useState<ChatSession | null>(null);
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [traceSummaries, setTraceSummaries] = useState<Record<string, TraceSummary>>({});
  const [latestTraceId, setLatestTraceId] = useState<string | null>(null);
  const [status, setStatus] = useState<ChatStatus>({ status: "idle" });

  const loadSessions = useCallback(async () => {
    try {
      setSessions(await listChatSessions(fetchJson));
    } catch {
      setSessions([]);
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    let cancelled = false;
    async function loadTraceSummaries() {
      const traceIds = uniqueTraceIds(messages);
      if (traceIds.length === 0) {
        setTraceSummaries({});
        return;
      }
      const summaries = await fetchJson<TraceSummary[]>(`/trace-summaries${traceSummaryQuery(traceIds)}`);
      if (!cancelled) {
        setTraceSummaries(summaryMap(summaries));
      }
    }
    loadTraceSummaries().catch(() => {
      if (!cancelled) {
        setTraceSummaries({});
      }
    });
    return () => {
      cancelled = true;
    };
  }, [messages, refreshKey]);

  const refreshMessages = useCallback(
    async (sessionId: string) => {
      try {
        const nextMessages = await getChatMessages(fetchJson, sessionId);
        const nextLatestTraceId = latestTraceFromMessages(nextMessages);
        setMessages(nextMessages);
        setLatestTraceId(nextLatestTraceId);
        if (nextLatestTraceId) {
          onSelectTrace(nextLatestTraceId);
        }
      } catch {
        setStatus({ status: "error", message: "Could not refresh chat messages." });
      }
    },
    [onSelectTrace],
  );

  const refreshSession = useCallback(async (sessionId: string) => {
    const nextSession = await getChatSession(fetchJson, sessionId);
    setSession(nextSession);
    setMessages(nextSession.messages);
    setSessions((items) => upsertChatSession(items, nextSession));
  }, []);

  const openSession = useCallback(
    async (sessionId: string) => {
      if (!sessionId) {
        setSession(null);
        setMessages([]);
        setLatestTraceId(null);
        setStatus({ status: "idle" });
        if (isCurrentChatOnly) {
          onClearCurrentChatFilter();
        }
        return;
      }
      setStatus({ status: "idle" });
      const nextSession = await getChatSession(fetchJson, sessionId);
      setSession(nextSession);
      setMessages(nextSession.messages);
      setLatestTraceId(latestTraceFromMessages(nextSession.messages));
      onRefresh();
    },
    [isCurrentChatOnly, onClearCurrentChatFilter, onRefresh],
  );

  const startNewSession = useCallback(() => {
    setSession(null);
    setMessages([]);
    setLatestTraceId(null);
    setStatus({ status: "idle" });
    if (isCurrentChatOnly) {
      onClearCurrentChatFilter();
    }
  }, [isCurrentChatOnly, onClearCurrentChatFilter]);

  const submitTurn = useCallback(
    async (input: ChatInput) => {
      setStatus({ status: "submitting" });
      let pendingMessage: ChatMessage | null = null;
      try {
        const activeSession =
          session ??
          (await createChatSession(apiPostJson, {
            customerEmail: input.customerEmail,
            title: "Customer support",
          }));
        if (!session) {
          setSession(activeSession);
          setSessions((items) => upsertChatSession(items, activeSession));
        }
        pendingMessage = createPendingUserMessage({ sessionId: activeSession.session_id, content: input.message });
        setMessages((items) => [...items, pendingMessage!]);
        const result = await sendChatMessageAsync(apiPostJson, activeSession.session_id, {
          content: input.message,
          llmProvider: input.llmProvider,
        });
        setSession(result.session);
        setSessions((items) => upsertChatSession(items, result.session));
        setMessages((items) =>
          replacePendingChatMessage(items, pendingMessage!.message_id, result.user_message, result.assistant_message),
        );
        onRefresh();
        setStatus({ status: "idle" });
      } catch (submitError) {
        const message = submitError instanceof Error ? submitError.message : "Unknown chat error";
        if (pendingMessage) {
          setMessages((items) => markPendingMessageFailed(items, pendingMessage!.message_id, message));
        }
        setStatus({ status: "error", message });
      }
    },
    [onRefresh, session],
  );

  return {
    session,
    sessions,
    messages,
    traceSummaries,
    latestTraceId,
    status,
    loadSessions,
    refreshMessages,
    refreshSession,
    openSession,
    startNewSession,
    submitTurn,
  };
}
