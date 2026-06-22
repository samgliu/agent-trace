export type ValidatorReport = {
  groundingStatus: string;
  approvalRequired: boolean;
  policyStatus: string;
  riskReviewRequired: boolean;
  customerSafeToSend: boolean;
  missingEvidence: string[];
  unsupportedClaimCount: number;
  validatorCorrections: string[];
};

export function extractValidatorReport(output: unknown): ValidatorReport | null {
  if (!isRecord(output) || !isRecord(output.validation_report)) {
    return null;
  }

  const report = output.validation_report;
  const policyCompliance = isRecord(report.policy_compliance) ? report.policy_compliance : {};
  return {
    groundingStatus: stringValue(report.grounding_status),
    approvalRequired: booleanValue(report.approval_required),
    policyStatus: stringValue(policyCompliance.status),
    riskReviewRequired: booleanValue(report.risk_review_required),
    customerSafeToSend: booleanValue(report.customer_safe_to_send),
    missingEvidence: stringArray(report.missing_evidence),
    unsupportedClaimCount: Array.isArray(report.unsupported_claims) ? report.unsupported_claims.length : 0,
    validatorCorrections: stringArray(report.validator_corrections),
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function stringValue(value: unknown): string {
  return typeof value === "string" && value.length > 0 ? value : "-";
}

function booleanValue(value: unknown): boolean {
  return typeof value === "boolean" ? value : false;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is string => typeof item === "string" && item.length > 0);
}
