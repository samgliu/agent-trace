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
  suite_id: string;
  name: string;
  total: number;
  passed: number;
  failed: number;
  pass_rate: number;
  results: EvalCaseResult[];
};

export type EvalSuiteTransport = <T>(path: string, body?: unknown) => Promise<T>;

export function runSupportTriageEvalSuite(transport: EvalSuiteTransport): Promise<EvalSuiteRun> {
  return transport("/evals/support-triage/run");
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
