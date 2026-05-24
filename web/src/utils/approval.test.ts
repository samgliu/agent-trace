import { describe, expect, it } from "vitest";
import { getApprovalStatus } from "./approval";

describe("getApprovalStatus", () => {
  it("extracts approval metadata for approval spans", () => {
    expect(
      getApprovalStatus("approval", {
        approval_required: true,
        approval_status: "blocked",
        risk_level: "high",
        permission_scope: "billing.refund.multi_month",
        decision_actor: {
          type: "token_role",
          id: "operator",
          display_name: "Operator",
          role: "operator",
        },
        decision_action: "approved",
        decision_at: "2026-05-24T01:02:03Z",
        decision_source: "dashboard",
      }),
    ).toEqual({
      approvalStatus: "blocked",
      isPending: true,
      isResolved: false,
      riskLevel: "high",
      permissionScope: "billing.refund.multi_month",
      decisionActor: {
        type: "token_role",
        id: "operator",
        displayName: "Operator",
        role: "operator",
      },
      decisionAction: "approved",
      decisionAt: "2026-05-24T01:02:03Z",
      decisionSource: "dashboard",
    });
  });

  it("marks approved and rejected approvals as resolved", () => {
    expect(getApprovalStatus("approval", { approval_status: "approved" })).toMatchObject({
      isPending: false,
      isResolved: true,
    });
    expect(getApprovalStatus("approval", { approval_status: "rejected" })).toMatchObject({
      isPending: false,
      isResolved: true,
    });
  });

  it("returns null for normal spans", () => {
    expect(getApprovalStatus("agent", {})).toBeNull();
  });
});
