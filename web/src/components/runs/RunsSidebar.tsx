import { AlertCircle } from "lucide-react";
import type { TraceFilters, TraceSummary } from "../../types";
import { chatTurnBadges, isChatTrace, isLatestChatTrace } from "../../utils/chatTrace";
import { hasNextPage, nextOffset, pageRange, previousOffset, TRACE_PAGE_SIZE } from "../../utils/pagination";
import { sourceKindLabel, sourceLabel } from "../../utils/source";
import { executionStatus, groundingTone, statusTone } from "../../utils/status";
import { activeFilterCount, emptyFilters } from "../../utils/traceFilters";

export function RunsSidebar({
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

export function EmptyRunsState({ onClearFilters }: { onClearFilters: () => void }) {
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
  return (
    <div className="traceBadges">
      {chatTurnBadges(trace, { isChatTurn, isLatest: isLatestChatTrace }).map((badge) => (
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
