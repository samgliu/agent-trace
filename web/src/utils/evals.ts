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
  status: string;
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  created_at: string;
  results: EvalCaseResult[];
};

export type EvalRunSummary = Omit<EvalSuiteRun, "results">;

export type EvalRunListResponse = {
  items: EvalRunSummary[];
  limit: number;
  offset: number;
  total: number;
};

export type EvalSuiteTransport = <T>(path: string, body?: unknown) => Promise<T>;
export type EvalSuiteGetTransport = <T>(path: string) => Promise<T>;

export function runSupportTriageEvalSuite(transport: EvalSuiteTransport): Promise<EvalSuiteRun> {
  return transport("/evals/support-triage/run");
}

export function listEvalRuns(transport: EvalSuiteGetTransport): Promise<EvalRunListResponse> {
  return transport("/eval-runs?limit=5");
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
  return run.failed === 0 ? "Passing" : "Needs review";
}
