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
  status: "ready" | "missing_runs" | "missing_deterministic" | "missing_llm";
  deterministic_run: EvalRunSummary | null;
  llm_run: EvalRunSummary | null;
  pass_rate_delta: number | null;
  llm_regressions: EvalComparisonCase[];
  llm_improvements: EvalComparisonCase[];
  both_failed: EvalComparisonCase[];
};

export type EvalCheckCategory = "Routing" | "Policy" | "Memory" | "Response" | "Reliability";

export type EvalCategorySummary = {
  category: EvalCheckCategory;
  failed: number;
  total: number;
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

export function evalModeLabel(mode: EvalExecutionMode): string {
  return mode === "llm" ? "LLM-backed" : "Deterministic";
}

export function listEvalRuns(transport: EvalSuiteGetTransport): Promise<EvalRunListResponse> {
  return transport("/eval-runs?limit=5");
}

export function getSupportTriageEvalComparison(transport: EvalSuiteGetTransport): Promise<EvalComparison> {
  return transport("/eval-runs/support-triage/comparison");
}

export function getEvalRun(transport: EvalSuiteGetTransport, runId: string): Promise<EvalSuiteRun> {
  return transport(`/eval-runs/${runId}`);
}

export function evalPassRateLabel(passRate: number): string {
  return `${Math.round(passRate * 100)}%`;
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
  return run.failed === 0 ? "Passing" : "Needs review";
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
  if ((comparison.llm_regressions?.length ?? 0) > 0) return "LLM drift detected";
  return "Aligned";
}

export function evalCheckCategory(checkName: string): EvalCheckCategory {
  if (checkName === "issue_type" || checkName === "action_type") return "Routing";
  if (checkName === "policy_id" || checkName === "approval_required" || checkName === "grounding_status") return "Policy";
  if (checkName === "memory_warning_count") return "Memory";
  if (checkName.startsWith("response_contains:") || checkName.startsWith("response_excludes:")) return "Response";
  return "Reliability";
}

export function evalCategorySummaries(run: EvalSuiteRun | null): EvalCategorySummary[] {
  const categories: EvalCheckCategory[] = ["Routing", "Policy", "Memory", "Response", "Reliability"];
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
  const categories: EvalCheckCategory[] = ["Routing", "Policy", "Memory", "Response", "Reliability"];
  return categories
    .map((category) => ({
      category,
      checks: result.checks.filter((check) => !check.passed && evalCheckCategory(check.name) === category),
    }))
    .filter((group) => group.checks.length > 0);
}
