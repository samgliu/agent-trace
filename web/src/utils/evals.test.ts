import { describe, expect, it } from "vitest";
import {
  evalCategorySummaries,
  evalCheckCategory,
  evalPassRateLabel,
  evalStatusLabel,
  failedEvalCases,
  failedChecksByCategory,
  listEvalRuns,
  runSupportTriageEvalSuite,
  type EvalRunListResponse,
  type EvalSuiteRun,
} from "./evals";

const sampleRun: EvalSuiteRun = {
  run_id: "eval_1",
  suite_id: "support-triage-core",
  name: "Support triage core",
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
    expect(calls).toEqual([{ path: "/evals/support-triage/run", body: undefined }]);
  });

  it("lists recent eval runs", async () => {
    const response: EvalRunListResponse = {
      items: [
        {
          run_id: sampleRun.run_id,
          suite_id: sampleRun.suite_id,
          name: sampleRun.name,
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

  it("formats eval summary state", () => {
    expect(evalPassRateLabel(0.875)).toBe("88%");
    expect(evalStatusLabel(null)).toBe("Not run");
    expect(evalStatusLabel(sampleRun)).toBe("Needs review");
    expect(failedEvalCases(sampleRun).map((result) => result.case_id)).toEqual(["fail"]);
  });

  it("categorizes eval checks by product-facing failure area", () => {
    expect(evalCheckCategory("issue_type")).toBe("Routing");
    expect(evalCheckCategory("policy_id")).toBe("Policy");
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
      { category: "Routing", failed: 1, total: 1 },
      { category: "Policy", failed: 1, total: 1 },
      { category: "Memory", failed: 0, total: 0 },
      { category: "Response", failed: 1, total: 1 },
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

    expect(groups.map((group) => group.category)).toEqual(["Routing", "Policy"]);
    expect(groups[0].checks[0].name).toBe("issue_type");
  });
});
