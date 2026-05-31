export type TraceSummary = {
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
  escalation_count: number;
  escalation_human_review_count: number;
  escalation_risk_review_count: number;
  escalation_technical_recovery_count: number;
  escalation_types: string[];
  escalation_next_owners: string[];
  metadata?: Record<string, unknown>;
};

export type TraceListResponse = {
  items: TraceSummary[];
  limit: number;
  offset: number;
  total: number;
};

export type Span = {
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

export type TraceDetail = TraceSummary & {
  metadata: Record<string, unknown>;
  spans: Span[];
};

export type SpanSummary = {
  name: string;
  span_type: string;
  duration_ms: number | null;
  estimated_cost: number | null;
};

export type Metrics = {
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

export type GroundingClaim = {
  claim: string;
  reason?: string;
  evidence?: string;
  span_id: string;
  span_name: string;
};

export type GroundingSummary = {
  status: string;
  final_grounded: boolean | null;
  recovered: boolean;
  unsupported_claim_count: number;
  supported_claim_count: number;
  validation_span_count: number;
  unsupported_claims: GroundingClaim[];
  supported_claims: GroundingClaim[];
};

export type DashboardSummary = {
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
  escalation_count: number;
  escalation_human_review_count: number;
  escalation_risk_review_count: number;
  escalation_technical_recovery_count: number;
  escalation_type_counts: Record<string, number>;
  escalation_owner_counts: Record<string, number>;
};

export type TraceFilters = {
  status: string;
  workflowName: string;
  sourceFormat: string;
  sourceKind: string;
  errorStatus: string;
  escalationStatus: string;
  escalationType: string;
  escalationOwner: string;
  approvalStatus: string;
  groundingStatus: string;
  timeRange: string;
  currentChatOnly: boolean;
  offset: number;
};

export type LoadState =
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

export type EvalRunStatus = { status: "idle" } | { status: "running" } | { status: "error"; message: string };

export type ChatStatus = { status: "idle" } | { status: "submitting" } | { status: "error"; message: string };

export type ChatInput = {
  customerEmail: string;
  message: string;
  llmProvider: LLMProvider;
};

export type LiveWorkflowInput = ChatInput;

export type ApprovalAction = "approve" | "reject" | "revert";
import type { LLMProvider } from "./utils/chat";
