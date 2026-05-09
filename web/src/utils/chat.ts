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
  role: "user" | "assistant";
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
