export type ChatSession = {
  session_id: string;
  customer_email: string;
  title: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ChatMessage = {
  message_id: string;
  session_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  trace_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
};

export type ChatTurnResponse<Trace = unknown> = {
  session: ChatSession;
  user_message: ChatMessage;
  assistant_message: ChatMessage;
  trace: Trace;
};

export type ChatTransport = <T>(path: string, body?: unknown) => Promise<T>;
export type ChatGetTransport = <T>(path: string) => Promise<T>;
export type LLMProvider = "deterministic" | "openai_compatible";

export type ChatSessionDetail = ChatSession & {
  messages: ChatMessage[];
};

export function createPendingUserMessage(input: {
  sessionId: string;
  content: string;
  messageId?: string;
  createdAt?: string;
}): ChatMessage {
  return {
    message_id: input.messageId ?? `pending_${Date.now()}`,
    session_id: input.sessionId,
    role: "user",
    content: input.content,
    trace_id: null,
    metadata: { pending: true },
    created_at: input.createdAt ?? new Date().toISOString(),
  };
}

export function replacePendingChatTurn(
  messages: ChatMessage[],
  pendingMessageId: string,
  userMessage: ChatMessage,
  assistantMessage: ChatMessage,
): ChatMessage[] {
  let replaced = false;
  const nextMessages = messages.map((message) => {
    if (message.message_id !== pendingMessageId) {
      return message;
    }
    replaced = true;
    return userMessage;
  });
  return [...(replaced ? nextMessages : [...nextMessages, userMessage]), assistantMessage];
}

export function markPendingMessageFailed(
  messages: ChatMessage[],
  pendingMessageId: string,
  errorMessage: string,
): ChatMessage[] {
  return messages.map((message) => {
    if (message.message_id !== pendingMessageId) {
      return message;
    }
    return {
      ...message,
      metadata: { ...message.metadata, pending: false, error: errorMessage },
    };
  });
}

export function listChatSessions(transport: ChatGetTransport): Promise<ChatSession[]> {
  return transport("/chat/sessions");
}

export function getChatSession(transport: ChatGetTransport, sessionId: string): Promise<ChatSessionDetail> {
  return transport(`/chat/sessions/${sessionId}`);
}

export function createChatSession(
  transport: ChatTransport,
  input: { customerEmail: string; title?: string },
): Promise<ChatSession & { messages?: ChatMessage[] }> {
  return transport("/chat/sessions", {
    customer_email: input.customerEmail,
    title: input.title,
  });
}

export function sendChatMessage<Trace>(
  transport: ChatTransport,
  sessionId: string,
  input: { content: string; llmProvider?: LLMProvider; openaiApi?: "chat_completions" | "responses" },
): Promise<ChatTurnResponse<Trace>> {
  return transport(`/chat/sessions/${sessionId}/messages`, {
    content: input.content,
    use_openai: input.llmProvider === "openai_compatible",
    openai_api: input.openaiApi ?? "chat_completions",
  });
}
