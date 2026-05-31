import { describe, expect, it } from "vitest";
import { activeFilterCount, emptyFilters, filterQuery } from "./traceFilters";

describe("trace filter helpers", () => {
  it("builds trace list query params", () => {
    const query = filterQuery(
      {
        ...emptyFilters(),
        workflowName: "support-triage",
        status: "failed",
        errorStatus: "true",
        escalationStatus: "true",
        escalationType: "risk_review",
        escalationOwner: "trust_and_safety",
        currentChatOnly: true,
        offset: 25,
      },
      "chat_123",
    );

    const params = new URLSearchParams(query.slice(1));
    expect(params.get("limit")).toBe("25");
    expect(params.get("offset")).toBe("25");
    expect(params.get("workflow_name")).toBe("support-triage");
    expect(params.get("status")).toBe("failed");
    expect(params.get("has_errors")).toBe("true");
    expect(params.get("has_escalation")).toBe("true");
    expect(params.get("escalation_type")).toBe("risk_review");
    expect(params.get("escalation_owner")).toBe("trust_and_safety");
    expect(params.get("chat_session_id")).toBe("chat_123");
  });

  it("counts active filters", () => {
    expect(activeFilterCount(emptyFilters())).toBe(0);
    expect(activeFilterCount({ ...emptyFilters(), status: "failed", escalationStatus: "true", currentChatOnly: true })).toBe(3);
  });
});
