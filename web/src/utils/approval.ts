export type ApprovalStatus = {
  approvalStatus: string;
  isPending: boolean;
  isResolved: boolean;
  riskLevel?: string;
  permissionScope?: string;
};

export function getApprovalStatus(spanType: string, spanData: Record<string, unknown>): ApprovalStatus | null {
  const approvalRequired = spanData.approval_required;
  if (spanType !== "approval" && approvalRequired !== true) {
    return null;
  }
  const approvalStatus = String(spanData.approval_status ?? "unknown");
  return {
    approvalStatus,
    isPending: approvalStatus === "blocked" || approvalStatus === "pending",
    isResolved: approvalStatus === "approved" || approvalStatus === "rejected",
    riskLevel: typeof spanData.risk_level === "string" ? spanData.risk_level : undefined,
    permissionScope: typeof spanData.permission_scope === "string" ? spanData.permission_scope : undefined,
  };
}
