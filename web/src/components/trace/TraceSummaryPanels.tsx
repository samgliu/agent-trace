import type React from "react";
import {
  AlertCircle,
  Braces,
  CircleDollarSign,
  Clock3,
  GitBranch,
  ShieldCheck,
  UserCheck,
  Wrench,
} from "lucide-react";
import { SummaryFact } from "../common/SummaryFact";
import type { GroundingSummary, Metrics, TraceDetail } from "../../types";
import { formatCost, formatDuration, formatTokens } from "../../utils/format";
import { sourceKindLabel, sourceLabel, stringMetadata } from "../../utils/source";
import { buildExecutiveSummary, countApprovals } from "../../utils/summary";

export function TraceHeader({ trace, executionStatus }: { trace: TraceDetail; executionStatus: string }) {
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

export function MetricGrid({ metrics, grounding }: { metrics: Metrics; grounding: GroundingSummary }) {
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

export function ExecutiveSummaryPanel({
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
