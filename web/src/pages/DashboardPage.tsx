import { ChatMonitor } from "../components/chat/ChatMonitor";
import { DashboardSummaryPanel } from "../components/dashboard/DashboardSummaryPanel";
import { EvalDashboardPanel } from "../components/evals/EvalDashboardPanel";
import { LiveWorkflowPanel } from "../components/live/LiveWorkflowPanel";
import { EmptyRunsState, RunsSidebar } from "../components/runs/RunsSidebar";
import { AnalysisPanel } from "../components/trace/TraceAnalysisPanel";
import { ExecutiveSummaryPanel, MetricGrid, TraceHeader } from "../components/trace/TraceSummaryPanels";
import { AgentFlowPanel, TraceTimeline } from "../components/trace/TraceTimelinePanel";
import type { ApprovalAction, LoadState, TraceFilters } from "../types";
import { executionStatus } from "../utils/status";
import { emptyFilters } from "../utils/traceFilters";
import type { AuthRole } from "../utils/authz";
import type { useChatMonitor } from "../hooks/useChatMonitor";
import type { useEvalRuns } from "../hooks/useEvalRuns";
import type { useLiveWorkflowRun } from "../hooks/useLiveWorkflowRun";

type DashboardState = Extract<LoadState, { status: "empty" | "ready" }>;

type DashboardPageProps = {
  state: DashboardState;
  authRole: AuthRole | null;
  filters: TraceFilters;
  selectedSpanId: string | null;
  chat: ReturnType<typeof useChatMonitor>;
  evals: ReturnType<typeof useEvalRuns>;
  liveWorkflow: ReturnType<typeof useLiveWorkflowRun>;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
  onFiltersChange: (filters: TraceFilters) => void;
  onPageChange: (offset: number) => void;
  onSelectSpan: (spanId: string | null) => void;
  onSelectTrace: (traceId: string) => void;
};

export function DashboardPage({
  state,
  authRole,
  filters,
  selectedSpanId,
  chat,
  evals,
  liveWorkflow,
  onApprovalAction,
  onFiltersChange,
  onPageChange,
  onSelectSpan,
  onSelectTrace,
}: DashboardPageProps) {
  const ready = state.status === "ready";

  return (
    <div className="layout">
      <RunsSidebar
        traces={state.traces}
        traceTotal={state.traceTotal}
        selectedTraceId={ready ? state.selectedTrace.trace_id : null}
        filters={filters}
        workflows={state.workflows}
        activeChatSessionId={chat.session?.session_id ?? null}
        latestChatTraceId={chat.latestTraceId}
        onFiltersChange={onFiltersChange}
        onSelectTrace={onSelectTrace}
        onClearSelection={() => onSelectSpan(null)}
        onPageChange={onPageChange}
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
          onSelectTrace={onSelectTrace}
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
          onSelectTrace={onSelectTrace}
          onSubmit={chat.submitTurn}
        />
        {ready ? (
          <TraceRecord
            state={state}
            authRole={authRole}
            selectedSpanId={selectedSpanId}
            onApprovalAction={onApprovalAction}
            onSelectSpan={onSelectSpan}
          />
        ) : (
          <EmptyRunsState onClearFilters={() => onFiltersChange(emptyFilters())} />
        )}
      </main>
    </div>
  );
}

function TraceRecord({
  state,
  authRole,
  selectedSpanId,
  onApprovalAction,
  onSelectSpan,
}: {
  state: Extract<LoadState, { status: "ready" }>;
  authRole: AuthRole | null;
  selectedSpanId: string | null;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
  onSelectSpan: (spanId: string) => void;
}) {
  return (
    <section className="traceRecord">
      <TraceHeader trace={state.selectedTrace} executionStatus={executionStatus(state.selectedTrace.status)} />
      <ExecutiveSummaryPanel trace={state.selectedTrace} metrics={state.metrics} grounding={state.grounding} />
      <MetricGrid metrics={state.metrics} grounding={state.grounding} />
      <AgentFlowPanel spans={state.selectedTrace.spans} selectedSpanId={selectedSpanId} onSelectSpan={onSelectSpan} />
      <section className="workspace">
        <TraceTimeline spans={state.selectedTrace.spans} selectedSpanId={selectedSpanId} onSelectSpan={onSelectSpan} />
        <AnalysisPanel
          metrics={state.metrics}
          grounding={state.grounding}
          spans={state.selectedTrace.spans}
          rawTrace={state.rawTrace}
          authRole={authRole}
          selectedSpanId={selectedSpanId}
          onSelectSpan={onSelectSpan}
          onApprovalAction={onApprovalAction}
        />
      </section>
    </section>
  );
}
