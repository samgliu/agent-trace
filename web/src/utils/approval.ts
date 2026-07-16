export type DecisionActor = {
  type: string;
  id: string;
  displayName: string;
  role: string;
};

export type ApprovalDecision = {
  approvalStatus: string;
  decisionActor?: DecisionActor;
  decisionAction: string;
  decisionAt: string;
  decisionSource?: string;
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
  decisionHistory: ApprovalDecision[];
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
    decisionHistory: extractDecisionHistory(spanData.decision_history),
  };
}

function extractDecisionHistory(value: unknown): ApprovalDecision[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((entry) => {
    if (!entry || typeof entry !== "object") {
      return [];
    }
    const event = entry as Record<string, unknown>;
    const decisionAction = typeof event.decision_action === "string" ? event.decision_action : null;
    const decisionAt = typeof event.decision_at === "string" ? event.decision_at : null;
    if (!decisionAction || !decisionAt) {
      return [];
    }
    return [
      {
        approvalStatus: typeof event.approval_status === "string" ? event.approval_status : "unknown",
        decisionActor: extractDecisionActor(event.decision_actor),
        decisionAction,
        decisionAt,
        decisionSource: typeof event.decision_source === "string" ? event.decision_source : undefined,
      },
    ];
  });
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
