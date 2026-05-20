import { useState } from "react";
import { Activity, GitBranch, RotateCcw, Send } from "lucide-react";
import type { LiveWorkflowInput, TraceDetail } from "../../types";
import type { LLMProvider } from "../../utils/chat";
import { isWorkflowRunActive, type WorkflowRun } from "../../utils/workflowRuns";

export function LiveWorkflowPanel({
  run,
  error,
  onStart,
  onCancel,
  onRetry,
}: {
  run: WorkflowRun<TraceDetail> | null;
  error: string | null;
  onStart: (input: LiveWorkflowInput) => Promise<void>;
  onCancel: () => Promise<void>;
  onRetry: () => Promise<void>;
}) {
  const [customerEmail, setCustomerEmail] = useState("customer@example.com");
  const [message, setMessage] = useState("I was charged twice for my Pro subscription yesterday. Can I get a refund?");
  const [llmProvider, setLlmProvider] = useState<LLMProvider>("deterministic");
  const active = isWorkflowRunActive(run);
  const canRetry = run?.status === "failed" || run?.status === "cancelled";

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedEmail = customerEmail.trim();
    const trimmedMessage = message.trim();
    if (!trimmedEmail || !trimmedMessage || active) {
      return;
    }
    await onStart({ customerEmail: trimmedEmail, message: trimmedMessage, llmProvider });
  }

  return (
    <section className="liveWorkflow">
      <div className="liveWorkflowHeader">
        <div>
          <small>Running workflow monitor</small>
          <h2>Support-triage live run</h2>
        </div>
        <span className={run?.status === "failed" || run?.status === "cancelled" ? "liveRunStatus failed" : "liveRunStatus"}>
          {active ? <Activity size={15} /> : <GitBranch size={15} />}
          {run?.status ?? "idle"}
        </span>
      </div>
      <form className="liveWorkflowForm" onSubmit={submit}>
        <label>
          <span>Customer email</span>
          <input value={customerEmail} onChange={(event) => setCustomerEmail(event.target.value)} disabled={active} />
        </label>
        <label className="liveWorkflowMessage">
          <span>Message</span>
          <input value={message} onChange={(event) => setMessage(event.target.value)} disabled={active} />
        </label>
        <label>
          <span>LLM provider</span>
          <select value={llmProvider} onChange={(event) => setLlmProvider(event.target.value as LLMProvider)} disabled={active}>
            <option value="deterministic">Deterministic</option>
            <option value="openai_compatible">Configured LLM</option>
          </select>
        </label>
        <button type="submit" disabled={active || !message.trim()}>
          {active ? <Activity size={15} /> : <Send size={15} />}
          Run
        </button>
        <button className="secondary" type="button" disabled={!active} onClick={onCancel}>
          Cancel
        </button>
        <button className="secondary" type="button" disabled={!canRetry} onClick={onRetry}>
          <RotateCcw size={15} />
          Retry
        </button>
      </form>
      {run ? (
        <div className="liveRunDetails">
          <span>Run: {run.run_id}</span>
          {run.trace_id ? <span>Trace: {run.trace_id}</span> : <span>Trace pending</span>}
          {run.trace ? <span>{run.trace.spans.length} spans visible</span> : null}
          {run.completed_at ? <span>Completed: {run.completed_at}</span> : <span>Updated: {run.updated_at}</span>}
        </div>
      ) : null}
      {error ? <p className="chatError">{error}</p> : null}
    </section>
  );
}
