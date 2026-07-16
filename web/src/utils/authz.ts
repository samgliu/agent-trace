export type AuthRole = "admin" | "operator" | "viewer";

export function canManageApprovals(role: AuthRole | null | undefined): boolean {
  return role === "admin" || role === "operator";
}

export function displayRole(role: AuthRole | null | undefined): string {
  return role ?? "unknown";
}
