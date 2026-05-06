import { describe, expect, it } from "vitest";
import { chatTurnBadges, isChatTrace, isLatestChatTrace } from "./chatTrace";

describe("chat trace helpers", () => {
  it("detects traces created by the active chat session", () => {
    expect(
      isChatTrace(
        {
          trace_id: "trace_1",
          metadata: { chat_session_id: "chat_1" },
        },
        "chat_1",
      ),
    ).toBe(true);
    expect(isChatTrace({ trace_id: "trace_1", metadata: { chat_session_id: "chat_2" } }, "chat_1")).toBe(false);
  });

  it("detects the latest chat trace", () => {
    expect(isLatestChatTrace("trace_1", "trace_1")).toBe(true);
    expect(isLatestChatTrace("trace_1", "trace_2")).toBe(false);
  });

  it("builds badges for chat turn summaries", () => {
    expect(
      chatTurnBadges(
        {
          trace_id: "trace_1",
          approval_pending_count: 1,
          error_count: 2,
          status: "recovered",
        },
        { isChatTurn: true, isLatest: true },
      ),
    ).toEqual(["Chat turn", "Latest"]);
  });
});
