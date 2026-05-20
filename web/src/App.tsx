import { useCallback, useEffect, useRef, useState } from "react";
import { Shell } from "./components/layout/Shell";
import { DashboardPage } from "./pages/DashboardPage";
import type { ApprovalAction } from "./types";
import { postJson } from "./utils/apiClient";
import type { ServerEvent } from "./utils/appState";
import { useChatMonitor } from "./hooks/useChatMonitor";
import { useEvalRuns } from "./hooks/useEvalRuns";
import { useLiveWorkflowRun } from "./hooks/useLiveWorkflowRun";
import { useServerEvents } from "./hooks/useServerEvents";
import { useTraceData } from "./hooks/useTraceData";
import { stringMetadata } from "./utils/source";

export function App() {
  const [refreshKey, setRefreshKey] = useState(0);
  const refreshData = useCallback(() => setRefreshKey((value) => value + 1), []);
  const trace = useTraceData({ refreshKey });
  const {
    clearCurrentChatFilter,
    filters,
    selectTrace,
    selectTraceWithSpan,
    selectedSpanId,
    setActiveChatSessionId,
    setSelectedSpanId,
    state,
    updateFilters,
    updatePage,
  } = trace;
  const selectTraceFromChat = useCallback((traceId: string) => selectTraceWithSpan({ traceId, spanId: null }), [selectTraceWithSpan]);
  const chatSessionIdRef = useRef<string | null>(null);
  const liveWorkflowRunIdRef = useRef<string | null>(null);
  const chat = useChatMonitor({
    refreshKey,
    isCurrentChatOnly: filters.currentChatOnly,
    onClearCurrentChatFilter: clearCurrentChatFilter,
    onRefresh: refreshData,
    onSelectTrace: selectTraceFromChat,
  });
  chatSessionIdRef.current = chat.session?.session_id ?? null;
  const selectTraceFromWorkflow = useCallback(
    ({ traceId, spanId }: { traceId: string; spanId: string | null }) => selectTraceWithSpan({ traceId, spanId }),
    [selectTraceWithSpan],
  );
  const liveWorkflow = useLiveWorkflowRun({ onRefresh: refreshData, onSelectTrace: selectTraceFromWorkflow });
  const evals = useEvalRuns(refreshData);
  liveWorkflowRunIdRef.current = liveWorkflow.runId;

  useEffect(() => {
    const timer = window.setInterval(() => {
      refreshData();
    }, 60000);
    return () => window.clearInterval(timer);
  }, [refreshData]);

  useEffect(() => {
    setActiveChatSessionId(chat.session?.session_id ?? null);
  }, [chat.session?.session_id, setActiveChatSessionId]);

  const handleServerEvent = useCallback((event: ServerEvent | null) => {
    if (!event) return;
    if (event.type.startsWith("chat.") && event.session_id && event.session_id === chatSessionIdRef.current) {
      if (event.type === "chat.turn.completed" || event.type === "chat.turn.failed" || event.type === "chat.message.created") {
        chat.refreshMessages(event.session_id);
      }
    }
    if (event.type.startsWith("workflow_run.") && event.run_id && event.run_id === liveWorkflowRunIdRef.current) {
      liveWorkflow.refreshRun(event.run_id);
    }
    if (
      event.type === "trace.created" ||
      event.type === "trace.updated" ||
      event.type === "span.updated" ||
      event.type === "approval.updated" ||
      event.type === "dashboard.updated"
    ) {
      refreshData();
    }
    if (event.type.startsWith("eval_run.")) {
      if (event.run_id) {
        evals.loadRun(event.run_id);
      }
      evals.loadRuns();
      refreshData();
    }
  }, [chat, evals, liveWorkflow, refreshData]);

  useServerEvents(handleServerEvent);

  async function updateApproval(spanId: string, action: ApprovalAction) {
    if (state.status !== "ready") {
      return;
    }
    await postJson(`/traces/${state.selectedTrace.trace_id}/approvals/${spanId}/${action}`);
    const sessionId = stringMetadata(state.selectedTrace.metadata.chat_session_id);
    if (sessionId && chat.session?.session_id === sessionId) {
      await chat.refreshSession(sessionId);
    }
    refreshData();
  }

  if (state.status === "loading") {
    return <Shell status="Loading traces" />;
  }

  if (state.status === "error") {
    return <Shell status="API unavailable" error={state.message} />;
  }

  if (state.status === "empty") {
    return (
      <Shell status="Connected">
        <DashboardPage
          state={state}
          filters={filters}
          selectedSpanId={selectedSpanId}
          chat={chat}
          evals={evals}
          liveWorkflow={liveWorkflow}
          onApprovalAction={updateApproval}
          onFiltersChange={updateFilters}
          onPageChange={updatePage}
          onSelectSpan={setSelectedSpanId}
          onSelectTrace={selectTrace}
        />
      </Shell>
    );
  }

  return (
    <Shell status="Connected">
      <DashboardPage
        state={state}
        filters={filters}
        selectedSpanId={selectedSpanId}
        chat={chat}
        evals={evals}
        liveWorkflow={liveWorkflow}
        onApprovalAction={updateApproval}
        onFiltersChange={updateFilters}
        onPageChange={updatePage}
        onSelectSpan={setSelectedSpanId}
        onSelectTrace={selectTrace}
      />
    </Shell>
  );
}
