import { describe, expect, it } from "vitest";
import { createChatSession, getChatSession, listChatSessions, sendChatMessage, type ChatGetTransport, type ChatTransport } from "./chat";

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

  it("sends chat messages with OpenAI-compatible provider", async () => {
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

    await sendChatMessage(transport, "chat_1", { content: "Refund?", llmProvider: "openai_compatible" });

    expect(calls[0]).toEqual({
      path: "/chat/sessions/chat_1/messages",
      body: { content: "Refund?", use_openai: true, openai_api: "chat_completions" },
    });
  });

  it("loads chat sessions and session details", async () => {
    const calls: string[] = [];
    const transport: ChatGetTransport = async <T>(path: string): Promise<T> => {
      calls.push(path);
      if (path === "/chat/sessions") {
        return [{ session_id: "chat_1" }] as T;
      }
      return { session_id: "chat_1", messages: [{ message_id: "msg_1" }] } as T;
    };

    const sessions = await listChatSessions(transport);
    const detail = await getChatSession(transport, "chat_1");

    expect(sessions[0].session_id).toBe("chat_1");
    expect(detail.messages[0].message_id).toBe("msg_1");
    expect(calls).toEqual(["/chat/sessions", "/chat/sessions/chat_1"]);
  });
});
