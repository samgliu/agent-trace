import { getApprovalStatus } from "./approval";

export type SummarySpan = {
  span_type: string;
  span_data: Record<string, unknown>;
};

export type SummaryMetrics = {
  span_count: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
};

export type SummaryGrounding = {
  status: string;
  unsupported_claim_count: number;
  recovered: boolean;
};

export type TraceSummaryInput = {
  status: string;
  duration_ms: number | null;
  spans: SummarySpan[];
};

export type ApprovalCounts = {
  total: number;
  pending: number;
  approved: number;
  rejected: number;
};

export function countApprovals(spans: SummarySpan[]): ApprovalCounts {
  return spans.reduce(
    (counts, span) => {
      const approval = getApprovalStatus(span.span_type, span.span_data);
      if (!approval) return counts;

      counts.total += 1;
      if (approval.isPending) counts.pending += 1;
      if (approval.approvalStatus === "approved") counts.approved += 1;
      if (approval.approvalStatus === "rejected") counts.rejected += 1;
      return counts;
    },
    { total: 0, pending: 0, approved: 0, rejected: 0 },
  );
}

export function buildExecutiveSummary(
  trace: TraceSummaryInput,
  metrics: SummaryMetrics,
  grounding: SummaryGrounding,
): string {
  const approvals = countApprovals(trace.spans);
  if (approvals.pending > 0) {
    return `${approvals.pending} approval waiting before this workflow can safely continue.`;
  }
  if (grounding.recovered) {
    return `${grounding.unsupported_claim_count} unsupported claim recovered before final response.`;
  }
  if (grounding.unsupported_claim_count > 0) {
    return `${grounding.unsupported_claim_count} unsupported claim needs investigation.`;
  }
  return `${metrics.span_count} spans completed with no open approval or grounding issue.`;
}

