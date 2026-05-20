import { useCallback, useEffect, useRef, useState } from "react";
import { ChatMonitor } from "./components/chat/ChatMonitor";
import { DashboardSummaryPanel } from "./components/dashboard/DashboardSummaryPanel";
import { EvalDashboardPanel } from "./components/evals/EvalDashboardPanel";
import { Shell } from "./components/layout/Shell";
import { LiveWorkflowPanel } from "./components/live/LiveWorkflowPanel";
import { EmptyRunsState, RunsSidebar } from "./components/runs/RunsSidebar";
import { AnalysisPanel } from "./components/trace/TraceAnalysisPanel";
import { ExecutiveSummaryPanel, MetricGrid, TraceHeader } from "./components/trace/TraceSummaryPanels";
import { AgentFlowPanel, TraceTimeline } from "./components/trace/TraceTimelinePanel";
import type { ApprovalAction } from "./types";
import { getApprovalStatus } from "./utils/approval";
import { postJson } from "./utils/apiClient";
import type { ServerEvent } from "./utils/appState";
import { useChatMonitor } from "./hooks/useChatMonitor";
import { useEvalRuns } from "./hooks/useEvalRuns";
import { useLiveWorkflowRun } from "./hooks/useLiveWorkflowRun";
import { useServerEvents } from "./hooks/useServerEvents";
import { useTraceData } from "./hooks/useTraceData";
import { stringMetadata } from "./utils/source";
import { executionStatus } from "./utils/status";
import { emptyFilters } from "./utils/traceFilters";

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
        <div className="layout">
          <RunsSidebar
            traces={state.traces}
            traceTotal={state.traceTotal}
            selectedTraceId={null}
            filters={filters}
            workflows={state.workflows}
            activeChatSessionId={chat.session?.session_id ?? null}
            latestChatTraceId={chat.latestTraceId}
            onFiltersChange={updateFilters}
            onSelectTrace={selectTrace}
            onClearSelection={() => setSelectedSpanId(null)}
            onPageChange={updatePage}
          />
          <main className="main">
            <DashboardSummaryPanel summary={state.dashboard} />
            <EvalDashboardPanel
              run={evals.run}
              history={evals.history}
              comparison={evals.comparison}
              status={evals.status}
              mode={evals.mode}
              onModeChange={evals.setMode}
              onRun={evals.runEvals}
              onResume={evals.resumeEvals}
              onSelectEvalRun={evals.loadRun}
              onSelectTrace={selectTrace}
            />
            <LiveWorkflowPanel
              run={liveWorkflow.run}
              error={liveWorkflow.error}
              onStart={liveWorkflow.start}
              onCancel={liveWorkflow.cancel}
              onRetry={liveWorkflow.retry}
            />
            <ChatMonitor
              session={chat.session}
              sessions={chat.sessions}
              messages={chat.messages}
              traceSummaries={chat.traceSummaries}
              status={chat.status}
              latestTraceId={chat.latestTraceId}
              onSelectSession={chat.openSession}
              onNewSession={chat.startNewSession}
              onSelectTrace={selectTrace}
              onSubmit={chat.submitTurn}
            />
            <EmptyRunsState onClearFilters={() => updateFilters(emptyFilters())} />
          </main>
        </div>
      </Shell>
    );
  }

  return (
    <Shell status="Connected">
      <div className="layout">
        <RunsSidebar
          traces={state.traces}
          traceTotal={state.traceTotal}
          selectedTraceId={state.selectedTrace.trace_id}
          filters={filters}
          workflows={state.workflows}
          activeChatSessionId={chat.session?.session_id ?? null}
          latestChatTraceId={chat.latestTraceId}
          onFiltersChange={updateFilters}
          onSelectTrace={selectTrace}
          onClearSelection={() => setSelectedSpanId(null)}
          onPageChange={updatePage}
        />

        <main className="main">
          <DashboardSummaryPanel summary={state.dashboard} />
          <EvalDashboardPanel
            run={evals.run}
            history={evals.history}
            comparison={evals.comparison}
            status={evals.status}
            mode={evals.mode}
            onModeChange={evals.setMode}
            onRun={evals.runEvals}
            onResume={evals.resumeEvals}
            onSelectEvalRun={evals.loadRun}
            onSelectTrace={selectTrace}
          />
          <LiveWorkflowPanel
            run={liveWorkflow.run}
            error={liveWorkflow.error}
            onStart={liveWorkflow.start}
            onCancel={liveWorkflow.cancel}
            onRetry={liveWorkflow.retry}
          />
          <ChatMonitor
            session={chat.session}
            sessions={chat.sessions}
            messages={chat.messages}
            traceSummaries={chat.traceSummaries}
            status={chat.status}
            latestTraceId={chat.latestTraceId}
            onSelectSession={chat.openSession}
            onNewSession={chat.startNewSession}
            onSelectTrace={selectTrace}
            onSubmit={chat.submitTurn}
          />
          <section className="traceRecord">
            <TraceHeader trace={state.selectedTrace} executionStatus={executionStatus(state.selectedTrace.status)} />
            <ExecutiveSummaryPanel trace={state.selectedTrace} metrics={state.metrics} grounding={state.grounding} />
            <MetricGrid metrics={state.metrics} grounding={state.grounding} />
            <AgentFlowPanel
              spans={state.selectedTrace.spans}
              selectedSpanId={selectedSpanId}
              onSelectSpan={setSelectedSpanId}
            />
            <section className="workspace">
              <TraceTimeline
                spans={state.selectedTrace.spans}
                selectedSpanId={selectedSpanId}
                onSelectSpan={setSelectedSpanId}
              />
              <AnalysisPanel
                metrics={state.metrics}
                grounding={state.grounding}
                spans={state.selectedTrace.spans}
                rawTrace={state.rawTrace}
                selectedSpanId={selectedSpanId}
                onSelectSpan={setSelectedSpanId}
                onApprovalAction={updateApproval}
              />
            </section>
          </section>
        </main>
      </div>
    </Shell>
  );
}
