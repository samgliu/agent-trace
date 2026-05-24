import { describe, expect, it } from "vitest";
import { canManageApprovals, displayRole } from "./authz";

describe("authz", () => {
  it("allows admin and operator approval actions", () => {
    expect(canManageApprovals("admin")).toBe(true);
    expect(canManageApprovals("operator")).toBe(true);
  });

  it("blocks viewer and unknown approval actions", () => {
    expect(canManageApprovals("viewer")).toBe(false);
    expect(canManageApprovals(null)).toBe(false);
    expect(canManageApprovals(undefined)).toBe(false);
  });

  it("formats unknown role labels", () => {
    expect(displayRole("viewer")).toBe("viewer");
    expect(displayRole(null)).toBe("unknown");
  });
});
