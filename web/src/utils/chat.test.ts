import { describe, expect, it } from "vitest";
import { createChatSession, sendChatMessage, type ChatTransport } from "./chat";

describe("chat api helpers", () => {
  it("creates a chat session with backend field names", async () => {
    const calls: Array<{ path: string; body?: unknown }> = [];
    const transport: ChatTransport = async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return {
        session_id: "chat_1",
        customer_email: "customer@example.com",
        title: "Billing",
        metadata: {},
        created_at: "now",
        updated_at: "now",
      } as T;
    };

    const session = await createChatSession(transport, {
      customerEmail: "customer@example.com",
      title: "Billing",
    });

    expect(session.session_id).toBe("chat_1");
    expect(calls).toEqual([
      {
        path: "/chat/sessions",
        body: { customer_email: "customer@example.com", title: "Billing" },
      },
    ]);
  });

  it("sends chat messages and keeps generic OpenAI disabled by default", async () => {
    const calls: Array<{ path: string; body?: unknown }> = [];
    const transport: ChatTransport = async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return {
        session: { session_id: "chat_1" },
        user_message: { role: "user" },
        assistant_message: { role: "assistant", trace_id: "trace_1" },
        trace: { trace_id: "trace_1" },
      } as T;
    };

    const result = await sendChatMessage(transport, "chat_1", { content: "Refund?" });

    expect(result.assistant_message.trace_id).toBe("trace_1");
    expect(calls).toEqual([
      {
        path: "/chat/sessions/chat_1/messages",
        body: { content: "Refund?", use_openai: false, openai_api: "chat_completions" },
      },
    ]);
  });
});
