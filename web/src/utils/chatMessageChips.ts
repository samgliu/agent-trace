import { formatCost, formatDuration } from "./format";

export type ChatMessageTraceSummaryInput = {
  status: string;
  grounding_status: string;
  approval_pending_count: number;
  error_count: number;
  estimated_cost: number;
  duration_ms: number | null;
};

export type ChatMessageChip = {
  label: string;
  tone: "neutral" | "success" | "warning" | "danger";
};

export function buildChatMessageChips(summary: ChatMessageTraceSummaryInput | undefined): ChatMessageChip[] {
  if (!summary) {
    return [];
  }
  const chips: ChatMessageChip[] = [
    {
      label: statusLabel(summary.status),
      tone: statusTone(summary.status),
    },
  ];
  if (summary.grounding_status !== summary.status && summary.grounding_status !== "grounded") {
    chips.push({ label: `Grounding: ${summary.grounding_status}`, tone: groundingTone(summary.grounding_status) });
  }
  if (summary.approval_pending_count > 0) {
    chips.push({ label: "Needs approval", tone: "warning" });
  }
  if (summary.error_count > 0) {
    chips.push({ label: `Errors: ${summary.error_count}`, tone: "danger" });
  }
  if (summary.estimated_cost > 0) {
    chips.push({ label: formatCost(summary.estimated_cost), tone: summary.estimated_cost > 0.01 ? "warning" : "neutral" });
  }
  if (summary.duration_ms !== null) {
    chips.push({ label: formatDuration(summary.duration_ms), tone: summary.duration_ms > 5000 ? "warning" : "neutral" });
  }
  return chips;
}

function statusLabel(status: string): string {
  if (status === "grounded") return "Passed";
  if (status === "recovered") return "Recovered";
  return status.charAt(0).toUpperCase() + status.slice(1);
}

function statusTone(status: string): ChatMessageChip["tone"] {
  if (status === "failed" || status === "rejected") return "danger";
  if (status === "recovered" || status === "running") return "warning";
  return "success";
}

function groundingTone(status: string): ChatMessageChip["tone"] {
  if (status === "failed") return "danger";
  if (status === "recovered") return "warning";
  if (status === "grounded") return "success";
  return "neutral";
}
