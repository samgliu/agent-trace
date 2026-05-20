import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Bot,
  Braces,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  FlaskConical,
  GitBranch,
  MessageSquare,
  Network,
  RotateCcw,
  Send,
  ShieldCheck,
  UserCheck,
  Wrench
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type MouseHandlerDataParam,
} from "recharts";
import "./styles.css";
import { getApprovalStatus, type ApprovalStatus } from "./utils/approval";
import { buildAgentFlow, type AgentFlowStep } from "./utils/agentFlow";
import {
  createPendingUserMessage,
  createChatSession,
  getChatMessages,
  getChatSession,
  listChatSessions,
  markPendingMessageFailed,
  sendChatMessageAsync,
  type ChatMessage,
  type ChatSession,
  type LLMProvider,
} from "./utils/chat";
import { buildChatMessageChips } from "./utils/chatMessageChips";
import { chatTurnBadges, isChatTrace, isLatestChatTrace } from "./utils/chatTrace";
import { extractUnsupportedClaims } from "./utils/claims";
import {
  buildEvalImprovementPlan,
  buildEvalTrendSeries,
  evalCategorySummaries,
  evalCheckCategory,
  evalComparisonStatusLabel,
  evalModeLabel,
  evalModelSummary,
  evalPassRateLabel,
  evalProgress,
  evalRunHasProviderIssue,
  evalRunIsActive,
  evalStatusLabel,
  failedEvalCases,
  failedEvalChecks,
  formatEvalValue,
  getEvalRun,
  getSupportTriageEvalComparison,
  listEvalRuns,
  resumeEvalRun,
  runSupportTriageEvalSuite,
  startSupportTriageEvalSuite,
  type EvalComparison,
  type EvalExecutionMode,
  type EvalRunSummary,
  type EvalSuiteRun,
  type EvalTrendPoint,
} from "./utils/evals";
import { formatCost, formatDuration, formatTokens } from "./utils/format";
import { buildMemorySummary, type MemorySummary } from "./utils/memoryAnalysis";
import { clampedOffset, hasNextPage, nextOffset, pageRange, previousOffset, TRACE_PAGE_SIZE } from "./utils/pagination";
import { buildSpanFacts } from "./utils/spanFacts";
import { sourceKindLabel, sourceLabel, stringMetadata } from "./utils/source";
import { buildExecutiveSummary, countApprovals } from "./utils/summary";
import {
  cancelWorkflowRun,
  getWorkflowRun,
  isWorkflowRunActive,
  retryWorkflowRun,
  startSupportTriageLiveRun,
  type WorkflowRun,
} from "./utils/workflowRuns";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type TraceSummary = {
  trace_id: string;
  workflow_name: string;
  group_id: string | null;
  status: string;
  source_format: string;
  source_kind: string;
  ingested_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  span_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  error_count: number;
  approval_total_count: number;
  approval_pending_count: number;
  approval_approved_count: number;
  approval_rejected_count: number;
  grounding_status: string;
  unsupported_claim_count: number;
  metadata?: Record<string, unknown>;
};

type TraceListResponse = {
  items: TraceSummary[];
  limit: number;
  offset: number;
  total: number;
};

type Span = {
  span_id: string;
  parent_id: string | null;
  name: string;
  span_type: string;
  duration_ms: number | null;
  input: unknown;
  output: unknown;
  input_tokens: number | null;
  output_tokens: number | null;
  estimated_cost: number | null;
  span_data: Record<string, unknown>;
  error: unknown;
};

type TraceDetail = TraceSummary & {
  metadata: Record<string, unknown>;
  spans: Span[];
};

type Metrics = {
  span_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  error_count: number;
  errored_span_count: number;
  spans_with_errors: SpanSummary[];
  spans_by_type: Record<string, number>;
  slowest_span: SpanSummary | null;
  most_expensive_span: SpanSummary | null;
};

type GroundingSummary = {
  status: string;
  final_grounded: boolean | null;
  recovered: boolean;
  unsupported_claim_count: number;
  supported_claim_count: number;
  validation_span_count: number;
  unsupported_claims: GroundingClaim[];
  supported_claims: GroundingClaim[];
};

type GroundingClaim = {
  claim: string;
  reason?: string;
  evidence?: string;
  span_id: string;
  span_name: string;
};

type SpanSummary = {
  name: string;
  span_type: string;
  duration_ms: number | null;
  estimated_cost: number | null;
};

type DashboardSummary = {
  total_runs: number;
  status_counts: Record<string, number>;
  workflow_counts: Record<string, number>;
  grounding_counts: Record<string, number>;
  source_format_counts: Record<string, number>;
  source_kind_counts: Record<string, number>;
  approval_pending_count: number;
  approval_rejected_count: number;
  unsupported_claim_count: number;
  error_count: number;
  average_duration_ms: number | null;
  p95_duration_ms: number | null;
  estimated_cost: number;
  input_tokens: number;
  output_tokens: number;
  memory_read_count: number;
  memory_write_count: number;
  memory_retrieved_count: number;
  memory_ignored_count: number;
  memory_stale_count: number;
  memory_warning_count: number;
  memory_average_relevance: number | null;
};

type TraceFilters = {
  status: string;
  workflowName: string;
  sourceFormat: string;
  sourceKind: string;
  errorStatus: string;
  approvalStatus: string;
  groundingStatus: string;
  timeRange: string;
  currentChatOnly: boolean;
  offset: number;
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "empty";
      traces: TraceSummary[];
      traceTotal: number;
      dashboard: DashboardSummary;
      workflows: string[];
    }
  | {
      status: "ready";
      traces: TraceSummary[];
      traceTotal: number;
      dashboard: DashboardSummary;
      workflows: string[];
      selectedTrace: TraceDetail;
      rawTrace: unknown;
      metrics: Metrics;
      grounding: GroundingSummary;
    };

type EvalRunStatus = { status: "idle" } | { status: "running" } | { status: "error"; message: string };

function App() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [chatSession, setChatSession] = useState<ChatSession | null>(null);
  const [chatSessions, setChatSessions] = useState<ChatSession[]>([]);
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [chatTraceSummaries, setChatTraceSummaries] = useState<Record<string, TraceSummary>>({});
  const [latestChatTraceId, setLatestChatTraceId] = useState<string | null>(null);
  const [chatStatus, setChatStatus] = useState<ChatStatus>({ status: "idle" });
  const [liveWorkflowRun, setLiveWorkflowRun] = useState<WorkflowRun<TraceDetail> | null>(null);
  const [liveWorkflowError, setLiveWorkflowError] = useState<string | null>(null);
  const [evalRun, setEvalRun] = useState<EvalSuiteRun | null>(null);
  const [evalHistory, setEvalHistory] = useState<EvalRunSummary[]>([]);
  const [evalComparison, setEvalComparison] = useState<EvalComparison | null>(null);
  const [evalRunStatus, setEvalRunStatus] = useState<EvalRunStatus>({ status: "idle" });
  const [evalMode, setEvalMode] = useState<EvalExecutionMode>("deterministic");
  const [filters, setFilters] = useState<TraceFilters>({
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
  });
  const [refreshKey, setRefreshKey] = useState(0);
  const chatSessionIdRef = useRef<string | null>(null);
  const liveWorkflowRunIdRef = useRef<string | null>(null);
  chatSessionIdRef.current = chatSession?.session_id ?? null;
  liveWorkflowRunIdRef.current = liveWorkflowRun?.run_id ?? null;

  useEffect(() => {
    const timer = window.setInterval(() => {
      setRefreshKey((value) => value + 1);
    }, 60000);
    return () => window.clearInterval(timer);
  }, []);

  useEffect(() => {
    loadChatSessions();
    loadEvalRuns();
  }, []);

  useEffect(() => {
    const events = new EventSource(`${API_BASE_URL}/events`);
    events.addEventListener("message", (rawEvent) => {
      handleServerEvent(parseServerEvent(rawEvent));
    });
    events.addEventListener("connected", () => {});
    [
      "chat.message.created",
      "chat.turn.started",
      "chat.turn.completed",
      "chat.turn.failed",
      "workflow_run.created",
      "workflow_run.updated",
      "workflow_run.completed",
      "workflow_run.failed",
      "workflow_run.cancelled",
      "trace.created",
      "trace.updated",
      "span.updated",
      "approval.updated",
      "dashboard.updated",
      "eval_run.created",
      "eval_run.updated",
      "eval_run.completed",
      "eval_run.failed",
    ].forEach((eventType) => {
      events.addEventListener(eventType, (rawEvent) => {
        handleServerEvent(parseServerEvent(rawEvent));
      });
    });
    return () => events.close();
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function loadChatTraceSummaries() {
      const traceIds = uniqueTraceIds(chatMessages);
      if (traceIds.length === 0) {
        setChatTraceSummaries({});
        return;
      }
      const summaries = await fetchJson<TraceSummary[]>(`/trace-summaries${traceSummaryQuery(traceIds)}`);
      if (!cancelled) {
        setChatTraceSummaries(summaryMap(summaries));
      }
    }
    loadChatTraceSummaries().catch(() => {
      if (!cancelled) {
        setChatTraceSummaries({});
      }
    });
    return () => {
      cancelled = true;
    };
  }, [chatMessages, refreshKey]);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [traceList, dashboard, workflows] = await Promise.all([
          fetchJson<TraceListResponse>(`/traces${filterQuery(filters, chatSession?.session_id ?? null)}`),
          fetchJson<DashboardSummary>("/dashboard/summary"),
          fetchJson<string[]>("/workflows"),
        ]);
        const traces = traceList.items;
        const safeOffset = clampedOffset(filters.offset, traceList.total, TRACE_PAGE_SIZE);
        if (safeOffset !== filters.offset) {
          if (!cancelled) {
            setFilters((current) => ({ ...current, offset: safeOffset }));
          }
          return;
        }
        const traceId = selectedTraceId ?? traces[0]?.trace_id;
        if (!traceId) {
          if (!cancelled) {
            setSelectedTraceId(null);
            setSelectedSpanId(null);
            setState({ status: "empty", traces, traceTotal: traceList.total, dashboard, workflows });
          }
          return;
        }
        const [selectedTrace, rawTrace, metrics, grounding] = await Promise.all([
          fetchJson<TraceDetail>(`/traces/${traceId}`),
          fetchJson<unknown>(`/traces/${traceId}/raw`),
          fetchJson<Metrics>(`/traces/${traceId}/metrics`),
          fetchJson<GroundingSummary>(`/traces/${traceId}/grounding`),
        ]);
        if (!cancelled) {
          setSelectedTraceId(traceId);
          setSelectedSpanId((currentSpanId) =>
            selectedTrace.spans.some((span) => span.span_id === currentSpanId)
              ? currentSpanId
              : selectedTrace.spans[0]?.span_id ?? null,
          );
          setState({
            status: "ready",
            traces,
            traceTotal: traceList.total,
            dashboard,
            workflows,
            selectedTrace,
            rawTrace,
            metrics,
            grounding,
          });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : "Unknown error" });
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [selectedTraceId, filters, refreshKey, chatSession?.session_id]);

  async function loadChatSessions() {
    try {
      setChatSessions(await listChatSessions(fetchJson));
    } catch {
      setChatSessions([]);
    }
  }

  async function loadEvalRuns() {
    try {
      const history = await listEvalRuns(fetchJson);
      setEvalHistory(history.items);
      setEvalComparison(await getSupportTriageEvalComparison(fetchJson));
    } catch {
      setEvalHistory([]);
      setEvalComparison(null);
    }
  }

  async function loadEvalRun(runId: string) {
    try {
      const run = await getEvalRun(fetchJson, runId);
      setEvalRun(run);
      if (run.error) {
        setEvalRunStatus({ status: "error", message: run.error });
      } else {
        setEvalRunStatus(run.status === "running" ? { status: "running" } : { status: "idle" });
      }
    } catch {
      // Leave the current eval state unchanged during transient SSE refresh races.
    }
  }

  function handleServerEvent(event: ServerEvent | null) {
    if (!event) return;
    if (event.type.startsWith("chat.") && event.session_id && event.session_id === chatSessionIdRef.current) {
      if (event.type === "chat.turn.completed" || event.type === "chat.turn.failed" || event.type === "chat.message.created") {
        refreshChatMessages(event.session_id);
      }
    }
    if (event.type.startsWith("workflow_run.") && event.run_id && event.run_id === liveWorkflowRunIdRef.current) {
      refreshWorkflowRun(event.run_id);
    }
    if (
      event.type === "trace.created" ||
      event.type === "trace.updated" ||
      event.type === "span.updated" ||
      event.type === "approval.updated" ||
      event.type === "dashboard.updated"
    ) {
      setRefreshKey((value) => value + 1);
    }
    if (event.type.startsWith("eval_run.")) {
      if (event.run_id) {
        loadEvalRun(event.run_id);
      }
      loadEvalRuns();
      setRefreshKey((value) => value + 1);
    }
  }

  async function refreshChatMessages(sessionId: string) {
    try {
      const messages = await getChatMessages(fetchJson, sessionId);
      const nextLatestTraceId = latestTraceFromMessages(messages);
      setChatMessages(messages);
      setLatestChatTraceId(nextLatestTraceId);
      if (nextLatestTraceId) {
        setSelectedTraceId(nextLatestTraceId);
        setSelectedSpanId(null);
      }
    } catch {
      setChatStatus({ status: "error", message: "Could not refresh chat messages." });
    }
  }

  async function refreshWorkflowRun(runId: string) {
    try {
      const run = await getWorkflowRun<TraceDetail>(fetchJson, runId);
      setLiveWorkflowRun(run);
      if (run.trace_id) {
        setSelectedTraceId(run.trace_id);
        setSelectedSpanId((currentSpanId) =>
          run.trace?.spans.some((span) => span.span_id === currentSpanId)
            ? currentSpanId
            : run.trace?.spans[0]?.span_id ?? null,
        );
      }
      if (run.status === "failed") {
        setLiveWorkflowError(run.error ?? "Workflow run failed.");
      }
    } catch (error) {
      setLiveWorkflowError(error instanceof Error ? error.message : "Could not refresh workflow run.");
    }
  }

  async function openChatSession(sessionId: string) {
    if (!sessionId) {
      startNewChatSession();
      return;
    }
    setChatStatus({ status: "idle" });
    const session = await getChatSession(fetchJson, sessionId);
    setChatSession(session);
    setChatMessages(session.messages);
    setLatestChatTraceId(latestTraceFromMessages(session.messages));
    setRefreshKey((value) => value + 1);
  }

  function startNewChatSession() {
    setChatSession(null);
    setChatMessages([]);
    setLatestChatTraceId(null);
    setChatStatus({ status: "idle" });
    if (filters.currentChatOnly) {
      setFilters({ ...filters, currentChatOnly: false, offset: 0 });
    }
  }

  async function updateApproval(spanId: string, action: ApprovalAction) {
    if (state.status !== "ready") {
      return;
    }
    await postJson(`/traces/${state.selectedTrace.trace_id}/approvals/${spanId}/${action}`);
    const sessionId = stringMetadata(state.selectedTrace.metadata.chat_session_id);
    if (sessionId && chatSession?.session_id === sessionId) {
      const session = await getChatSession(fetchJson, sessionId);
      setChatSession(session);
      setChatMessages(session.messages);
      setChatSessions((sessions) => upsertChatSession(sessions, session));
    }
    setRefreshKey((value) => value + 1);
  }

  function updateTraceFilters(nextFilters: TraceFilters) {
    setSelectedTraceId(null);
    setSelectedSpanId(null);
    setFilters(nextFilters);
  }

  function updateTracePage(offset: number) {
    setSelectedTraceId(null);
    setSelectedSpanId(null);
    setFilters((current) => ({ ...current, offset }));
  }

  async function startLiveWorkflow(input: LiveWorkflowInput) {
    setLiveWorkflowError(null);
    try {
      const run = await startSupportTriageLiveRun<TraceDetail>(apiPostJson, {
        message: input.message,
        customerEmail: input.customerEmail,
        llmProvider: input.llmProvider,
      });
      setLiveWorkflowRun(run);
      if (run.trace_id) {
        setSelectedTraceId(run.trace_id);
        setSelectedSpanId(run.trace?.spans[0]?.span_id ?? null);
      }
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setLiveWorkflowError(error instanceof Error ? error.message : "Could not start workflow run.");
    }
  }

  async function cancelLiveWorkflow() {
    if (!liveWorkflowRun) {
      return;
    }
    setLiveWorkflowError(null);
    try {
      const run = await cancelWorkflowRun<TraceDetail>(apiPostJson, liveWorkflowRun.run_id);
      setLiveWorkflowRun(run);
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setLiveWorkflowError(error instanceof Error ? error.message : "Could not cancel workflow run.");
    }
  }

  async function retryLiveWorkflow() {
    if (!liveWorkflowRun) {
      return;
    }
    setLiveWorkflowError(null);
    try {
      const run = await retryWorkflowRun<TraceDetail>(apiPostJson, liveWorkflowRun.run_id);
      setLiveWorkflowRun(run);
      if (run.trace_id) {
        setSelectedTraceId(run.trace_id);
        setSelectedSpanId(run.trace?.spans[0]?.span_id ?? null);
      }
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setLiveWorkflowError(error instanceof Error ? error.message : "Could not retry workflow run.");
    }
  }

  async function runEvals() {
    setEvalRunStatus({ status: "running" });
    try {
      const result =
        evalMode === "llm"
          ? await startSupportTriageEvalSuite(apiPostJson, evalMode)
          : await runSupportTriageEvalSuite(apiPostJson, evalMode);
      setEvalRun(result);
      setEvalHistory((history) => [result, ...history.filter((item) => item.run_id !== result.run_id)].slice(0, 5));
      setEvalComparison(await getSupportTriageEvalComparison(fetchJson));
      setEvalRunStatus(result.status === "running" ? { status: "running" } : { status: "idle" });
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setEvalRunStatus({ status: "error", message: error instanceof Error ? error.message : "Could not run evals." });
    }
  }

  async function resumeEvals() {
    if (!evalRun) {
      return;
    }
    setEvalRunStatus({ status: "running" });
    try {
      const result = await resumeEvalRun(apiPostJson, evalRun.run_id);
      setEvalRun(result);
      setEvalHistory((history) => [result, ...history.filter((item) => item.run_id !== result.run_id)].slice(0, 5));
      setEvalComparison(await getSupportTriageEvalComparison(fetchJson));
      setEvalRunStatus(result.status === "running" ? { status: "running" } : { status: "idle" });
      setRefreshKey((value) => value + 1);
    } catch (error) {
      setEvalRunStatus({ status: "error", message: error instanceof Error ? error.message : "Could not resume evals." });
    }
  }

  async function submitChatTurn(input: ChatInput) {
    setChatStatus({ status: "submitting" });
    let pendingMessage: ChatMessage | null = null;
    try {
      const session =
        chatSession ??
        (await createChatSession(apiPostJson, {
          customerEmail: input.customerEmail,
          title: "Customer support",
        }));
      if (!chatSession) {
        setChatSession(session);
        setChatSessions((sessions) => upsertChatSession(sessions, session));
      }
      pendingMessage = createPendingUserMessage({ sessionId: session.session_id, content: input.message });
      setChatMessages((messages) => [...messages, pendingMessage!]);
      const result = await sendChatMessageAsync(apiPostJson, session.session_id, {
        content: input.message,
        llmProvider: input.llmProvider,
      });
      setChatSession(result.session);
      setChatSessions((sessions) => upsertChatSession(sessions, result.session));
      setChatMessages((messages) =>
        replacePendingChatMessage(messages, pendingMessage!.message_id, result.user_message, result.assistant_message),
      );
      setRefreshKey((value) => value + 1);
      setChatStatus({ status: "idle" });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unknown chat error";
      if (pendingMessage) {
        setChatMessages((messages) => markPendingMessageFailed(messages, pendingMessage!.message_id, message));
      }
      setChatStatus({ status: "error", message });
    }
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
              activeChatSessionId={chatSession?.session_id ?? null}
            latestChatTraceId={latestChatTraceId}
            onFiltersChange={updateTraceFilters}
            onSelectTrace={setSelectedTraceId}
            onClearSelection={() => setSelectedSpanId(null)}
            onPageChange={updateTracePage}
          />
          <main className="main">
            <DashboardSummaryPanel summary={state.dashboard} />
            <EvalDashboardPanel
              run={evalRun}
              history={evalHistory}
              comparison={evalComparison}
              status={evalRunStatus}
              mode={evalMode}
              onModeChange={setEvalMode}
              onRun={runEvals}
              onResume={resumeEvals}
              onSelectEvalRun={loadEvalRun}
              onSelectTrace={setSelectedTraceId}
            />
            <LiveWorkflowPanel
              run={liveWorkflowRun}
              error={liveWorkflowError}
              onStart={startLiveWorkflow}
              onCancel={cancelLiveWorkflow}
              onRetry={retryLiveWorkflow}
            />
            <ChatMonitor
              session={chatSession}
              sessions={chatSessions}
              messages={chatMessages}
              traceSummaries={chatTraceSummaries}
              status={chatStatus}
              latestTraceId={latestChatTraceId}
              onSelectSession={openChatSession}
              onNewSession={startNewChatSession}
              onSelectTrace={setSelectedTraceId}
              onSubmit={submitChatTurn}
            />
            <EmptyRunsState onClearFilters={() => updateTraceFilters(emptyFilters())} />
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
          activeChatSessionId={chatSession?.session_id ?? null}
          latestChatTraceId={latestChatTraceId}
          onFiltersChange={updateTraceFilters}
          onSelectTrace={setSelectedTraceId}
          onClearSelection={() => setSelectedSpanId(null)}
          onPageChange={updateTracePage}
        />

        <main className="main">
          <DashboardSummaryPanel summary={state.dashboard} />
          <EvalDashboardPanel
            run={evalRun}
            history={evalHistory}
            comparison={evalComparison}
            status={evalRunStatus}
            mode={evalMode}
            onModeChange={setEvalMode}
            onRun={runEvals}
            onResume={resumeEvals}
            onSelectEvalRun={loadEvalRun}
            onSelectTrace={setSelectedTraceId}
          />
          <LiveWorkflowPanel
            run={liveWorkflowRun}
            error={liveWorkflowError}
            onStart={startLiveWorkflow}
            onCancel={cancelLiveWorkflow}
            onRetry={retryLiveWorkflow}
          />
          <ChatMonitor
            session={chatSession}
            sessions={chatSessions}
            messages={chatMessages}
            traceSummaries={chatTraceSummaries}
            status={chatStatus}
            latestTraceId={latestChatTraceId}
            onSelectSession={openChatSession}
            onNewSession={startNewChatSession}
            onSelectTrace={setSelectedTraceId}
            onSubmit={submitChatTurn}
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

function RunsSidebar({
  traces,
  traceTotal,
  selectedTraceId,
  filters,
  workflows,
  activeChatSessionId,
  latestChatTraceId,
  onFiltersChange,
  onSelectTrace,
  onClearSelection,
  onPageChange,
}: {
  traces: TraceSummary[];
  traceTotal: number;
  selectedTraceId: string | null;
  filters: TraceFilters;
  workflows: string[];
  activeChatSessionId: string | null;
  latestChatTraceId: string | null;
  onFiltersChange: (filters: TraceFilters) => void;
  onSelectTrace: (traceId: string) => void;
  onClearSelection: () => void;
  onPageChange: (offset: number) => void;
}) {
  const hasPrevious = filters.offset > 0;
  const nextPageOffset = nextOffset(filters.offset, TRACE_PAGE_SIZE);
  const hasNext = hasNextPage(filters.offset, traceTotal, TRACE_PAGE_SIZE);

  return (
    <aside className="sidebar" aria-label="Runs inbox">
      <div className="sidebarHeader">Runs Inbox</div>
      <TraceFiltersPanel
        filters={filters}
        workflows={workflows}
        activeChatSessionId={activeChatSessionId}
        onChange={onFiltersChange}
      />
      <div className="runsCount">{traceTotal} matching runs</div>
      <div className="traceList">
        {traces.map((trace) => (
          <button
            className={trace.trace_id === selectedTraceId ? "traceButton active" : "traceButton"}
            key={trace.trace_id}
            onClick={() => onSelectTrace(trace.trace_id)}
            onDoubleClick={onClearSelection}
          >
            <span>{trace.workflow_name}</span>
            <small>{trace.trace_id}</small>
            <TraceBadges
              trace={trace}
              isChatTurn={isChatTrace(trace, activeChatSessionId)}
              isLatestChatTrace={isLatestChatTrace(trace.trace_id, latestChatTraceId)}
            />
          </button>
        ))}
      </div>
      <div className="paginationControls">
        <button disabled={!hasPrevious} onClick={() => onPageChange(previousOffset(filters.offset, TRACE_PAGE_SIZE))}>
          Previous
        </button>
        <span>{pageRange(filters.offset, traces.length, traceTotal)}</span>
        <button disabled={!hasNext} onClick={() => onPageChange(nextPageOffset)}>
          Next
        </button>
      </div>
    </aside>
  );
}

function Shell({ children, status, error }: { children?: React.ReactNode; status: string; error?: string }) {
  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <Network size={24} />
          <div>
            <h1>AgentTrace</h1>
            <p>Multi-agent workflow trace analysis</p>
          </div>
        </div>
        <div className={error ? "status error" : "status"}>
          {error ? <AlertCircle size={16} /> : <Activity size={16} />}
          <span>{status}</span>
        </div>
      </header>
      {error ? <div className="errorPanel">{error}</div> : children}
    </div>
  );
}

type ChatStatus = { status: "idle" } | { status: "submitting" } | { status: "error"; message: string };

type ChatInput = {
  customerEmail: string;
  message: string;
  llmProvider: LLMProvider;
};

type ServerEvent = {
  type: string;
  resource_type?: string;
  resource_id?: string;
  session_id?: string;
  message_id?: string;
  trace_id?: string;
  run_id?: string;
};

type LiveWorkflowInput = ChatInput;

function LiveWorkflowPanel({
  run,
  error,
  onStart,
  onCancel,
  onRetry,
}: {
  run: WorkflowRun<TraceDetail> | null;
  error: string | null;
  onStart: (input: LiveWorkflowInput) => Promise<void>;
  onCancel: () => Promise<void>;
  onRetry: () => Promise<void>;
}) {
  const [customerEmail, setCustomerEmail] = useState("customer@example.com");
  const [message, setMessage] = useState("I was charged twice for my Pro subscription yesterday. Can I get a refund?");
  const [llmProvider, setLlmProvider] = useState<LLMProvider>("deterministic");
  const active = isWorkflowRunActive(run);
  const canRetry = run?.status === "failed" || run?.status === "cancelled";

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedEmail = customerEmail.trim();
    const trimmedMessage = message.trim();
    if (!trimmedEmail || !trimmedMessage || active) {
      return;
    }
    await onStart({ customerEmail: trimmedEmail, message: trimmedMessage, llmProvider });
  }

  return (
    <section className="liveWorkflow">
      <div className="liveWorkflowHeader">
        <div>
          <small>Running workflow monitor</small>
          <h2>Support-triage live run</h2>
        </div>
        <span className={run?.status === "failed" || run?.status === "cancelled" ? "liveRunStatus failed" : "liveRunStatus"}>
          {active ? <Activity size={15} /> : <GitBranch size={15} />}
          {run?.status ?? "idle"}
        </span>
      </div>
      <form className="liveWorkflowForm" onSubmit={submit}>
        <label>
          <span>Customer email</span>
          <input value={customerEmail} onChange={(event) => setCustomerEmail(event.target.value)} disabled={active} />
        </label>
        <label className="liveWorkflowMessage">
          <span>Message</span>
          <input value={message} onChange={(event) => setMessage(event.target.value)} disabled={active} />
        </label>
        <label>
          <span>LLM provider</span>
          <select value={llmProvider} onChange={(event) => setLlmProvider(event.target.value as LLMProvider)} disabled={active}>
            <option value="deterministic">Deterministic</option>
            <option value="openai_compatible">Configured LLM</option>
          </select>
        </label>
        <button type="submit" disabled={active || !message.trim()}>
          {active ? <Activity size={15} /> : <Send size={15} />}
          Run
        </button>
        <button className="secondary" type="button" disabled={!active} onClick={onCancel}>
          Cancel
        </button>
        <button className="secondary" type="button" disabled={!canRetry} onClick={onRetry}>
          <RotateCcw size={15} />
          Retry
        </button>
      </form>
      {run ? (
        <div className="liveRunDetails">
          <span>Run: {run.run_id}</span>
          {run.trace_id ? <span>Trace: {run.trace_id}</span> : <span>Trace pending</span>}
          {run.trace ? <span>{run.trace.spans.length} spans visible</span> : null}
          {run.completed_at ? <span>Completed: {run.completed_at}</span> : <span>Updated: {run.updated_at}</span>}
        </div>
      ) : null}
      {error ? <p className="chatError">{error}</p> : null}
    </section>
  );
}

function ChatMonitor({
  session,
  sessions,
  messages,
  traceSummaries,
  status,
  latestTraceId,
  onSelectSession,
  onNewSession,
  onSelectTrace,
  onSubmit,
}: {
  session: ChatSession | null;
  sessions: ChatSession[];
  messages: ChatMessage[];
  traceSummaries: Record<string, TraceSummary>;
  status: ChatStatus;
  latestTraceId: string | null;
  onSelectSession: (sessionId: string) => Promise<void>;
  onNewSession: () => void;
  onSelectTrace: (traceId: string) => void;
  onSubmit: (input: ChatInput) => Promise<void>;
}) {
  const [customerEmail, setCustomerEmail] = useState("customer@example.com");
  const [message, setMessage] = useState("I was charged twice for my Pro subscription yesterday. Can I get a refund?");
  const [llmProvider, setLlmProvider] = useState<LLMProvider>("deterministic");
  const isSubmitting = status.status === "submitting";

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedMessage = message.trim();
    const trimmedEmail = customerEmail.trim();
    if (!trimmedMessage || !trimmedEmail || isSubmitting) {
      return;
    }
    setMessage("");
    await onSubmit({ customerEmail: trimmedEmail, message: trimmedMessage, llmProvider });
  }

  return (
    <section className="chatMonitor" aria-label="Live customer-service agent">
      <div className="chatHeader">
        <div>
          <small>Live customer-service agent</small>
          <h2>Chat monitor</h2>
        </div>
        <div className="chatSessionControls">
          <select value={session?.session_id ?? ""} onChange={(event) => onSelectSession(event.target.value)}>
            <option value="">New session</option>
            {sessions.map((chatSession) => (
              <option value={chatSession.session_id} key={chatSession.session_id}>
                {chatSession.title ?? chatSession.customer_email} · {chatSession.customer_email}
              </option>
            ))}
          </select>
          <button type="button" onClick={onNewSession}>
            New
          </button>
        </div>
      </div>
      <div className="chatBody">
        <form className="chatComposer" onSubmit={submit}>
          <label>
            <span>Customer email</span>
            <input
              value={customerEmail}
              onChange={(event) => setCustomerEmail(event.target.value)}
              disabled={Boolean(session) || isSubmitting}
            />
          </label>
          <label className="chatMessageInput">
            <span>Message</span>
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} disabled={isSubmitting} />
          </label>
          <label>
            <span>LLM provider</span>
            <select
              value={llmProvider}
              onChange={(event) => setLlmProvider(event.target.value as LLMProvider)}
              disabled={isSubmitting}
            >
              <option value="deterministic">Deterministic</option>
              <option value="openai_compatible">Configured LLM</option>
            </select>
          </label>
          <button type="submit" disabled={isSubmitting || !message.trim()}>
            {isSubmitting ? <Activity size={15} /> : <Send size={15} />}
            {isSubmitting ? "Sending" : "Send"}
          </button>
          {status.status === "error" ? <p className="chatError">{status.message}</p> : null}
        </form>
        <div className="chatThread" aria-live="polite">
          {messages.length === 0 ? (
            <div className="chatEmpty">
              <MessageSquare size={18} />
              <span>Send a customer message to generate a monitored trace.</span>
            </div>
          ) : (
            messages.map((chatMessage) => {
              const isPending = chatMessage.metadata.pending === true;
              const errorMessage = typeof chatMessage.metadata.error === "string" ? chatMessage.metadata.error : null;
              return (
                <div
                  className={`chatBubble ${chatMessage.role}${isPending ? " pending" : ""}${
                    errorMessage ? " error" : ""
                  }`}
                  key={chatMessage.message_id}
                >
                  <small>{chatMessage.role}</small>
                  <p>{chatMessage.content}</p>
                  {errorMessage ? <span className="chatMessageError">{errorMessage}</span> : null}
                  {chatMessage.trace_id ? (
                    <div className="chatMessageChips">
                      {buildChatMessageChips(traceSummaries[chatMessage.trace_id]).map((chip) => (
                        <span className={`chatMessageChip ${chip.tone}`} key={chip.label}>
                          {chip.label}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {chatMessage.trace_id ? (
                    <button className="chatTraceLink" type="button" onClick={() => onSelectTrace(chatMessage.trace_id!)}>
                      Trace: {chatMessage.trace_id}
                      {chatMessage.trace_id === latestTraceId ? <strong>Latest</strong> : null}
                    </button>
                  ) : null}
                </div>
              );
            })
          )}
          {isSubmitting ? (
            <div className="chatBubble assistant pending" aria-label="Assistant response pending">
              <small>assistant</small>
              <p>Checking account, policy, and approval context</p>
              <span className="typingDots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}

function TraceHeader({ trace, executionStatus }: { trace: TraceDetail; executionStatus: string }) {
  const sourceFormat = stringMetadata(trace.metadata.source_format);
  const sourceKind = stringMetadata(trace.metadata.source_kind);
  const ingestedAt = stringMetadata(trace.metadata.ingested_at);

  return (
    <section className="traceHeader" aria-label="Selected trace">
      <div>
        <div className="eyebrow">{trace.trace_id}</div>
        <h2>{trace.workflow_name}</h2>
      </div>
      <div className="traceMeta">
        <span>Execution: {executionStatus}</span>
        {sourceFormat ? <span>Source: {sourceLabel(sourceFormat)}</span> : null}
        {sourceKind ? <span>Format: {sourceKindLabel(sourceKind)}</span> : null}
        {ingestedAt ? <span>Ingested: {ingestedAt}</span> : null}
        <span>{formatDuration(trace.duration_ms)}</span>
      </div>
    </section>
  );
}

function EmptyRunsState({ onClearFilters }: { onClearFilters: () => void }) {
  return (
    <section className="emptyState">
      <AlertCircle size={22} />
      <div>
        <h2>No matching runs</h2>
        <p>Adjust the filters or clear them to return to the full runs inbox.</p>
      </div>
      <button type="button" onClick={onClearFilters}>
        Clear filters
      </button>
    </section>
  );
}

function DashboardSummaryPanel({ summary }: { summary: DashboardSummary }) {
  return (
    <section className="dashboardSummary">
      <div className="dashboardSummaryHeader">
        <div>
          <small>Operations dashboard</small>
          <h2>Fleet health</h2>
        </div>
        <span>{summary.total_runs} total runs</span>
      </div>
      <div className="fleetSummary">
        <SummaryFact icon={<GitBranch size={16} />} label="Runs" value={String(summary.total_runs)} />
        <SummaryFact icon={<UserCheck size={16} />} label="Approvals waiting" value={String(summary.approval_pending_count)} />
        <SummaryFact icon={<ShieldCheck size={16} />} label="Grounding issues" value={String(summary.unsupported_claim_count)} />
        <SummaryFact icon={<AlertCircle size={16} />} label="Errors" value={String(summary.error_count)} />
        <SummaryFact icon={<Clock3 size={16} />} label="Avg duration" value={formatDuration(summary.average_duration_ms)} />
        <SummaryFact icon={<Clock3 size={16} />} label="P95 duration" value={formatDuration(summary.p95_duration_ms)} />
        <SummaryFact icon={<CircleDollarSign size={16} />} label="Total cost" value={formatCost(summary.estimated_cost)} />
      </div>
      <div className="memoryFleetSummary">
        <SummaryFact
          icon={<Braces size={16} />}
          label="Memory events"
          value={`${summary.memory_read_count} reads · ${summary.memory_write_count} writes`}
        />
        <SummaryFact icon={<AlertCircle size={16} />} label="Memory warnings" value={String(summary.memory_warning_count)} />
        <SummaryFact icon={<Braces size={16} />} label="Ignored memory" value={String(summary.memory_ignored_count)} />
        <SummaryFact icon={<Clock3 size={16} />} label="Stale memory" value={String(summary.memory_stale_count)} />
        <SummaryFact icon={<ShieldCheck size={16} />} label="Avg relevance" value={formatRelevance(summary.memory_average_relevance)} />
      </div>
      <div className="sourceSummary">
        <SourceBreakdown title="Source mix" counts={summary.source_format_counts} labelForValue={sourceLabel} />
        <SourceBreakdown title="Ingest format" counts={summary.source_kind_counts} labelForValue={sourceKindLabel} />
      </div>
    </section>
  );
}

function EvalDashboardPanel({
  run,
  history,
  comparison,
  status,
  mode,
  onModeChange,
  onRun,
  onResume,
  onSelectEvalRun,
  onSelectTrace,
}: {
  run: EvalSuiteRun | null;
  history: EvalRunSummary[];
  comparison: EvalComparison | null;
  status: EvalRunStatus;
  mode: EvalExecutionMode;
  onModeChange: (mode: EvalExecutionMode) => void;
  onRun: () => Promise<void>;
  onResume: () => Promise<void>;
  onSelectEvalRun: (runId: string) => Promise<void>;
  onSelectTrace: (traceId: string) => void;
}) {
  const failures = failedEvalCases(run);
  const categorySummaries = evalCategorySummaries(run);
  const activeRun = evalRunIsActive(run);
  const running = status.status === "running" || activeRun;
  const progress = evalProgress(run);
  const visibleResults = run ? (failures.length > 0 ? failures : run.results).slice(0, 4) : [];
  const improvementPlan = buildEvalImprovementPlan(run);
  const resumable = Boolean(run && run.execution_mode === "llm" && evalRunHasProviderIssue(run) && run.results.length < run.total);

  return (
    <section className="evalDashboard">
      <div className="evalDashboardHeader">
        <div>
          <small>Evaluation dashboard</small>
          <h2>Support agent quality</h2>
        </div>
        <div className="evalRunControls">
          <select value={mode} onChange={(event) => onModeChange(event.target.value as EvalExecutionMode)} disabled={running}>
            <option value="deterministic">Deterministic baseline</option>
            <option value="llm">Configured LLM</option>
          </select>
          <button type="button" onClick={() => void onRun()} disabled={running}>
            {running ? <Activity size={15} /> : <FlaskConical size={15} />}
            Run evals
          </button>
          {resumable ? (
            <button className="secondary" type="button" onClick={() => void onResume()} disabled={running}>
              <RotateCcw size={15} />
              Resume eval
            </button>
          ) : null}
        </div>
      </div>
      <div className="evalSummaryGrid">
        <SummaryFact icon={<CheckCircle2 size={16} />} label="Status" value={evalStatusLabel(run)} />
        <SummaryFact icon={<Bot size={16} />} label="Mode" value={run ? evalModeLabel(run.execution_mode) : evalModeLabel(mode)} />
        <SummaryFact icon={<Activity size={16} />} label="Pass rate" value={run ? evalPassRateLabel(run.pass_rate) : "-"} />
        <SummaryFact icon={<GitBranch size={16} />} label="Cases" value={run ? (activeRun ? `${progress.completed}/${progress.total}` : `${run.passed}/${run.total}`) : "-"} />
        <SummaryFact icon={<AlertCircle size={16} />} label="Failures" value={run ? String(run.failed) : "-"} />
      </div>
      {activeRun ? (
        <div className="evalProgressPanel" role="status" aria-live="polite">
          <div className="evalProgressHeader">
            <div>
              <strong>LLM eval is running</strong>
              <span>Completed cases appear below as they finish.</span>
            </div>
            <em>{progress.label}</em>
          </div>
          <div className="evalProgressTrack" aria-label={progress.label}>
            <span className="evalProgressBar" style={{ width: `${progress.percent}%` }} />
          </div>
        </div>
      ) : null}
      <div className="evalCategoryStrip">
        {categorySummaries.map((summary) => (
          <span className={summary.failed > 0 ? "failed" : "passed"} key={summary.category}>
            {summary.category} <strong>{summary.failed}</strong>
          </span>
        ))}
      </div>
      <EvalTrendChart history={history} selectedRunId={run?.run_id ?? null} onSelectEvalRun={onSelectEvalRun} />
      <div
        className={
          comparison?.status === "degraded_llm" || evalRunHasProviderIssue(comparison?.llm_run ?? null)
            ? "evalComparison degraded"
            : comparison?.status === "ready" && comparison.llm_regressions.length > 0
              ? "evalComparison drift"
              : "evalComparison"
        }
      >
        <div>
          <small>Deterministic vs LLM</small>
          <strong>{evalComparisonStatusLabel(comparison)}</strong>
        </div>
        <span>
          Delta <strong>{evalRunHasProviderIssue(comparison?.llm_run ?? null) ? "degraded" : comparison?.pass_rate_delta === null || comparison?.pass_rate_delta === undefined ? "-" : `${Math.round(comparison.pass_rate_delta * 100)} pts`}</strong>
        </span>
        <span>
          Regressions <strong>{evalRunHasProviderIssue(comparison?.llm_run ?? null) ? "not scored" : comparison?.llm_regressions.length ?? "-"}</strong>
        </span>
        <span>
          Model <strong>{comparison?.llm_run ? `${comparison.llm_run.model_provider}/${comparison.llm_run.model_name}` : "-"}</strong>
        </span>
      </div>
      {status.status === "error" ? <p className="evalError">{status.message}</p> : null}
      {run && visibleResults.length > 0 ? (
        <div className="evalCases">
          {visibleResults.map((result) => (
            <div className={result.passed ? "evalCaseCard passed" : "evalCaseCard failed"} key={result.case_id}>
              <button type="button" onClick={() => onSelectTrace(result.trace_id)}>
                <span>{result.name}</span>
                <strong>{Math.round(result.score * 100)}%</strong>
              </button>
              {evalModelSummary(result) ? <EvalModelBadge result={result} /> : null}
              {!result.passed ? (
                <div className="evalCheckDetails">
                  {failedEvalChecks(result).slice(0, 3).map((check) => (
                    <div key={check.name}>
                      <small>{evalCheckCategory(check.name)}</small>
                      <strong>{check.name}</strong>
                      <span>Expected: {formatEvalValue(check.expected)}</span>
                      <span>Actual: {formatEvalValue(check.actual)}</span>
                    </div>
                  ))}
                  {failedEvalChecks(result).length > 3 ? <em>{failedEvalChecks(result).length - 3} more failed checks</em> : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : activeRun ? (
        <p className="evalEmpty">Waiting for the first case result...</p>
      ) : (
        <p className="evalEmpty">Run the deterministic suite to check routing, approvals, memory, and tool failures.</p>
      )}
      {improvementPlan.length > 0 ? (
        <div className="evalImprovementPlan">
          <div className="evalImprovementHeader">
            <small>Improvement plan</small>
            <strong>Use failures to patch the agent</strong>
          </div>
          {improvementPlan.slice(0, 4).map((item) => (
            <article className="evalImprovementItem" key={item.category}>
              <div>
                <span>{item.category}</span>
                <strong>{item.owner_area}</strong>
                <p>{item.recommended_action}</p>
              </div>
              <div className="evalImprovementFiles">
                {item.suggested_files.map((file) => (
                  <code key={file}>{file}</code>
                ))}
              </div>
              <div className="evalImprovementCases">
                {item.cases.slice(0, 3).map((failure) => (
                  <button key={`${failure.case_id}-${failure.check}`} type="button" onClick={() => onSelectTrace(failure.trace_id)}>
                    <span>{failure.case_id}</span>
                    <strong>{failure.check}</strong>
                    <em>
                      {formatEvalValue(failure.expected)} {"->"} {formatEvalValue(failure.actual)}
                    </em>
                  </button>
                ))}
                {item.cases.length > 3 ? <em>{item.cases.length - 3} more failed checks</em> : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {history.length > 0 ? (
        <div className="evalHistory">
          <small>Recent eval runs</small>
          {history.map((item) => (
            <button
              aria-current={run?.run_id === item.run_id ? "true" : undefined}
              className={item.failed === 0 ? "passed" : "failed"}
              key={item.run_id}
              onClick={() => void onSelectEvalRun(item.run_id)}
              type="button"
            >
              <span>{formatShortTimestamp(item.created_at)}</span>
              <strong>{evalPassRateLabel(item.pass_rate)}</strong>
              <em>{evalModeLabel(item.execution_mode)}</em>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function EvalTrendChart({
  history,
  selectedRunId,
  onSelectEvalRun,
}: {
  history: EvalRunSummary[];
  selectedRunId: string | null;
  onSelectEvalRun: (runId: string) => Promise<void>;
}) {
  const series = buildEvalTrendSeries(history);
  const totalRuns = series.deterministic.length + series.llm.length;
  if (totalRuns === 0) {
    return null;
  }

  return (
    <div className="evalTrendPanel">
      <div className="evalTrendHeader">
        <div>
          <small>Eval trend</small>
          <strong>Recent pass rate by mode</strong>
        </div>
        <span>{totalRuns} runs</span>
      </div>
      <div className="evalTrendSeriesGrid">
        <EvalTrendSeriesChart
          mode="deterministic"
          points={series.deterministic}
          selectedRunId={selectedRunId}
          onSelectEvalRun={onSelectEvalRun}
        />
        <EvalTrendSeriesChart mode="llm" points={series.llm} selectedRunId={selectedRunId} onSelectEvalRun={onSelectEvalRun} />
      </div>
      <div className="evalTrendMeta">
        {[...series.deterministic, ...series.llm]
          .sort((left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime())
          .slice(-4)
          .map((point) => (
            <button
              aria-current={selectedRunId === point.runId ? "true" : undefined}
              key={point.runId}
              onClick={() => void onSelectEvalRun(point.runId)}
              type="button"
            >
              <span>{formatShortTimestamp(point.createdAt)}</span>
              <strong>{point.passRate}%</strong>
              <em>{evalModeLabel(point.mode)}</em>
            </button>
          ))}
      </div>
    </div>
  );
}

function EvalTrendSeriesChart({
  mode,
  points,
  selectedRunId,
  onSelectEvalRun,
}: {
  mode: EvalExecutionMode;
  points: EvalTrendPoint[];
  selectedRunId: string | null;
  onSelectEvalRun: (runId: string) => Promise<void>;
}) {
  function handleChartClick(event: MouseHandlerDataParam) {
    const point = points.find((item) => item.label === event.activeLabel);
    if (point) {
      void onSelectEvalRun(point.runId);
    }
  }

  const latest = points.at(-1);
  return (
    <div className={mode === "llm" ? "evalTrendSeries llm" : "evalTrendSeries"}>
      <div className="evalTrendSeriesHeader">
        <strong>{evalModeLabel(mode)}</strong>
        <span>{latest ? `${latest.passRate}% latest` : "No runs"}</span>
      </div>
      {points.length > 0 ? (
        <div className="evalTrendChart" role="img" aria-label={`${evalModeLabel(mode)} eval pass-rate trend`}>
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={points} margin={{ top: 12, right: 10, bottom: 0, left: -20 }} onClick={handleChartClick}>
              <CartesianGrid stroke="#edf1f3" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#637179", fontSize: 11 }} />
              <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: "#637179", fontSize: 11 }} tickFormatter={(value) => `${value}%`} />
              <Tooltip content={<EvalTrendTooltip />} cursor={{ stroke: "#9bb7af", strokeWidth: 1 }} />
              <Line
                type="monotone"
                dataKey="passRate"
                stroke={mode === "llm" ? "#6f4ab8" : "#246b5b"}
                strokeWidth={2}
                dot={{ r: 4, strokeWidth: 2, fill: "#ffffff" }}
                activeDot={{
                  r: 6,
                  strokeWidth: 2,
                  fill: selectedRunId === latest?.runId ? "#172026" : mode === "llm" ? "#6f4ab8" : "#246b5b",
                  cursor: "pointer",
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="evalTrendEmpty">Run {evalModeLabel(mode).toLowerCase()} evals to start this trend.</p>
      )}
    </div>
  );
}

function EvalTrendTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: EvalTrendPoint }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) {
    return null;
  }
  return (
    <div className="evalTrendTooltip">
      <small>{formatShortTimestamp(point.createdAt)}</small>
      <strong>{point.passRate}% pass rate</strong>
      <span>
        {point.passed}/{point.total} passed, {point.failed} failed
      </span>
      <em>
        {evalModeLabel(point.mode)} · {point.model}
      </em>
    </div>
  );
}

function EvalModelBadge({ result }: { result: EvalSuiteRun["results"][number] }) {
  const event = evalModelSummary(result);
  if (!event) {
    return null;
  }
  const failedAttempt = event.attempts?.find((attempt) => attempt.status === "failed");
  return (
    <div className={event.fallback_used ? "evalModelBadge fallback" : "evalModelBadge"}>
      <span>{event.span_name}</span>
      <strong>{event.model ?? "model unknown"}</strong>
      {event.fallback_used ? <em>Fallback used{failedAttempt?.model ? ` after ${failedAttempt.model}` : ""}</em> : null}
    </div>
  );
}

function SourceBreakdown({
  title,
  counts,
  labelForValue,
}: {
  title: string;
  counts: Record<string, number>;
  labelForValue: (value: string) => string;
}) {
  const entries = Object.entries(counts).sort((left, right) => right[1] - left[1]);
  return (
    <div className="sourceBreakdown">
      <small>{title}</small>
      <div>
        {entries.length > 0 ? (
          entries.map(([value, count]) => (
            <span key={value}>
              {labelForValue(value)} <strong>{count}</strong>
            </span>
          ))
        ) : (
          <span>None <strong>0</strong></span>
        )}
      </div>
    </div>
  );
}

function TraceFiltersPanel({
  filters,
  workflows,
  activeChatSessionId,
  onChange,
}: {
  filters: TraceFilters;
  workflows: string[];
  activeChatSessionId: string | null;
  onChange: (filters: TraceFilters) => void;
}) {
  function update(next: Partial<TraceFilters>) {
    onChange({ ...filters, ...next, offset: 0 });
  }

  const activeCount = activeFilterCount(filters);

  return (
    <div className="traceFilters">
      <div className="filterHeader">
        <span>Filters</span>
        {activeCount > 0 ? <strong>{activeCount}</strong> : null}
        <button type="button" onClick={() => onChange(emptyFilters())} disabled={activeCount === 0}>
          Clear
        </button>
      </div>
      <details className="filterGroup" open>
        <summary>Run</summary>
        <div className="filterFields">
          <label>
            <span>Workflow</span>
            <select value={filters.workflowName} onChange={(event) => update({ workflowName: event.target.value })}>
              <option value="">Any</option>
              {workflows.map((workflow) => (
                <option value={workflow} key={workflow}>
                  {workflow}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Status</span>
            <select value={filters.status} onChange={(event) => update({ status: event.target.value })}>
              <option value="">Any</option>
              <option value="passed">Passed</option>
              <option value="failed">Failed</option>
              <option value="running">Running</option>
            </select>
          </label>
          <label className="inlineFilter">
            <input
              type="checkbox"
              checked={filters.currentChatOnly}
              disabled={!activeChatSessionId}
              onChange={(event) => update({ currentChatOnly: event.target.checked })}
            />
            <span>Current chat only</span>
          </label>
        </div>
      </details>
      <details className="filterGroup">
        <summary>Signals</summary>
        <div className="filterFields">
          <label>
            <span>Errors</span>
            <select value={filters.errorStatus} onChange={(event) => update({ errorStatus: event.target.value })}>
              <option value="">Any</option>
              <option value="true">Has errors</option>
              <option value="false">No errors</option>
            </select>
          </label>
          <label>
            <span>Approval</span>
            <select
              value={filters.approvalStatus}
              onChange={(event) => update({ approvalStatus: event.target.value })}
            >
              <option value="">Any</option>
              <option value="pending">Needs approval</option>
              <option value="approved">Approved</option>
              <option value="rejected">Rejected</option>
              <option value="none">No approval</option>
            </select>
          </label>
          <label>
            <span>Grounding</span>
            <select
              value={filters.groundingStatus}
              onChange={(event) => update({ groundingStatus: event.target.value })}
            >
              <option value="">Any</option>
              <option value="grounded">Grounded</option>
              <option value="recovered">Recovered</option>
              <option value="failed">Failed</option>
            </select>
          </label>
        </div>
      </details>
      <details className="filterGroup">
        <summary>Source</summary>
        <div className="filterFields">
          <label>
            <span>Source</span>
            <select value={filters.sourceFormat} onChange={(event) => update({ sourceFormat: event.target.value })}>
              <option value="">Any</option>
              <option value="agenttrace">AgentTrace</option>
              <option value="openai-agents">OpenAI Agents</option>
            </select>
          </label>
          <label>
            <span>Format</span>
            <select value={filters.sourceKind} onChange={(event) => update({ sourceKind: event.target.value })}>
              <option value="">Any</option>
              <option value="trace_export">Trace export</option>
              <option value="event_stream">Event stream</option>
              <option value="live_api">Live API</option>
            </select>
          </label>
          <label>
            <span>Time range</span>
            <select value={filters.timeRange} onChange={(event) => update({ timeRange: event.target.value })}>
              <option value="">Any time</option>
              <option value="15m">Last 15 minutes</option>
              <option value="1h">Last hour</option>
              <option value="24h">Last 24 hours</option>
            </select>
          </label>
        </div>
      </details>
    </div>
  );
}

function TraceBadges({
  trace,
  isChatTurn,
  isLatestChatTrace,
}: {
  trace: TraceSummary;
  isChatTurn: boolean;
  isLatestChatTrace: boolean;
}) {
  const chatBadges = chatTurnBadges(trace, { isChatTurn, isLatest: isLatestChatTrace });
  return (
    <div className="traceBadges">
      {chatBadges.map((badge) => (
        <strong className={badge === "Latest" ? "chip success" : "chip neutral"} key={badge}>
          {badge}
        </strong>
      ))}
      <span className={`chip status ${statusTone(trace.status)}`}>Status: {executionStatus(trace.status)}</span>
      <span className="chip neutral">{sourceLabel(trace.source_format)}</span>
      <span className="chip neutral">{sourceKindLabel(trace.source_kind)}</span>
      {trace.grounding_status !== trace.status ? (
        <span className={`chip grounding ${groundingTone(trace.grounding_status)}`}>Grounding: {trace.grounding_status}</span>
      ) : null}
      {trace.approval_pending_count > 0 ? <strong className="chip warning">Needs approval</strong> : null}
      {trace.approval_rejected_count > 0 ? <strong className="chip danger">Rejected</strong> : null}
      {trace.error_count > 0 ? <strong className="chip danger">Errors: {trace.error_count}</strong> : null}
      {trace.estimated_cost > 0.01 ? <strong className="chip warning">High cost</strong> : null}
      {trace.duration_ms !== null && trace.duration_ms > 5000 ? <strong className="chip warning">Slow</strong> : null}
    </div>
  );
}

function statusTone(status: string): string {
  if (status === "failed" || status === "rejected") return "danger";
  if (status === "running") return "warning";
  return "neutral";
}

function groundingTone(status: string): string {
  if (status === "failed") return "danger";
  if (status === "recovered") return "warning";
  if (status === "grounded") return "success";
  return "neutral";
}

function MetricGrid({ metrics, grounding }: { metrics: Metrics; grounding: GroundingSummary }) {
  return (
    <section className="metricGrid">
      <Metric icon={<GitBranch size={18} />} label="Spans" value={String(metrics.span_count)} />
      <Metric
        icon={<ShieldCheck size={18} />}
        label="Grounding"
        value={`${grounding.status} · ${grounding.unsupported_claim_count} unsupported`}
        tone={grounding.unsupported_claim_count > 0 ? "warning" : "normal"}
      />
      <Metric icon={<Braces size={18} />} label="Tokens" value={formatTokens(metrics.input_tokens, metrics.output_tokens)} />
      <Metric
        icon={<AlertCircle size={18} />}
        label="Errors"
        value={String(metrics.error_count)}
        tone={metrics.error_count > 0 ? "warning" : "normal"}
      />
      <Metric icon={<CircleDollarSign size={18} />} label="Cost" value={formatCost(metrics.estimated_cost)} />
    </section>
  );
}

function ExecutiveSummaryPanel({
  trace,
  metrics,
  grounding,
}: {
  trace: TraceDetail;
  metrics: Metrics;
  grounding: GroundingSummary;
}) {
  const approvals = countApprovals(trace.spans);
  const mcpCalls = trace.spans.filter((span) => span.span_data.tool_protocol === "mcp").length;
  const guardrails = trace.spans.filter((span) => span.span_type === "guardrail" || span.span_type === "validation").length;
  const memorySpans = trace.spans.filter((span) => span.span_type === "memory_read" || span.span_type === "memory_write");

  return (
    <section className={approvals.pending > 0 ? "executiveSummary attention" : "executiveSummary"}>
      <div className="summaryLead">
        <small>Executive summary</small>
        <strong>{buildExecutiveSummary(trace, metrics, grounding)}</strong>
      </div>
      <div className="summaryFacts">
        <SummaryFact icon={<UserCheck size={16} />} label="Approvals" value={`${approvals.pending} waiting`} />
        <SummaryFact icon={<ShieldCheck size={16} />} label="Grounding" value={grounding.recovered ? "recovered" : grounding.status} />
        <SummaryFact icon={<Wrench size={16} />} label="MCP calls" value={String(mcpCalls)} />
        <SummaryFact icon={<Braces size={16} />} label="Memory" value={`${memorySpans.length} events`} />
        <SummaryFact icon={<ShieldCheck size={16} />} label="Guardrails" value={String(guardrails)} />
        <SummaryFact icon={<Clock3 size={16} />} label="Duration" value={formatDuration(trace.duration_ms)} />
        <SummaryFact icon={<CircleDollarSign size={16} />} label="Cost" value={formatCost(metrics.estimated_cost)} />
      </div>
    </section>
  );
}

function SummaryFact({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="summaryFact">
      {icon}
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function Metric({
  icon,
  label,
  value,
  tone = "normal",
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  tone?: "normal" | "warning";
}) {
  return (
    <div className={tone === "warning" ? "metric warning" : "metric"}>
      <div className="metricIcon">{icon}</div>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function TraceTimeline({
  spans,
  selectedSpanId,
  onSelectSpan,
}: {
  spans: Span[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
}) {
  const rootSpans = useMemo(() => buildSpanTree(spans), [spans]);

  return (
    <section className="panel timelinePanel">
      <div className="panelHeader">
        <h3>Trace Timeline</h3>
        <span>{spans.length} spans</span>
      </div>
      <div className="timeline">
        {rootSpans.map((node) => (
          <SpanRow
            key={node.span.span_id}
            node={node}
            depth={0}
            selectedSpanId={selectedSpanId}
            onSelectSpan={onSelectSpan}
          />
        ))}
      </div>
    </section>
  );
}

function AgentFlowPanel({
  spans,
  selectedSpanId,
  onSelectSpan,
}: {
  spans: Span[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
}) {
  const steps = useMemo(() => buildAgentFlow(spans), [spans]);
  if (steps.length === 0) {
    return null;
  }
  return (
    <section className="agentFlowPanel" aria-label="Agent flow">
      <div className="panelHeader">
        <h3>Agent Flow</h3>
        <span>{steps.length} agents</span>
      </div>
      <div className="agentFlow">
        {steps.map((step, index) => (
          <React.Fragment key={step.spanId}>
            <AgentFlowCard
              step={step}
              selected={step.spanId === selectedSpanId}
              onSelectSpan={onSelectSpan}
            />
            {index < steps.length - 1 ? (
              <span className="agentFlowArrow" aria-hidden="true">
                <ArrowRight size={16} />
              </span>
            ) : null}
          </React.Fragment>
        ))}
      </div>
    </section>
  );
}

function AgentFlowCard({
  step,
  selected,
  onSelectSpan,
}: {
  step: AgentFlowStep;
  selected: boolean;
  onSelectSpan: (spanId: string) => void;
}) {
  const decisionSource = formatDecisionSource(step.decisionSource);
  return (
    <button
      className={["agentFlowCard", selected ? "selected" : "", step.approvalPending ? "approvalPending" : "", step.errorCount > 0 ? "errored" : ""]
        .filter(Boolean)
        .join(" ")}
      type="button"
      onClick={() => onSelectSpan(step.spanId)}
    >
      <div className="agentFlowTitle">
        <span>{agentFlowIcon(step.role)}</span>
        <strong>{step.label}</strong>
      </div>
      <div className="agentFlowFacts">
        <span>{formatDuration(step.durationMs)}</span>
        {step.model ? <span>{step.model}</span> : null}
        {decisionSource ? <span>{decisionSource.label}</span> : null}
        {step.tokenTotal > 0 ? <span>{step.tokenTotal} tokens</span> : null}
        {step.estimatedCost ? <span>{formatCost(step.estimatedCost)}</span> : null}
      </div>
      <div className="agentFlowBadges">
        {step.handoffCount > 0 ? <em>{step.handoffCount} handoff</em> : null}
        {step.toolCount > 0 ? <em>{step.toolCount} tool</em> : null}
        {step.modelFallbackUsed ? <strong>Model fallback</strong> : null}
        {step.approvalPending ? <strong>Approval needed</strong> : null}
        {step.errorCount > 0 ? <strong>{step.errorCount} error</strong> : null}
      </div>
    </button>
  );
}

function agentFlowIcon(role: string) {
  if (role === "supervisor") return <Network size={15} />;
  if (role === "validator") return <ShieldCheck size={15} />;
  if (role === "response") return <MessageSquare size={15} />;
  return <Bot size={15} />;
}

function SpanRow({
  node,
  depth,
  selectedSpanId,
  onSelectSpan,
}: {
  node: SpanNode;
  depth: number;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
}) {
  const span = node.span;
  const approvalStatus = getApprovalStatus(span.span_type, span.span_data);
  const decisionSource = formatDecisionSource(span.span_data.decision_source);
  const rowClassName = [
    "spanRow",
    span.span_id === selectedSpanId ? "selected" : "",
    approvalStatus?.isPending ? "approvalPending" : "",
    span.error ? "errored" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <>
      <button
        className={rowClassName}
        style={{ paddingLeft: `${depth * 22 + 12}px` }}
        onClick={() => onSelectSpan(span.span_id)}
      >
        <span className={`spanType ${span.span_type}`}>{spanIcon(span.span_type)}</span>
        <div className="spanMain">
          <strong>{span.name}</strong>
          <small>{span.span_type}</small>
        </div>
        <div className="spanMeta">
          {approvalStatus?.isPending ? <span className="approvalBadge">Needs approval</span> : null}
          {span.error ? <span className="errorBadge">Error</span> : null}
          {decisionSource ? <span className={`decisionBadge ${decisionSource.className}`}>{decisionSource.label}</span> : null}
          <span>{formatDuration(span.duration_ms)}</span>
          {span.input_tokens || span.output_tokens ? <span>{formatTokens(span.input_tokens ?? 0, span.output_tokens ?? 0)}</span> : null}
          {span.estimated_cost ? <span>{formatCost(span.estimated_cost)}</span> : null}
          {typeof span.span_data.tool_server === "string" ? <span>{span.span_data.tool_server}</span> : null}
        </div>
      </button>
      {node.children.map((child) => (
        <SpanRow
          key={child.span.span_id}
          node={child}
          depth={depth + 1}
          selectedSpanId={selectedSpanId}
          onSelectSpan={onSelectSpan}
        />
      ))}
    </>
  );
}

function formatDecisionSource(value: unknown): { label: string; className: string } | null {
  if (typeof value !== "string" || value.length === 0) {
    return null;
  }
  if (value === "llm") {
    return { label: "LLM decision", className: "llm" };
  }
  if (value === "fallback") {
    return { label: "Fallback decision", className: "fallback" };
  }
  if (value === "policy_validation") {
    return { label: "Policy validation", className: "validation" };
  }
  if (value === "deterministic") {
    return { label: "Deterministic", className: "deterministic" };
  }
  return { label: value.replaceAll("_", " "), className: "unknown" };
}

function AnalysisPanel({
  metrics,
  grounding,
  spans,
  rawTrace,
  selectedSpanId,
  onSelectSpan,
  onApprovalAction,
}: {
  metrics: Metrics;
  grounding: GroundingSummary;
  spans: Span[];
  rawTrace: unknown;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const mcpSpans = spans.filter((span) => span.span_data.tool_protocol === "mcp");
  const guardrails = spans.filter((span) => span.span_type === "guardrail" || span.span_type === "validation");
  const approvals = spans.filter((span) => span.span_type === "approval");
  const pendingApprovals = approvals.filter((span) => getApprovalStatus(span.span_type, span.span_data)?.isPending);
  const handoffs = spans.filter((span) => span.span_type === "handoff");
  const memorySpans = spans.filter((span) => span.span_type === "memory_read" || span.span_type === "memory_write");
  const memoryReads = memorySpans.filter((span) => span.span_type === "memory_read").length;
  const memoryWrites = memorySpans.filter((span) => span.span_type === "memory_write").length;
  const memorySummary = buildMemorySummary(spans);
  const erroredSpans = spans.filter((span) => span.error);
  const selectedSpan = spans.find((span) => span.span_id === selectedSpanId) ?? spans[0];

  return (
    <section className="panel analysisPanel">
      <div className="panelHeader">
        <h3>Analysis</h3>
        <span>{metrics.span_count} events</span>
      </div>
      <div className="analysisList">
        <Insight
          icon={<ShieldCheck size={16} />}
          label="Grounding"
          value={`${grounding.status} · ${grounding.unsupported_claim_count} unsupported`}
        />
        <Insight icon={<ArrowRight size={16} />} label="Handoffs" value={`${handoffs.length} supervisor routes`} />
        <Insight icon={<Wrench size={16} />} label="MCP tools" value={`${mcpSpans.length} calls captured`} />
        <Insight icon={<Braces size={16} />} label="Memory" value={`${memoryReads} reads · ${memoryWrites} writes`} />
        <Insight icon={<ShieldCheck size={16} />} label="Guardrails" value={`${guardrails.length} validation span`} />
        <Insight icon={<UserCheck size={16} />} label="Approvals" value={`${pendingApprovals.length} waiting · ${approvals.length} total`} />
        <Insight icon={<AlertCircle size={16} />} label="Errors" value={`${erroredSpans.length} errored span`} />
        <Insight icon={<CircleDollarSign size={16} />} label="Most expensive" value={metrics.most_expensive_span?.name ?? "-"} />
      </div>
      <ApprovalQueue approvals={approvals} onSelectSpan={onSelectSpan} onApprovalAction={onApprovalAction} />
      <GroundingPanel grounding={grounding} onSelectSpan={onSelectSpan} />
      <MemoryPanel summary={memorySummary} onSelectSpan={onSelectSpan} />
      <div className="typeBreakdown">
        {Object.entries(metrics.spans_by_type).map(([type, count]) => (
          <div key={type} className="typeBar">
            <span>{type}</span>
            <div>
              <i style={{ width: `${Math.max(8, count * 18)}px` }} />
            </div>
            <strong>{count}</strong>
          </div>
        ))}
      </div>
      {mcpSpans.length > 0 ? (
        <div className="quickLinks">
          <small>MCP tool calls</small>
          {mcpSpans.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {memorySpans.length > 0 ? (
        <div className="quickLinks">
          <small>Memory events</small>
          {memorySpans.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {erroredSpans.length > 0 ? (
        <div className="quickLinks errorLinks">
          <small>Errored spans</small>
          {erroredSpans.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {guardrails.length > 0 ? (
        <div className="quickLinks">
          <small>Guardrails and validation</small>
          {guardrails.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {selectedSpan ? <SpanDetail span={selectedSpan} rawTrace={rawTrace} onApprovalAction={onApprovalAction} /> : null}
    </section>
  );
}

function ApprovalQueue({
  approvals,
  onSelectSpan,
  onApprovalAction,
}: {
  approvals: Span[];
  onSelectSpan: (spanId: string) => void;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  if (approvals.length === 0) {
    return null;
  }

  return (
    <section className="approvalQueue" aria-label="Approval gates">
      <div className="approvalQueueHeader">
        <div>
          <strong>Approval gates</strong>
          <small>{approvals.length} human checkpoint in this trace</small>
        </div>
        <UserCheck size={18} />
      </div>
      {approvals.map((span) => {
        const status = getApprovalStatus(span.span_type, span.span_data);
        if (!status) return null;
        return (
          <div className={status.isPending ? "approvalQueueItem pending" : "approvalQueueItem"} key={span.span_id}>
            <button className="approvalQueueTitle" onClick={() => onSelectSpan(span.span_id)}>
              <strong>{span.name}</strong>
              <span>{status.approvalStatus}</span>
            </button>
            <div className="approvalQueueMeta">
              <span>{status.riskLevel ?? "risk unknown"}</span>
              <span>{status.permissionScope ?? "scope unknown"}</span>
            </div>
            <ApprovalActions spanId={span.span_id} status={status} onApprovalAction={onApprovalAction} />
          </div>
        );
      })}
    </section>
  );
}

function GroundingPanel({
  grounding,
  onSelectSpan,
}: {
  grounding: GroundingSummary;
  onSelectSpan: (spanId: string) => void;
}) {
  if (grounding.validation_span_count === 0) {
    return null;
  }

  return (
    <div className={grounding.unsupported_claim_count > 0 ? "groundingPanel warning" : "groundingPanel"}>
      <div className="groundingHeader">
        <strong>Grounding summary</strong>
        <span>{grounding.recovered ? "Recovered" : grounding.status}</span>
      </div>
      {grounding.unsupported_claims.length > 0 ? (
        <div className="groundingClaims">
          <small>Unsupported claims</small>
          {grounding.unsupported_claims.map((claim, index) => (
            <button key={`${claim.span_id}-${index}`} onClick={() => onSelectSpan(claim.span_id)}>
              <strong>{claim.claim}</strong>
              <span>{claim.reason ?? claim.span_name}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="groundingOk">No unsupported claims detected.</p>
      )}
    </div>
  );
}

function MemoryPanel({ summary, onSelectSpan }: { summary: MemorySummary; onSelectSpan: (spanId: string) => void }) {
  if (summary.readCount + summary.writeCount === 0) {
    return null;
  }

  return (
    <div className={summary.warnings.length > 0 ? "memoryPanel warning" : "memoryPanel"}>
      <div className="memoryHeader">
        <strong>Memory analysis</strong>
        <span>{summary.warnings.length > 0 ? `${summary.warnings.length} warning` : "Healthy"}</span>
      </div>
      <div className="memoryStats">
        <span>Reads <strong>{summary.readCount}</strong></span>
        <span>Writes <strong>{summary.writeCount}</strong></span>
        <span>Retrieved <strong>{summary.retrievedCount}</strong></span>
        <span>Relevance <strong>{summary.averageRelevance === null ? "-" : summary.averageRelevance.toFixed(2)}</strong></span>
        <span>Used <strong>{summary.usedCount}</strong></span>
        <span>Ignored <strong>{summary.ignoredCount}</strong></span>
      </div>
      {summary.stores.length > 0 ? (
        <div className="memoryStores">
          <small>Stores</small>
          <span>{summary.stores.join(" · ")}</span>
        </div>
      ) : null}
      {summary.warnings.length > 0 ? (
        <div className="memoryWarnings">
          <small>Warnings</small>
          {summary.warnings.map((warning, index) => (
            <button className={warning.tone} key={`${warning.spanId}-${warning.label}-${index}`} onClick={() => onSelectSpan(warning.spanId)}>
              <strong>{warning.label}</strong>
              <span>{warning.detail}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SpanDetail({
  span,
  rawTrace,
  onApprovalAction,
}: {
  span: Span;
  rawTrace: unknown;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const [activeTab, setActiveTab] = useState<"overview" | "span" | "trace">("overview");
  const unsupportedClaims = extractUnsupportedClaims(span.output);
  const approvalStatus = getApprovalStatus(span.span_type, span.span_data);
  const facts = buildSpanFacts(span);
  const modelOutputText = typeof span.span_data.model_output_text === "string" ? span.span_data.model_output_text : null;

  return (
    <div className="spanDetail">
      <div className="spanDetailHeader">
        <div>
          <small>Selected span</small>
          <strong>{span.name}</strong>
        </div>
        <span>{span.span_type}</span>
      </div>

      <div className="spanFacts">
        {facts.map((fact) => (
          <div key={fact.label}>
            <small>{fact.label}</small>
            <strong>{fact.value}</strong>
          </div>
        ))}
      </div>

      <div className="inspectorTabs" role="tablist" aria-label="Span inspector">
        <button className={activeTab === "overview" ? "active" : ""} onClick={() => setActiveTab("overview")}>
          Overview
        </button>
        <button className={activeTab === "span" ? "active" : ""} onClick={() => setActiveTab("span")}>
          Span JSON
        </button>
        <button className={activeTab === "trace" ? "active" : ""} onClick={() => setActiveTab("trace")}>
          Raw trace
        </button>
      </div>

      {activeTab === "overview" ? (
        <>
          {unsupportedClaims.length > 0 ? (
            <div className="claimAlert">
              <strong>Unsupported claims</strong>
              {unsupportedClaims.map((claim, index) => (
                <p key={`${claim.claim}-${index}`}>
                  {claim.claim}
                  {claim.reason ? <span>{claim.reason}</span> : null}
                </p>
              ))}
            </div>
          ) : null}

          {approvalStatus ? <ApprovalNotice spanId={span.span_id} status={approvalStatus} onApprovalAction={onApprovalAction} /> : null}

          {modelOutputText ? <JsonBlock label="Model output" value={modelOutputText} /> : null}
          <JsonBlock label="Input" value={span.input} />
          <JsonBlock label="Output" value={span.output} />
          <JsonBlock label="Metadata" value={span.span_data} />
          {span.error ? <JsonBlock label="Error" value={span.error} /> : null}
        </>
      ) : null}

      {activeTab === "span" ? <JsonBlock label="Normalized span" value={span} /> : null}
      {activeTab === "trace" ? <JsonBlock label="Original trace payload" value={rawTrace} /> : null}
    </div>
  );
}

function ApprovalNotice({
  spanId,
  status,
  onApprovalAction,
}: {
  spanId: string;
  status: ApprovalStatus;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  return (
    <div className="approvalNotice">
      <strong>Approval required</strong>
      <dl>
        <div>
          <dt>Status</dt>
          <dd>{status.approvalStatus}</dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd>{status.riskLevel ?? "-"}</dd>
        </div>
        <div>
          <dt>Scope</dt>
          <dd>{status.permissionScope ?? "-"}</dd>
        </div>
      </dl>
      <ApprovalActions spanId={spanId} status={status} onApprovalAction={onApprovalAction} />
      <small>Approval state is stored on the approval span.</small>
    </div>
  );
}

function ApprovalActions({
  spanId,
  status,
  onApprovalAction,
}: {
  spanId: string;
  status: ApprovalStatus;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const isApproved = status.approvalStatus === "approved";
  const isRejected = status.approvalStatus === "rejected";

  return (
    <div className="approvalActions">
      <button className="approveButton" disabled={isApproved} onClick={() => void onApprovalAction(spanId, "approve")}>
        <UserCheck size={15} />
        Approve
      </button>
      <button className="rejectButton" disabled={isRejected} onClick={() => void onApprovalAction(spanId, "reject")}>
        <AlertCircle size={15} />
        Reject
      </button>
      <button className="revertButton" disabled={!status.isResolved} onClick={() => void onApprovalAction(spanId, "revert")}>
        <RotateCcw size={15} />
        Revert
      </button>
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  const displayValue = value === null || value === undefined ? "-" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="jsonBlock">
      <small>{label}</small>
      <pre>{displayValue}</pre>
    </div>
  );
}

function Insight({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="insight">
      <div className="insightIcon">{icon}</div>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

type SpanNode = {
  span: Span;
  children: SpanNode[];
};

function buildSpanTree(spans: Span[]): SpanNode[] {
  const nodes = new Map<string, SpanNode>();
  for (const span of spans) {
    nodes.set(span.span_id, { span, children: [] });
  }

  const roots: SpanNode[] = [];
  for (const span of spans) {
    const node = nodes.get(span.span_id);
    if (!node) continue;
    if (span.parent_id && nodes.has(span.parent_id)) {
      nodes.get(span.parent_id)?.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

function spanIcon(spanType: string) {
  if (spanType === "agent") return <Bot size={15} />;
  if (spanType === "function_tool") return <Wrench size={15} />;
  if (spanType === "guardrail") return <ShieldCheck size={15} />;
  if (spanType === "handoff") return <ArrowRight size={15} />;
  if (spanType === "approval") return <UserCheck size={15} />;
  if (spanType === "memory_read" || spanType === "memory_write") return <Braces size={15} />;
  return <Activity size={15} />;
}

type ApprovalAction = "approve" | "reject" | "revert";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

function filterQuery(filters: TraceFilters, activeChatSessionId: string | null): string {
  const params = new URLSearchParams();
  params.set("limit", String(TRACE_PAGE_SIZE));
  params.set("offset", String(filters.offset));
  if (filters.workflowName) params.set("workflow_name", filters.workflowName);
  if (filters.status) params.set("status", filters.status);
  if (filters.sourceFormat) params.set("source_format", filters.sourceFormat);
  if (filters.sourceKind) params.set("source_kind", filters.sourceKind);
  if (filters.errorStatus) params.set("has_errors", filters.errorStatus);
  if (filters.approvalStatus) params.set("approval_status", filters.approvalStatus);
  if (filters.groundingStatus) params.set("grounding_status", filters.groundingStatus);
  if (filters.currentChatOnly && activeChatSessionId) params.set("chat_session_id", activeChatSessionId);
  const startedAfter = startedAfterForRange(filters.timeRange);
  if (startedAfter) params.set("started_after", startedAfter);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function traceSummaryQuery(traceIds: string[]): string {
  const params = new URLSearchParams();
  params.set("trace_ids", traceIds.join(","));
  return `?${params.toString()}`;
}

function emptyFilters(): TraceFilters {
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

function activeFilterCount(filters: TraceFilters): number {
  return [
    filters.workflowName,
    filters.status,
    filters.sourceFormat,
    filters.sourceKind,
    filters.errorStatus,
    filters.approvalStatus,
    filters.groundingStatus,
    filters.timeRange,
    filters.currentChatOnly ? "current-chat" : "",
  ].filter(Boolean).length;
}

function latestTraceFromMessages(messages: ChatMessage[]): string | null {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const traceId = messages[index].trace_id;
    if (traceId) return traceId;
  }
  return null;
}

function replacePendingChatMessage(
  messages: ChatMessage[],
  pendingMessageId: string,
  userMessage: ChatMessage,
  assistantMessage: ChatMessage,
): ChatMessage[] {
  return [...messages.filter((message) => message.message_id !== pendingMessageId), userMessage, assistantMessage];
}

function uniqueTraceIds(messages: ChatMessage[]): string[] {
  return Array.from(new Set(messages.map((message) => message.trace_id).filter((traceId): traceId is string => Boolean(traceId))));
}

function summaryMap(summaries: TraceSummary[]): Record<string, TraceSummary> {
  return Object.fromEntries(summaries.map((summary) => [summary.trace_id, summary]));
}

function parseServerEvent(event: Event): ServerEvent | null {
  if (!("data" in event) || typeof event.data !== "string") return null;
  try {
    return JSON.parse(event.data) as ServerEvent;
  } catch {
    return null;
  }
}

function upsertChatSession(sessions: ChatSession[], session: ChatSession): ChatSession[] {
  const next = sessions.filter((item) => item.session_id !== session.session_id);
  return [session, ...next];
}

function executionStatus(status: string): string {
  if (status === "grounded" || status === "recovered") return "passed";
  return status;
}

function startedAfterForRange(value: string): string | null {
  const minutesByRange: Record<string, number> = {
    "15m": 15,
    "1h": 60,
    "24h": 1440,
  };
  const minutes = minutesByRange[value];
  if (!minutes) return null;
  return new Date(Date.now() - minutes * 60 * 1000).toISOString();
}

function formatRelevance(value: number | null): string {
  return value === null ? "-" : value.toFixed(2);
}

function formatShortTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function apiPostJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    throw new Error(await responseErrorMessage(response));
  }
  return response.json() as Promise<T>;
}

async function responseErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.clone().json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.trim()) {
      return payload.detail;
    }
  } catch {
    // Fall back to the HTTP status when the backend did not return JSON.
  }
  return `Request failed: ${response.status} ${response.statusText}`;
}

createRoot(document.getElementById("root")!).render(<App />);
