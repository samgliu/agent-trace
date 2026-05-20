export function executionStatus(status: string): string {
  if (status === "grounded" || status === "recovered") return "passed";
  return status;
}

export function statusTone(status: string): string {
  if (status === "failed" || status === "rejected") return "danger";
  if (status === "running") return "warning";
  return "neutral";
}

export function groundingTone(status: string): string {
  if (status === "failed") return "danger";
  if (status === "recovered") return "warning";
  if (status === "grounded") return "success";
  return "neutral";
}
