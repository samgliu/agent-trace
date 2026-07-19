import { describe, expect, it } from "vitest";
import {
  defaultTraceId,
  latestTraceFromMessages,
  parseServerEvent,
  replacePendingChatMessage,
  summaryMap,
  traceSummaryQuery,
  uniqueTraceIds,
  upsertChatSession,
} from "./appState";
import type { ChatMessage, ChatSession } from "./chat";
import type { TraceSummary } from "../types";

const baseMessage: ChatMessage = {
  message_id: "msg_1",
  session_id: "chat_1",
  role: "user",
  content: "hello",
  trace_id: null,
  created_at: "2026-05-20T00:00:00Z",
  metadata: {},
};

describe("app state helpers", () => {
  it("builds trace summary query params", () => {
    expect(traceSummaryQuery(["trace_a", "trace_b"])).toBe("?trace_ids=trace_a%2Ctrace_b");
  });

  it("finds latest and unique trace ids from chat messages", () => {
    const messages = [
      baseMessage,
      { ...baseMessage, message_id: "msg_2", trace_id: "trace_a" },
      { ...baseMessage, message_id: "msg_3", trace_id: "trace_b" },
      { ...baseMessage, message_id: "msg_4", trace_id: "trace_a" },
    ];

    expect(latestTraceFromMessages(messages)).toBe("trace_a");
    expect(uniqueTraceIds(messages)).toEqual(["trace_a", "trace_b"]);
  });

  it("replaces pending chat messages with completed turn messages", () => {
    const result = replacePendingChatMessage(
      [baseMessage, { ...baseMessage, message_id: "pending" }],
      "pending",
      { ...baseMessage, message_id: "user_done" },
      { ...baseMessage, message_id: "assistant_done", role: "assistant" },
    );

    expect(result.map((message) => message.message_id)).toEqual(["msg_1", "user_done", "assistant_done"]);
  });

  it("indexes summaries and upserts chat sessions", () => {
    const summary = { trace_id: "trace_a" } as TraceSummary;
    expect(summaryMap([summary])).toEqual({ trace_a: summary });

    const session = { session_id: "chat_1", customer_email: "a@example.com" } as ChatSession;
    const updated = upsertChatSession([{ ...session, customer_email: "old@example.com" }], session);
    expect(updated).toEqual([session]);
  });

  it("prefers agent-runner traces for default dashboard selection", () => {
    expect(
      defaultTraceId([
        { trace_id: "trace_e2e", source_kind: "live_api" } as TraceSummary,
        { trace_id: "trace_agent", source_kind: "agent_runner" } as TraceSummary,
      ]),
    ).toBe("trace_agent");
    expect(defaultTraceId([{ trace_id: "trace_only", source_kind: "live_api" } as TraceSummary])).toBe("trace_only");
    expect(defaultTraceId([])).toBeNull();
  });

  it("parses server events defensively", () => {
    expect(parseServerEvent(new MessageEvent("message", { data: '{"type":"trace.created"}' }))).toEqual({
      type: "trace.created",
    });
    expect(parseServerEvent(new MessageEvent("message", { data: "not-json" }))).toBeNull();
  });
});
