import { describe, expect, it } from "vitest";
import {
  createChatSession,
  createPendingUserMessage,
  getChatMessages,
  getChatSession,
  listChatSessions,
  markPendingMessageFailed,
  replacePendingChatTurn,
  sendChatMessage,
  sendChatMessageAsync,
  type ChatGetTransport,
  type ChatMessage,
  type ChatTransport,
} from "./chat";

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

  it("enqueues async chat messages against the async endpoint", async () => {
    const calls: Array<{ path: string; body?: unknown }> = [];
    const transport: ChatTransport = async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return {
        session: { session_id: "chat_1" },
        user_message: { role: "user" },
        assistant_message: { role: "assistant", metadata: { pending: true } },
      } as T;
    };

    const result = await sendChatMessageAsync(transport, "chat_1", { content: "Refund?" });

    expect(result.assistant_message.metadata.pending).toBe(true);
    expect(calls[0]).toEqual({
      path: "/chat/sessions/chat_1/messages/async",
      body: { content: "Refund?", use_openai: false, openai_api: "chat_completions" },
    });
  });

  it("loads chat sessions, session details, and messages", async () => {
    const calls: string[] = [];
    const transport: ChatGetTransport = async <T>(path: string): Promise<T> => {
      calls.push(path);
      if (path === "/chat/sessions") {
        return [{ session_id: "chat_1" }] as T;
      }
      if (path === "/chat/sessions/chat_1/messages") {
        return [{ message_id: "msg_2" }] as T;
      }
      return { session_id: "chat_1", messages: [{ message_id: "msg_1" }] } as T;
    };

    const sessions = await listChatSessions(transport);
    const detail = await getChatSession(transport, "chat_1");
    const messages = await getChatMessages(transport, "chat_1");

    expect(sessions[0].session_id).toBe("chat_1");
    expect(detail.messages[0].message_id).toBe("msg_1");
    expect(messages[0].message_id).toBe("msg_2");
    expect(calls).toEqual(["/chat/sessions", "/chat/sessions/chat_1", "/chat/sessions/chat_1/messages"]);
  });

  it("creates a pending user message for optimistic chat rendering", () => {
    const message = createPendingUserMessage({
      sessionId: "chat_1",
      content: "What happens next?",
      messageId: "pending_1",
      createdAt: "2026-05-10T10:00:00.000Z",
    });

    expect(message).toEqual({
      message_id: "pending_1",
      session_id: "chat_1",
      role: "user",
      content: "What happens next?",
      trace_id: null,
      metadata: { pending: true },
      created_at: "2026-05-10T10:00:00.000Z",
    });
  });

  it("replaces the pending message and appends the assistant response", () => {
    const pending = createPendingUserMessage({
      sessionId: "chat_1",
      content: "Refund?",
      messageId: "pending_1",
      createdAt: "2026-05-10T10:00:00.000Z",
    });
    const userMessage: ChatMessage = { ...pending, message_id: "msg_user_1", metadata: {} };
    const assistantMessage: ChatMessage = {
      message_id: "msg_assistant_1",
      session_id: "chat_1",
      role: "assistant",
      content: "I can help review that.",
      trace_id: "trace_1",
      metadata: {},
      created_at: "2026-05-10T10:00:01.000Z",
    };

    const result = replacePendingChatTurn([pending], "pending_1", userMessage, assistantMessage);

    expect(result).toEqual([userMessage, assistantMessage]);
  });

  it("marks a pending message failed without removing the customer text", () => {
    const pending = createPendingUserMessage({
      sessionId: "chat_1",
      content: "Refund?",
      messageId: "pending_1",
      createdAt: "2026-05-10T10:00:00.000Z",
    });

    const result = markPendingMessageFailed([pending], "pending_1", "Provider rate limit");

    expect(result[0].content).toBe("Refund?");
    expect(result[0].metadata).toEqual({ pending: false, error: "Provider rate limit" });
  });
});
