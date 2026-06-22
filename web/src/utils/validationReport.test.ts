import { describe, expect, it } from "vitest";
import { extractValidatorReport } from "./validationReport";

describe("extractValidatorReport", () => {
  it("normalizes validator reports for display", () => {
    expect(
      extractValidatorReport({
        validation_report: {
          grounding_status: "grounded",
          approval_required: false,
          policy_compliance: { status: "passed" },
          unsupported_claims: [{ claim: "unsupported refund" }],
          missing_evidence: ["charge"],
          risk_review_required: false,
          customer_safe_to_send: true,
          validator_corrections: ["required_approval_enforced"],
        },
      }),
    ).toEqual({
      groundingStatus: "grounded",
      approvalRequired: false,
      policyStatus: "passed",
      riskReviewRequired: false,
      customerSafeToSend: true,
      missingEvidence: ["charge"],
      unsupportedClaimCount: 1,
      validatorCorrections: ["required_approval_enforced"],
    });
  });

  it("returns null when a span has no structured validation report", () => {
    expect(extractValidatorReport({ grounding_status: "grounded" })).toBeNull();
  });
});
