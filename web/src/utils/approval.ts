export type DecisionActor = {
  type: string;
  id: string;
  displayName: string;
  role: string;
};

export type ApprovalStatus = {
  approvalStatus: string;
  isPending: boolean;
  isResolved: boolean;
  riskLevel?: string;
  permissionScope?: string;
  decisionActor?: DecisionActor;
  decisionAction?: string;
  decisionAt?: string;
  decisionSource?: string;
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
    decisionActor: extractDecisionActor(spanData.decision_actor),
    decisionAction: typeof spanData.decision_action === "string" ? spanData.decision_action : undefined,
    decisionAt: typeof spanData.decision_at === "string" ? spanData.decision_at : undefined,
    decisionSource: typeof spanData.decision_source === "string" ? spanData.decision_source : undefined,
  };
}

function extractDecisionActor(value: unknown): DecisionActor | undefined {
  if (!value || typeof value !== "object") {
    return undefined;
  }
  const actor = value as Record<string, unknown>;
  const type = typeof actor.type === "string" ? actor.type : null;
  const id = typeof actor.id === "string" ? actor.id : null;
  const displayName = typeof actor.display_name === "string" ? actor.display_name : null;
  const role = typeof actor.role === "string" ? actor.role : null;
  if (!type || !id || !displayName || !role) {
    return undefined;
  }
  return { type, id, displayName, role };
}
