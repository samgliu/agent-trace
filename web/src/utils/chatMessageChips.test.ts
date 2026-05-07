import { describe, expect, it } from "vitest";
import { buildChatMessageChips } from "./chatMessageChips";

describe("chat message trace chips", () => {
  it("builds compact status chips from trace summaries", () => {
    expect(
      buildChatMessageChips({
        status: "recovered",
        grounding_status: "recovered",
        approval_pending_count: 1,
        error_count: 2,
        estimated_cost: 0.012,
        duration_ms: 6200,
      }),
    ).toEqual([
      { label: "Recovered", tone: "warning" },
      { label: "Needs approval", tone: "warning" },
      { label: "Errors: 2", tone: "danger" },
      { label: "$0.0120", tone: "warning" },
      { label: "6.20s", tone: "warning" },
    ]);
  });

  it("returns no chips before a summary is loaded", () => {
    expect(buildChatMessageChips(undefined)).toEqual([]);
  });
});
