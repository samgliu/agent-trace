export type WorkflowRunStatus = "pending" | "running" | "cancel_requested" | "completed" | "failed" | "cancelled";

export type WorkflowRun<Trace = unknown> = {
  run_id: string;
  workflow_name: string;
  status: WorkflowRunStatus;
  trace_id: string | null;
  error: string | null;
  started_at: string;
  updated_at: string;
  completed_at: string | null;
  trace?: Trace;
};

export type WorkflowRunTransport = <T>(path: string, body?: unknown) => Promise<T>;
export type WorkflowRunGetTransport = <T>(path: string) => Promise<T>;

export function startSupportTriageLiveRun<Trace>(
  transport: WorkflowRunTransport,
  input: { message: string; customerEmail: string; useOpenAI?: boolean },
): Promise<WorkflowRun<Trace>> {
  return transport("/workflows/support-triage/runs/live", {
    message: input.message,
    customer_email: input.customerEmail,
    use_openai: input.useOpenAI ?? false,
    openai_api: "chat_completions",
  });
}

export function getWorkflowRun<Trace>(
  transport: WorkflowRunGetTransport,
  runId: string,
): Promise<WorkflowRun<Trace>> {
  return transport(`/workflow-runs/${runId}`);
}

export function cancelWorkflowRun<Trace>(
  transport: WorkflowRunTransport,
  runId: string,
): Promise<WorkflowRun<Trace>> {
  return transport(`/workflow-runs/${runId}/cancel`);
}

export function retryWorkflowRun<Trace>(
  transport: WorkflowRunTransport,
  runId: string,
): Promise<WorkflowRun<Trace>> {
  return transport(`/workflow-runs/${runId}/retry`);
}

export function isWorkflowRunActive(run: WorkflowRun | null): boolean {
  return run?.status === "pending" || run?.status === "running" || run?.status === "cancel_requested";
}
