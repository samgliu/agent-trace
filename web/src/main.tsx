import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertCircle,
  ArrowRight,
  Bot,
  Braces,
  CircleDollarSign,
  Clock3,
  GitBranch,
  Network,
  RotateCcw,
  ShieldCheck,
  UserCheck,
  Wrench
} from "lucide-react";
import "./styles.css";
import { getApprovalStatus, type ApprovalStatus } from "./utils/approval";
import { extractUnsupportedClaims } from "./utils/claims";
import { formatCost, formatDuration, formatTokens } from "./utils/format";
import { buildExecutiveSummary, countApprovals } from "./utils/summary";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

type TraceSummary = {
  trace_id: string;
  workflow_name: string;
  group_id: string | null;
  status: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  span_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  approval_total_count: number;
  approval_pending_count: number;
  approval_approved_count: number;
  approval_rejected_count: number;
  grounding_status: string;
  unsupported_claim_count: number;
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
  spans: Span[];
};

type Metrics = {
  span_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
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
  approval_pending_count: number;
  approval_rejected_count: number;
  unsupported_claim_count: number;
  average_duration_ms: number | null;
  p95_duration_ms: number | null;
  estimated_cost: number;
  input_tokens: number;
  output_tokens: number;
};

type TraceFilters = {
  status: string;
  approvalStatus: string;
  groundingStatus: string;
};

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | {
      status: "empty";
      traces: TraceSummary[];
      traceTotal: number;
      dashboard: DashboardSummary;
    }
  | {
      status: "ready";
      traces: TraceSummary[];
      traceTotal: number;
      dashboard: DashboardSummary;
      selectedTrace: TraceDetail;
      metrics: Metrics;
      grounding: GroundingSummary;
    };

function App() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [filters, setFilters] = useState<TraceFilters>({ status: "", approvalStatus: "", groundingStatus: "" });
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [traceList, dashboard] = await Promise.all([
          fetchJson<TraceListResponse>(`/traces${filterQuery(filters)}`),
          fetchJson<DashboardSummary>("/dashboard/summary"),
        ]);
        const traces = traceList.items;
        const traceId = traces.some((trace) => trace.trace_id === selectedTraceId)
          ? selectedTraceId
          : traces[0]?.trace_id;
        if (!traceId) {
          if (!cancelled) {
            setSelectedTraceId(null);
            setSelectedSpanId(null);
            setState({ status: "empty", traces, traceTotal: traceList.total, dashboard });
          }
          return;
        }
        const [selectedTrace, metrics, grounding] = await Promise.all([
          fetchJson<TraceDetail>(`/traces/${traceId}`),
          fetchJson<Metrics>(`/traces/${traceId}/metrics`),
          fetchJson<GroundingSummary>(`/traces/${traceId}/grounding`),
        ]);
        if (!cancelled) {
          setSelectedTraceId(traceId);
          setSelectedSpanId(selectedTrace.spans[0]?.span_id ?? null);
          setState({
            status: "ready",
            traces,
            traceTotal: traceList.total,
            dashboard,
            selectedTrace,
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
  }, [selectedTraceId, filters, refreshKey]);

  async function updateApproval(spanId: string, action: ApprovalAction) {
    if (state.status !== "ready") {
      return;
    }
    await postJson(`/traces/${state.selectedTrace.trace_id}/approvals/${spanId}/${action}`);
    setRefreshKey((value) => value + 1);
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
            onFiltersChange={setFilters}
            onSelectTrace={setSelectedTraceId}
            onClearSelection={() => setSelectedSpanId(null)}
          />
          <main className="main">
            <DashboardSummaryPanel summary={state.dashboard} />
            <EmptyRunsState onClearFilters={() => setFilters({ status: "", approvalStatus: "", groundingStatus: "" })} />
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
          onFiltersChange={setFilters}
          onSelectTrace={setSelectedTraceId}
          onClearSelection={() => setSelectedSpanId(null)}
        />

        <main className="main">
          <DashboardSummaryPanel summary={state.dashboard} />
          <TraceHeader trace={state.selectedTrace} />
          <ExecutiveSummaryPanel trace={state.selectedTrace} metrics={state.metrics} grounding={state.grounding} />
          <MetricGrid metrics={state.metrics} grounding={state.grounding} />
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
              selectedSpanId={selectedSpanId}
              onSelectSpan={setSelectedSpanId}
              onApprovalAction={updateApproval}
            />
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
  onFiltersChange,
  onSelectTrace,
  onClearSelection,
}: {
  traces: TraceSummary[];
  traceTotal: number;
  selectedTraceId: string | null;
  filters: TraceFilters;
  onFiltersChange: (filters: TraceFilters) => void;
  onSelectTrace: (traceId: string) => void;
  onClearSelection: () => void;
}) {
  return (
    <aside className="sidebar">
      <div className="sidebarHeader">Runs Inbox</div>
      <TraceFiltersPanel filters={filters} onChange={onFiltersChange} />
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
            <TraceBadges trace={trace} />
          </button>
        ))}
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

function TraceHeader({ trace }: { trace: TraceDetail }) {
  return (
    <section className="traceHeader">
      <div>
        <div className="eyebrow">{trace.trace_id}</div>
        <h2>{trace.workflow_name}</h2>
      </div>
      <div className="traceMeta">
        <span>{trace.status}</span>
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
    <section className="fleetSummary">
      <SummaryFact icon={<GitBranch size={16} />} label="Runs" value={String(summary.total_runs)} />
      <SummaryFact icon={<UserCheck size={16} />} label="Approvals waiting" value={String(summary.approval_pending_count)} />
      <SummaryFact icon={<ShieldCheck size={16} />} label="Grounding issues" value={String(summary.unsupported_claim_count)} />
      <SummaryFact icon={<Clock3 size={16} />} label="Avg duration" value={formatDuration(summary.average_duration_ms)} />
      <SummaryFact icon={<Clock3 size={16} />} label="P95 duration" value={formatDuration(summary.p95_duration_ms)} />
      <SummaryFact icon={<CircleDollarSign size={16} />} label="Total cost" value={formatCost(summary.estimated_cost)} />
    </section>
  );
}

function TraceFiltersPanel({
  filters,
  onChange,
}: {
  filters: TraceFilters;
  onChange: (filters: TraceFilters) => void;
}) {
  return (
    <div className="traceFilters">
      <label>
        <span>Status</span>
        <select value={filters.status} onChange={(event) => onChange({ ...filters, status: event.target.value })}>
          <option value="">Any</option>
          <option value="passed">Passed</option>
          <option value="failed">Failed</option>
          <option value="running">Running</option>
        </select>
      </label>
      <label>
        <span>Approval</span>
        <select
          value={filters.approvalStatus}
          onChange={(event) => onChange({ ...filters, approvalStatus: event.target.value })}
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
          onChange={(event) => onChange({ ...filters, groundingStatus: event.target.value })}
        >
          <option value="">Any</option>
          <option value="grounded">Grounded</option>
          <option value="recovered">Recovered</option>
          <option value="failed">Failed</option>
        </select>
      </label>
      <button type="button" onClick={() => onChange({ status: "", approvalStatus: "", groundingStatus: "" })}>
        Clear
      </button>
    </div>
  );
}

function TraceBadges({ trace }: { trace: TraceSummary }) {
  return (
    <div className="traceBadges">
      <span className={`chip status ${statusTone(trace.status)}`}>Status: {trace.status}</span>
      {trace.grounding_status !== trace.status ? (
        <span className={`chip grounding ${groundingTone(trace.grounding_status)}`}>Grounding: {trace.grounding_status}</span>
      ) : null}
      {trace.approval_pending_count > 0 ? <strong className="chip warning">Needs approval</strong> : null}
      {trace.approval_rejected_count > 0 ? <strong className="chip danger">Rejected</strong> : null}
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
  const rowClassName = [
    "spanRow",
    span.span_id === selectedSpanId ? "selected" : "",
    approvalStatus?.isPending ? "approvalPending" : "",
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

function AnalysisPanel({
  metrics,
  grounding,
  spans,
  selectedSpanId,
  onSelectSpan,
  onApprovalAction,
}: {
  metrics: Metrics;
  grounding: GroundingSummary;
  spans: Span[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const mcpSpans = spans.filter((span) => span.span_data.tool_protocol === "mcp");
  const guardrails = spans.filter((span) => span.span_type === "guardrail" || span.span_type === "validation");
  const approvals = spans.filter((span) => span.span_type === "approval");
  const pendingApprovals = approvals.filter((span) => getApprovalStatus(span.span_type, span.span_data)?.isPending);
  const handoffs = spans.filter((span) => span.span_type === "handoff");
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
        <Insight icon={<ShieldCheck size={16} />} label="Guardrails" value={`${guardrails.length} validation span`} />
        <Insight icon={<UserCheck size={16} />} label="Approvals" value={`${pendingApprovals.length} waiting · ${approvals.length} total`} />
        <Insight icon={<CircleDollarSign size={16} />} label="Most expensive" value={metrics.most_expensive_span?.name ?? "-"} />
      </div>
      <ApprovalQueue approvals={approvals} onSelectSpan={onSelectSpan} onApprovalAction={onApprovalAction} />
      <GroundingPanel grounding={grounding} onSelectSpan={onSelectSpan} />
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
      {selectedSpan ? <SpanDetail span={selectedSpan} onApprovalAction={onApprovalAction} /> : null}
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
    <div className="approvalQueue">
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
    </div>
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

function SpanDetail({
  span,
  onApprovalAction,
}: {
  span: Span;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const unsupportedClaims = extractUnsupportedClaims(span.output);
  const approvalStatus = getApprovalStatus(span.span_type, span.span_data);

  return (
    <div className="spanDetail">
      <div className="spanDetailHeader">
        <div>
          <small>Selected span</small>
          <strong>{span.name}</strong>
        </div>
        <span>{span.span_type}</span>
      </div>

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

      <JsonBlock label="Input" value={span.input} />
      <JsonBlock label="Output" value={span.output} />
      <JsonBlock label="Metadata" value={span.span_data} />
      {span.error ? <JsonBlock label="Error" value={span.error} /> : null}
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
  return (
    <div className="jsonBlock">
      <small>{label}</small>
      <pre>{value === null || value === undefined ? "-" : JSON.stringify(value, null, 2)}</pre>
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
  return <Activity size={15} />;
}

type ApprovalAction = "approve" | "reject" | "revert";

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function filterQuery(filters: TraceFilters): string {
  const params = new URLSearchParams();
  params.set("limit", "50");
  if (filters.status) params.set("status", filters.status);
  if (filters.approvalStatus) params.set("approval_status", filters.approvalStatus);
  if (filters.groundingStatus) params.set("grounding_status", filters.groundingStatus);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function postJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

createRoot(document.getElementById("root")!).render(<App />);
