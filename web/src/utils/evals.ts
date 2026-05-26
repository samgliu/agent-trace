export type EvalCheck = {
  name: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
};

export type EvalModelAttempt = {
  model?: string | null;
  status?: string | null;
  error?: string | null;
};

export type EvalModelEvent = {
  span_name: string;
  model?: string | null;
  fallback_used: boolean;
  attempts?: EvalModelAttempt[];
};

export type EvalCaseResult = {
  case_id: string;
  name: string;
  trace_id: string;
  passed: boolean;
  score: number;
  checks: EvalCheck[];
  model_events?: EvalModelEvent[];
};

export type EvalSuiteRun = {
  run_id: string;
  suite_id: string;
  name: string;
  execution_mode: EvalExecutionMode;
  model_provider: string;
  model_name: string;
  status: string;
  error?: string | null;
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  created_at: string;
  results: EvalCaseResult[];
};

export type EvalRunSummary = Omit<EvalSuiteRun, "results">;

export type EvalExecutionMode = "deterministic" | "llm";

export type EvalRunListResponse = {
  items: EvalRunSummary[];
  limit: number;
  offset: number;
  total: number;
};

export type EvalComparisonCase = {
  case_id: string;
  name: string;
  deterministic_trace_id: string;
  llm_trace_id: string;
  deterministic_score: number;
  llm_score: number;
  failed_checks: EvalCheck[];
};

export type EvalComparison = {
  suite_id: string;
  status: "ready" | "missing_runs" | "missing_deterministic" | "missing_llm" | "degraded_llm";
  deterministic_run: EvalRunSummary | null;
  llm_run: EvalRunSummary | null;
  pass_rate_delta: number | null;
  llm_regressions: EvalComparisonCase[];
  llm_improvements: EvalComparisonCase[];
  both_failed: EvalComparisonCase[];
};

export type EvalCheckCategory = "Routing" | "Evidence" | "Governance" | "Response" | "Memory" | "Reliability" | "Other";

export type EvalCategorySummary = {
  category: EvalCheckCategory;
  failed: number;
  total: number;
};

export type EvalTrendPoint = {
  runId: string;
  label: string;
  mode: EvalExecutionMode;
  status: EvalRunSummary["status"];
  passRate: number;
  passed: number;
  failed: number;
  total: number;
  model: string;
  createdAt: string;
};

export type EvalTrendSeries = Record<EvalExecutionMode, EvalTrendPoint[]>;

export type EvalFailureTrendPoint = {
  run_id: string;
  label: string;
  created_at: string;
  execution_mode: EvalExecutionMode;
  model_provider: string;
  model_name: string;
  status: string;
  pass_rate: number;
  failed_cases: number;
  failed_checks: number;
  categories: Record<EvalCheckCategory, number>;
};

export type EvalFailureTrends = {
  suite_id: string;
  limit: number;
  execution_mode: EvalExecutionMode | null;
  categories: EvalCheckCategory[];
  totals: Record<EvalCheckCategory, number>;
  points: EvalFailureTrendPoint[];
};

export type EvalProgress = {
  completed: number;
  total: number;
  percent: number;
  label: string;
};

export type EvalFailedCheckGroup = {
  category: EvalCheckCategory;
  checks: EvalCheck[];
};

export type EvalImprovementCase = {
  case_id: string;
  trace_id: string;
  check: string;
  expected: unknown;
  actual: unknown;
};

export type EvalImprovementItem = {
  category: EvalCheckCategory;
  failed_check_count: number;
  owner_area: string;
  recommended_action: string;
  suggested_files: string[];
  cases: EvalImprovementCase[];
};

export type EvalSuiteTransport = <T>(path: string, body?: unknown) => Promise<T>;
export type EvalSuiteGetTransport = <T>(path: string) => Promise<T>;

export function runSupportTriageEvalSuite(
  transport: EvalSuiteTransport,
  mode: EvalExecutionMode = "deterministic",
): Promise<EvalSuiteRun> {
  return transport(`/evals/support-triage/run?mode=${mode}`);
}

export function startSupportTriageEvalSuite(
  transport: EvalSuiteTransport,
  mode: EvalExecutionMode = "llm",
): Promise<EvalSuiteRun> {
  return transport(`/evals/support-triage/run/async?mode=${mode}`);
}

export function resumeEvalRun(transport: EvalSuiteTransport, runId: string): Promise<EvalSuiteRun> {
  return transport(`/eval-runs/${runId}/resume`);
}

export function evalModeLabel(mode: EvalExecutionMode): string {
  return mode === "llm" ? "LLM-backed" : "Deterministic";
}

export function listEvalRuns(transport: EvalSuiteGetTransport): Promise<EvalRunListResponse> {
  return transport("/eval-runs?limit=12");
}

export function getSupportTriageEvalComparison(transport: EvalSuiteGetTransport): Promise<EvalComparison> {
  return transport("/eval-runs/support-triage/comparison");
}

export function getSupportTriageEvalFailureTrends(
  transport: EvalSuiteGetTransport,
  mode: EvalExecutionMode = "llm",
): Promise<EvalFailureTrends> {
  return transport(`/eval-runs/support-triage/failure-trends?mode=${mode}&limit=20`);
}

export function getEvalRun(transport: EvalSuiteGetTransport, runId: string): Promise<EvalSuiteRun> {
  return transport(`/eval-runs/${runId}`);
}

export function evalPassRateLabel(passRate: number): string {
  return `${Math.round(passRate * 100)}%`;
}

export function buildEvalTrendPoints(history: EvalRunSummary[]): EvalTrendPoint[] {
  return [...history].reverse().filter((run) => !evalRunHasProviderIssue(run)).map((run, index) => ({
    runId: run.run_id,
    label: `Run ${index + 1}`,
    mode: run.execution_mode,
    status: run.status,
    passRate: Math.round(run.pass_rate * 100),
    passed: run.passed,
    failed: run.failed,
    total: run.total,
    model: `${run.model_provider}/${run.model_name}`,
    createdAt: run.created_at,
  }));
}

export function buildEvalTrendSeries(history: EvalRunSummary[]): EvalTrendSeries {
  const points = buildEvalTrendPoints(history);
  return {
    deterministic: points.filter((point) => point.mode === "deterministic"),
    llm: points.filter((point) => point.mode === "llm"),
  };
}

export function failedEvalCases(run: EvalSuiteRun | null): EvalCaseResult[] {
  return run?.results.filter((result) => !result.passed) ?? [];
}

export function failedEvalChecks(result: EvalCaseResult): EvalCheck[] {
  return result.checks.filter((check) => !check.passed);
}

export function evalModelSummary(result: EvalCaseResult): EvalModelEvent | null {
  const events = result.model_events ?? [];
  return events.find((event) => event.fallback_used) ?? events.find((event) => Boolean(event.model)) ?? null;
}

export function formatEvalValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.length > 0 ? value.map(formatEvalValue).join(", ") : "[]";
  }
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function evalStatusLabel(run: EvalSuiteRun | null): string {
  if (run === null) {
    return "Not run";
  }
  if (run.status === "running") {
    return "Running";
  }
  if (run.status === "degraded" || evalRunHasProviderIssue(run)) {
    return "Provider degraded";
  }
  return run.failed === 0 ? "Passing" : "Needs review";
}

export function evalRunHasProviderIssue(run: EvalSuiteRun | EvalRunSummary | null): boolean {
  if (!run) return false;
  const error = run.error?.toLowerCase() ?? "";
  return (
    run.status === "degraded" ||
    error.includes("llm provider request failed") ||
    error.includes("http 429") ||
    error.includes("http 500") ||
    error.includes("http 502") ||
    error.includes("http 503") ||
    error.includes("http 504") ||
    error.includes("http 529") ||
    error.includes("resource_exhausted") ||
    error.includes("unavailable") ||
    error.includes("quota exceeded") ||
    error.includes("rate limit") ||
    error.includes("high demand") ||
    error.includes("timed out") ||
    error.includes("timeout") ||
    error.includes("missing api key") ||
    error.includes("not configured")
  );
}

export function evalRunIsActive(run: EvalSuiteRun | null): boolean {
  return run?.status === "running";
}

export function evalProgress(run: EvalSuiteRun | null): EvalProgress {
  const completed = run?.results.length ?? 0;
  const total = run?.total ?? 0;
  const percent = total > 0 ? Math.min(100, Math.round((completed / total) * 100)) : 0;
  const label = total > 0 ? `${completed}/${total} cases complete` : "No eval run";
  return { completed, total, percent, label };
}

export function evalComparisonStatusLabel(comparison: EvalComparison | null): string {
  if (comparison === null) return "Run both modes";
  if (comparison.status === "missing_runs") return "Run both modes";
  if (comparison.status === "missing_deterministic") return "Run deterministic baseline";
  if (comparison.status === "missing_llm") return "Run LLM eval";
  if (comparison.status === "degraded_llm" || evalRunHasProviderIssue(comparison.llm_run)) return "Provider degraded";
  if ((comparison.llm_regressions?.length ?? 0) > 0) return "LLM drift detected";
  return "Aligned";
}

export function evalCheckCategory(checkName: string): EvalCheckCategory {
  if (checkName === "trace_status" || checkName === "error_count") return "Reliability";
  if (checkName === "supervisor_route" || checkName === "issue_type" || checkName === "policy_id" || checkName === "action_type") return "Routing";
  if (checkName.startsWith("tool_used") || checkName.startsWith("evidence_id") || checkName.startsWith("agent_state")) return "Evidence";
  if (checkName === "approval_required" || checkName === "approval_reason") return "Governance";
  if (checkName === "grounding_status" || checkName.startsWith("response_")) return "Response";
  if (checkName.startsWith("memory_")) return "Memory";
  return "Other";
}

export function buildEvalImprovementPlan(run: EvalSuiteRun | null): EvalImprovementItem[] {
  if (!run) return [];
  const items = new Map<EvalCheckCategory, EvalImprovementItem>();

  run.results.forEach((result) => {
    failedEvalChecks(result).forEach((check) => {
      const category = evalCheckCategory(check.name);
      const item = items.get(category) ?? {
        category,
        failed_check_count: 0,
        owner_area: evalImprovementOwnerArea(category),
        recommended_action: evalImprovementRecommendedAction(category),
        suggested_files: evalImprovementSuggestedFiles(category),
        cases: [],
      };
      item.failed_check_count += 1;
      item.cases.push({
        case_id: result.case_id,
        trace_id: result.trace_id,
        check: check.name,
        expected: check.expected,
        actual: check.actual,
      });
      items.set(category, item);
    });
  });

  return Array.from(items.values()).sort(
    (left, right) => right.failed_check_count - left.failed_check_count || left.category.localeCompare(right.category),
  );
}

export function evalImprovementOwnerArea(category: EvalCheckCategory): string {
  return {
    Routing: "multi-agent routing and policy/action planning",
    Evidence: "tool usage, memory state, and evidence propagation",
    Governance: "approval policy and validator guardrails",
    Response: "customer-facing response generation and grounding",
    Memory: "short-term continuity and long-term customer memory",
    Reliability: "tool failure handling and workflow recovery",
    Other: "support-triage workflow",
  }[category];
}

export function evalImprovementRecommendedAction(category: EvalCheckCategory): string {
  return {
    Routing: "Tighten supervisor routing, triage, policy retrieval, or action prompts so the selected workflow path and outcome match the request.",
    Evidence: "Verify required tool calls and carry evidence IDs into agent state, validation, and final action output.",
    Governance: "Align validator approval decisions and approval reasons with policy requirements.",
    Response: "Adjust response instructions so the answer contains required facts and avoids prohibited claims.",
    Memory: "Preserve active issue state across turns and avoid topic drift unless the customer clearly switches topic.",
    Reliability: "Make failure paths explicit and ensure tool errors become recovered or failed traces as expected.",
    Other: "Inspect the failed trace and add the smallest targeted regression check.",
  }[category];
}

export function evalImprovementSuggestedFiles(category: EvalCheckCategory): string[] {
  const common = ["agent_apps/customer_service/runner.py", "agenttrace/evals/support_triage.py"];
  const extra: Partial<Record<EvalCheckCategory, string[]>> = {
    Routing: ["agent_apps/customer_service/routing.py", "agent_apps/customer_service/domain.py"],
    Evidence: ["agent_apps/customer_service/domain.py"],
    Governance: ["agent_apps/customer_service/domain.py"],
    Memory: ["agent_apps/customer_service/domain.py"],
    Reliability: ["agent_apps/customer_service/domain.py", "agenttrace/mcp_tools/tools.py"],
  };
  return [...common, ...(extra[category] ?? [])];
}

export function evalCategorySummaries(run: EvalSuiteRun | null): EvalCategorySummary[] {
  const categories: EvalCheckCategory[] = ["Routing", "Evidence", "Governance", "Response", "Memory", "Reliability"];
  const initial = Object.fromEntries(
    categories.map((category) => [category, { category, failed: 0, total: 0 }]),
  ) as Record<EvalCheckCategory, EvalCategorySummary>;

  run?.results.forEach((result) => {
    result.checks.forEach((check) => {
      const category = evalCheckCategory(check.name);
      initial[category].total += 1;
      if (!check.passed) {
        initial[category].failed += 1;
      }
    });
  });

  return categories.map((category) => initial[category]);
}

export function failedChecksByCategory(result: EvalCaseResult): EvalFailedCheckGroup[] {
  const categories: EvalCheckCategory[] = ["Routing", "Evidence", "Governance", "Response", "Memory", "Reliability", "Other"];
  return categories
    .map((category) => ({
      category,
      checks: result.checks.filter((check) => !check.passed && evalCheckCategory(check.name) === category),
    }))
    .filter((group) => group.checks.length > 0);
}
