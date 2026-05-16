export type EvalCheck = {
  name: string;
  expected: unknown;
  actual: unknown;
  passed: boolean;
};

export type EvalCaseResult = {
  case_id: string;
  name: string;
  trace_id: string;
  passed: boolean;
  score: number;
  checks: EvalCheck[];
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

export function evalStatusLabel(run: EvalSuiteRun | null): string {
  if (run === null) {
    return "Not run";
  }
  if (run.status === "running") {
    return "Running";
  }
  return run.failed === 0 ? "Passing" : "Needs review";
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
