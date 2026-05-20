import { useState } from "react";
import { Activity, MessageSquare, Send } from "lucide-react";
import type { ChatInput, ChatStatus, TraceSummary } from "../../types";
import { buildChatMessageChips } from "../../utils/chatMessageChips";
import type { ChatMessage, ChatSession, LLMProvider } from "../../utils/chat";

export function ChatMonitor({
  session,
  sessions,
  messages,
  traceSummaries,
  status,
  latestTraceId,
  onSelectSession,
  onNewSession,
  onSelectTrace,
  onSubmit,
}: {
  session: ChatSession | null;
  sessions: ChatSession[];
  messages: ChatMessage[];
  traceSummaries: Record<string, TraceSummary>;
  status: ChatStatus;
  latestTraceId: string | null;
  onSelectSession: (sessionId: string) => Promise<void>;
  onNewSession: () => void;
  onSelectTrace: (traceId: string) => void;
  onSubmit: (input: ChatInput) => Promise<void>;
}) {
  const [customerEmail, setCustomerEmail] = useState("customer@example.com");
  const [message, setMessage] = useState("I was charged twice for my Pro subscription yesterday. Can I get a refund?");
  const [llmProvider, setLlmProvider] = useState<LLMProvider>("deterministic");
  const isSubmitting = status.status === "submitting";

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedMessage = message.trim();
    const trimmedEmail = customerEmail.trim();
    if (!trimmedMessage || !trimmedEmail || isSubmitting) {
      return;
    }
    setMessage("");
    await onSubmit({ customerEmail: trimmedEmail, message: trimmedMessage, llmProvider });
  }

  return (
    <section className="chatMonitor" aria-label="Live customer-service agent">
      <div className="chatHeader">
        <div>
          <small>Live customer-service agent</small>
          <h2>Chat monitor</h2>
        </div>
        <div className="chatSessionControls">
          <select value={session?.session_id ?? ""} onChange={(event) => onSelectSession(event.target.value)}>
            <option value="">New session</option>
            {sessions.map((chatSession) => (
              <option value={chatSession.session_id} key={chatSession.session_id}>
                {chatSession.title ?? chatSession.customer_email} · {chatSession.customer_email}
              </option>
            ))}
          </select>
          <button type="button" onClick={onNewSession}>
            New
          </button>
        </div>
      </div>
      <div className="chatBody">
        <form className="chatComposer" onSubmit={submit}>
          <label>
            <span>Customer email</span>
            <input
              value={customerEmail}
              onChange={(event) => setCustomerEmail(event.target.value)}
              disabled={Boolean(session) || isSubmitting}
            />
          </label>
          <label className="chatMessageInput">
            <span>Message</span>
            <textarea value={message} onChange={(event) => setMessage(event.target.value)} disabled={isSubmitting} />
          </label>
          <label>
            <span>LLM provider</span>
            <select
              value={llmProvider}
              onChange={(event) => setLlmProvider(event.target.value as LLMProvider)}
              disabled={isSubmitting}
            >
              <option value="deterministic">Deterministic</option>
              <option value="openai_compatible">Configured LLM</option>
            </select>
          </label>
          <button type="submit" disabled={isSubmitting || !message.trim()}>
            {isSubmitting ? <Activity size={15} /> : <Send size={15} />}
            {isSubmitting ? "Sending" : "Send"}
          </button>
          {status.status === "error" ? <p className="chatError">{status.message}</p> : null}
        </form>
        <div className="chatThread" aria-live="polite">
          {messages.length === 0 ? (
            <div className="chatEmpty">
              <MessageSquare size={18} />
              <span>Send a customer message to generate a monitored trace.</span>
            </div>
          ) : (
            messages.map((chatMessage) => {
              const isPending = chatMessage.metadata.pending === true;
              const errorMessage = typeof chatMessage.metadata.error === "string" ? chatMessage.metadata.error : null;
              return (
                <div
                  className={`chatBubble ${chatMessage.role}${isPending ? " pending" : ""}${
                    errorMessage ? " error" : ""
                  }`}
                  key={chatMessage.message_id}
                >
                  <small>{chatMessage.role}</small>
                  <p>{chatMessage.content}</p>
                  {errorMessage ? <span className="chatMessageError">{errorMessage}</span> : null}
                  {chatMessage.trace_id ? (
                    <div className="chatMessageChips">
                      {buildChatMessageChips(traceSummaries[chatMessage.trace_id]).map((chip) => (
                        <span className={`chatMessageChip ${chip.tone}`} key={chip.label}>
                          {chip.label}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  {chatMessage.trace_id ? (
                    <button className="chatTraceLink" type="button" onClick={() => onSelectTrace(chatMessage.trace_id!)}>
                      Trace: {chatMessage.trace_id}
                      {chatMessage.trace_id === latestTraceId ? <strong>Latest</strong> : null}
                    </button>
                  ) : null}
                </div>
              );
            })
          )}
          {isSubmitting ? (
            <div className="chatBubble assistant pending" aria-label="Assistant response pending">
              <small>assistant</small>
              <p>Checking account, policy, and approval context</p>
              <span className="typingDots" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
