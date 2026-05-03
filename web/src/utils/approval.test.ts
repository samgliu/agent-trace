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
      }),
    ).toEqual({
      approvalStatus: "blocked",
      riskLevel: "high",
      permissionScope: "billing.refund.multi_month",
    });
  });

  it("returns null for normal spans", () => {
    expect(getApprovalStatus("agent", {})).toBeNull();
  });
});
