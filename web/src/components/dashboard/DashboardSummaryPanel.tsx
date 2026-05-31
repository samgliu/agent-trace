import {
  AlertCircle,
  Braces,
  CircleDollarSign,
  Clock3,
  GitBranch,
  GitPullRequestArrow,
  ShieldCheck,
  UserCheck,
} from "lucide-react";
import { SummaryFact } from "../common/SummaryFact";
import type { DashboardSummary } from "../../types";
import { formatCost, formatDuration, formatRelevance } from "../../utils/format";
import { sourceKindLabel, sourceLabel } from "../../utils/source";

export function DashboardSummaryPanel({ summary }: { summary: DashboardSummary }) {
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
        <SummaryFact icon={<GitPullRequestArrow size={16} />} label="Escalated runs" value={String(summary.escalation_count)} />
        <SummaryFact icon={<ShieldCheck size={16} />} label="Risk reviews" value={String(summary.escalation_risk_review_count)} />
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
