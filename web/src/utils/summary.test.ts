import { describe, expect, it } from "vitest";
import { buildExecutiveSummary, countApprovals } from "./summary";

describe("countApprovals", () => {
  it("counts pending and resolved approval spans", () => {
    expect(
      countApprovals([
        { span_type: "approval", span_data: { approval_status: "blocked" } },
        { span_type: "approval", span_data: { approval_status: "approved" } },
        { span_type: "agent", span_data: {} },
      ]),
    ).toEqual({
      total: 2,
      pending: 1,
      approved: 1,
      rejected: 0,
    });
  });
});

describe("buildExecutiveSummary", () => {
  it("prioritizes pending approvals", () => {
    expect(
      buildExecutiveSummary(
        {
          status: "passed",
          duration_ms: 4200,
          spans: [{ span_type: "approval", span_data: { approval_status: "blocked" } }],
        },
        { span_count: 9, input_tokens: 1000, output_tokens: 400, estimated_cost: 0.01 },
        { status: "recovered", unsupported_claim_count: 1, recovered: true },
      ),
    ).toBe("1 approval waiting before this workflow can safely continue.");
  });

  it("summarizes recovered grounding when no approval is pending", () => {
    expect(
      buildExecutiveSummary(
        { status: "passed", duration_ms: 4000, spans: [] },
        { span_count: 8, input_tokens: 1000, output_tokens: 400, estimated_cost: 0.01 },
        { status: "recovered", unsupported_claim_count: 1, recovered: true },
      ),
    ).toBe("1 unsupported claim recovered before final response.");
  });
});

