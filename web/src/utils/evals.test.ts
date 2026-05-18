import { describe, expect, it } from "vitest";
import {
  evalCategorySummaries,
  evalCheckCategory,
  buildEvalImprovementPlan,
  evalComparisonStatusLabel,
  evalModeLabel,
  evalPassRateLabel,
  evalProgress,
  evalRunHasProviderIssue,
  evalModelSummary,
  evalRunIsActive,
  evalStatusLabel,
  failedEvalCases,
  failedEvalChecks,
  failedChecksByCategory,
  formatEvalValue,
  getEvalRun,
  getSupportTriageEvalComparison,
  listEvalRuns,
  resumeEvalRun,
  runSupportTriageEvalSuite,
  startSupportTriageEvalSuite,
  type EvalRunListResponse,
  type EvalSuiteRun,
} from "./evals";

const sampleRun: EvalSuiteRun = {
  run_id: "eval_1",
  suite_id: "support-triage-core",
  name: "Support triage core",
  execution_mode: "deterministic",
  model_provider: "static",
  model_name: "deterministic",
  status: "failed",
  total: 2,
  passed: 1,
  failed: 1,
  pass_rate: 0.5,
  created_at: "2026-05-08T00:00:00Z",
  results: [
    { case_id: "pass", name: "Pass", trace_id: "trace_pass", passed: true, score: 1, checks: [] },
    { case_id: "fail", name: "Fail", trace_id: "trace_fail", passed: false, score: 0.5, checks: [] },
  ],
};

describe("eval helpers", () => {
  it("runs support triage evals through the API helper", async () => {
    const calls: unknown[] = [];
    const result = await runSupportTriageEvalSuite(async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return sampleRun as T;
    });

    expect(result.suite_id).toBe("support-triage-core");
    expect(calls).toEqual([{ path: "/evals/support-triage/run?mode=deterministic", body: undefined }]);
  });

  it("runs LLM-backed support triage evals through the API helper", async () => {
    const calls: unknown[] = [];
    const result = await runSupportTriageEvalSuite(async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return { ...sampleRun, execution_mode: "llm", model_provider: "gemini", model_name: "gemini-2.5-flash" } as T;
    }, "llm");

    expect(result.execution_mode).toBe("llm");
    expect(calls).toEqual([{ path: "/evals/support-triage/run?mode=llm", body: undefined }]);
  });

  it("starts async LLM-backed support triage evals through the API helper", async () => {
    const calls: unknown[] = [];
    const result = await startSupportTriageEvalSuite(async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return { ...sampleRun, execution_mode: "llm", status: "running", passed: 0, failed: 0, pass_rate: 0 } as T;
    });

    expect(result.status).toBe("running");
    expect(calls).toEqual([{ path: "/evals/support-triage/run/async?mode=llm", body: undefined }]);
  });

  it("resumes an eval run through the API helper", async () => {
    const calls: unknown[] = [];
    const result = await resumeEvalRun(async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return { ...sampleRun, run_id: "eval_resume", status: "running" } as T;
    }, "eval_resume");

    expect(result.status).toBe("running");
    expect(calls).toEqual([{ path: "/eval-runs/eval_resume/resume", body: undefined }]);
  });

  it("lists recent eval runs", async () => {
    const response: EvalRunListResponse = {
      items: [
        {
          run_id: sampleRun.run_id,
          suite_id: sampleRun.suite_id,
          name: sampleRun.name,
          execution_mode: sampleRun.execution_mode,
          model_provider: sampleRun.model_provider,
          model_name: sampleRun.model_name,
          status: sampleRun.status,
          total: sampleRun.total,
          passed: sampleRun.passed,
          failed: sampleRun.failed,
          pass_rate: sampleRun.pass_rate,
          created_at: sampleRun.created_at,
        },
      ],
      limit: 5,
      offset: 0,
      total: 1,
    };

    const result = await listEvalRuns(async <T>(path: string): Promise<T> => {
      expect(path).toBe("/eval-runs?limit=5");
      return response as T;
    });

    expect(result.items[0].run_id).toBe("eval_1");
  });

  it("gets support triage eval comparison", async () => {
    const result = await getSupportTriageEvalComparison(async <T>(path: string): Promise<T> => {
      expect(path).toBe("/eval-runs/support-triage/comparison");
      return {
        suite_id: "support-triage-core",
        status: "ready",
        deterministic_run: sampleRun,
        llm_run: { ...sampleRun, execution_mode: "llm", model_provider: "gemini", model_name: "gemini-test" },
        pass_rate_delta: -0.25,
        llm_regressions: [],
        llm_improvements: [],
        both_failed: [],
      } as T;
    });

    expect(result.pass_rate_delta).toBe(-0.25);
  });

  it("gets eval run detail", async () => {
    const result = await getEvalRun(async <T>(path: string): Promise<T> => {
      expect(path).toBe("/eval-runs/eval_1");
      return sampleRun as T;
    }, "eval_1");

    expect(result.run_id).toBe("eval_1");
  });

  it("formats eval summary state", () => {
    expect(evalPassRateLabel(0.875)).toBe("88%");
    expect(evalModeLabel("deterministic")).toBe("Deterministic");
    expect(evalModeLabel("llm")).toBe("LLM-backed");
    expect(evalComparisonStatusLabel(null)).toBe("Run both modes");
    expect(evalStatusLabel({ ...sampleRun, status: "running", failed: 0 })).toBe("Running");
    expect(
      evalStatusLabel({
        ...sampleRun,
        status: "degraded",
        error: "LLM provider request failed with HTTP 429: quota exceeded",
      }),
    ).toBe("Provider degraded");
    expect(evalRunHasProviderIssue({ ...sampleRun, error: "LLM provider request failed with HTTP 503: UNAVAILABLE" })).toBe(true);
    expect(evalRunHasProviderIssue({ ...sampleRun, error: "LLM provider request failed: The read operation timed out" })).toBe(true);
    expect(
      evalComparisonStatusLabel({
        suite_id: "support-triage-core",
        status: "ready",
        deterministic_run: sampleRun,
        llm_run: { ...sampleRun, execution_mode: "llm" },
        pass_rate_delta: -0.5,
        llm_regressions: [
          {
            case_id: "case",
            name: "Case",
            deterministic_trace_id: "trace_det",
            llm_trace_id: "trace_llm",
            deterministic_score: 1,
            llm_score: 0.5,
            failed_checks: [],
          },
        ],
        llm_improvements: [],
        both_failed: [],
      }),
    ).toBe("LLM drift detected");
    expect(
      evalComparisonStatusLabel({
        suite_id: "support-triage-core",
        status: "degraded_llm",
        deterministic_run: sampleRun,
        llm_run: {
          ...sampleRun,
          execution_mode: "llm",
          status: "degraded",
          error: "LLM provider request failed with HTTP 429: quota exceeded",
        },
        pass_rate_delta: null,
        llm_regressions: [],
        llm_improvements: [],
        both_failed: [],
      }),
    ).toBe("Provider degraded");
    expect(evalStatusLabel(null)).toBe("Not run");
    expect(evalStatusLabel(sampleRun)).toBe("Needs review");
    expect(failedEvalCases(sampleRun).map((result) => result.case_id)).toEqual(["fail"]);
    expect(failedEvalChecks(sampleRun.results[1]).map((check) => check.name)).toEqual([]);
    expect(formatEvalValue(["cus_123", "policy_a"])).toBe("cus_123, policy_a");
    expect(formatEvalValue({ expected: true })).toBe('{"expected":true}');
  });

  it("summarizes eval model events with fallback priority", () => {
    const result = {
      ...sampleRun.results[0],
      model_events: [
        { span_name: "Triage Agent", model: "gemini-primary", fallback_used: false },
        {
          span_name: "Policy Agent",
          model: "gemini-fallback",
          fallback_used: true,
          attempts: [
            { model: "gemini-primary", status: "failed", error: "HTTP 503" },
            { model: "gemini-fallback", status: "succeeded" },
          ],
        },
      ],
    };

    expect(evalModelSummary(result)?.span_name).toBe("Policy Agent");
    expect(evalModelSummary(result)?.model).toBe("gemini-fallback");
    expect(evalModelSummary({ ...sampleRun.results[0], model_events: [] })).toBeNull();
  });

  it("describes active eval progress from partial results", () => {
    const run: EvalSuiteRun = {
      ...sampleRun,
      status: "running",
      total: 4,
      passed: 1,
      failed: 0,
      pass_rate: 0.25,
      results: sampleRun.results.slice(0, 1),
    };

    expect(evalRunIsActive(run)).toBe(true);
    expect(evalRunIsActive(sampleRun)).toBe(false);
    expect(evalProgress(run)).toEqual({
      completed: 1,
      total: 4,
      percent: 25,
      label: "1/4 cases complete",
    });
    expect(evalProgress(null)).toEqual({
      completed: 0,
      total: 0,
      percent: 0,
      label: "No eval run",
    });
  });

  it("categorizes eval checks by product-facing failure area", () => {
    expect(evalCheckCategory("issue_type")).toBe("Routing");
    expect(evalCheckCategory("policy_id")).toBe("Routing");
    expect(evalCheckCategory("approval_required")).toBe("Governance");
    expect(evalCheckCategory("evidence_id:sub_123")).toBe("Evidence");
    expect(evalCheckCategory("memory_warning_count")).toBe("Memory");
    expect(evalCheckCategory("response_excludes:duplicate")).toBe("Response");
    expect(evalCheckCategory("error_count")).toBe("Reliability");
  });

  it("summarizes eval category failures across a run", () => {
    const run: EvalSuiteRun = {
      ...sampleRun,
      results: [
        {
          case_id: "case_1",
          name: "Case",
          trace_id: "trace_1",
          passed: false,
          score: 0.5,
          checks: [
            { name: "issue_type", expected: "billing", actual: "general", passed: false },
            { name: "policy_id", expected: "policy_a", actual: "policy_b", passed: false },
            { name: "response_excludes:duplicate", expected: "excludes duplicate", actual: "duplicate", passed: false },
            { name: "error_count", expected: 0, actual: 0, passed: true },
          ],
        },
      ],
    };

    expect(evalCategorySummaries(run)).toEqual([
      { category: "Routing", failed: 2, total: 2 },
      { category: "Evidence", failed: 0, total: 0 },
      { category: "Governance", failed: 0, total: 0 },
      { category: "Response", failed: 1, total: 1 },
      { category: "Memory", failed: 0, total: 0 },
      { category: "Reliability", failed: 0, total: 1 },
    ]);
  });

  it("groups failed checks by category for a case", () => {
    const groups = failedChecksByCategory({
      case_id: "case_1",
      name: "Case",
      trace_id: "trace_1",
      passed: false,
      score: 0.5,
      checks: [
        { name: "issue_type", expected: "billing", actual: "general", passed: false },
        { name: "policy_id", expected: "policy_a", actual: "policy_b", passed: false },
        { name: "error_count", expected: 0, actual: 0, passed: true },
      ],
    });

    expect(groups.map((group) => group.category)).toEqual(["Routing"]);
    expect(groups[0].checks[0].name).toBe("issue_type");
  });

  it("builds an improvement plan from failed eval checks", () => {
    const plan = buildEvalImprovementPlan({
      ...sampleRun,
      results: [
        {
          case_id: "approval-regression",
          name: "Approval regression",
          trace_id: "trace_approval",
          passed: false,
          score: 0.5,
          checks: [
            { name: "approval_required", expected: true, actual: false, passed: false },
            { name: "response_excludes:duplicate", expected: "duplicate", actual: "duplicate charge", passed: false },
          ],
        },
      ],
    });

    expect(plan.map((item) => item.category)).toEqual(["Governance", "Response"]);
    expect(plan[0].owner_area).toBe("approval policy and validator guardrails");
    expect(plan[0].suggested_files).toContain("agent_apps/customer_service/runner.py");
    expect(plan[0].cases[0]).toMatchObject({
      case_id: "approval-regression",
      trace_id: "trace_approval",
      check: "approval_required",
      expected: true,
      actual: false,
    });
  });
});
