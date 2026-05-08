import { describe, expect, it } from "vitest";
import {
  evalPassRateLabel,
  evalStatusLabel,
  failedEvalCases,
  runSupportTriageEvalSuite,
  type EvalSuiteRun,
} from "./evals";

const sampleRun: EvalSuiteRun = {
  suite_id: "support-triage-core",
  name: "Support triage core",
  total: 2,
  passed: 1,
  failed: 1,
  pass_rate: 0.5,
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

  it("formats eval summary state", () => {
    expect(evalPassRateLabel(0.875)).toBe("88%");
    expect(evalStatusLabel(null)).toBe("Not run");
    expect(evalStatusLabel(sampleRun)).toBe("Needs review");
    expect(failedEvalCases(sampleRun).map((result) => result.case_id)).toEqual(["fail"]);
  });
});
