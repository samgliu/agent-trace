import { describe, expect, it } from "vitest";
import {
  cancelWorkflowRun,
  getWorkflowRun,
  isWorkflowRunActive,
  retryWorkflowRun,
  startSupportTriageLiveRun,
} from "./workflowRuns";

describe("workflow run api helpers", () => {
  it("starts a support triage live run with backend field names", async () => {
    const calls: unknown[] = [];
    const transport = async <T>(path: string, body?: unknown): Promise<T> => {
      calls.push({ path, body });
      return {
        run_id: "run_1",
        workflow_name: "support-triage",
        status: "running",
        trace_id: null,
        error: null,
        started_at: "2026-05-07T00:00:00Z",
        updated_at: "2026-05-07T00:00:00Z",
        completed_at: null,
      } as T;
    };

    const run = await startSupportTriageLiveRun(transport, {
      message: "Refund?",
      customerEmail: "customer@example.com",
    });

    expect(run.status).toBe("running");
    expect(calls).toEqual([
      {
        path: "/workflows/support-triage/runs/live",
        body: {
          message: "Refund?",
          customer_email: "customer@example.com",
          use_openai: false,
          openai_api: "chat_completions",
        },
      },
    ]);
  });

  it("polls workflow run status", async () => {
    const run = await getWorkflowRun(
      async <T>(path: string): Promise<T> =>
        ({
          run_id: path.replace("/workflow-runs/", ""),
          workflow_name: "support-triage",
          status: "completed",
          trace_id: "trace_1",
          error: null,
          started_at: "2026-05-07T00:00:00Z",
          updated_at: "2026-05-07T00:00:01Z",
          completed_at: "2026-05-07T00:00:01Z",
        }) as T,
      "run_1",
    );

    expect(run.run_id).toBe("run_1");
    expect(run.trace_id).toBe("trace_1");
  });

  it("cancels and retries workflow runs", async () => {
    const calls: string[] = [];
    const transport = async <T>(path: string): Promise<T> => {
      calls.push(path);
      return {
        run_id: "run_1",
        workflow_name: "support-triage",
        status: path.endsWith("/retry") ? "running" : "cancel_requested",
        trace_id: "trace_1",
        error: null,
        started_at: "2026-05-07T00:00:00Z",
        updated_at: "2026-05-07T00:00:01Z",
        completed_at: null,
      } as T;
    };

    await cancelWorkflowRun(transport, "run_1");
    await retryWorkflowRun(transport, "run_1");

    expect(calls).toEqual(["/workflow-runs/run_1/cancel", "/workflow-runs/run_1/retry"]);
  });

  it("detects active workflow runs", () => {
    expect(isWorkflowRunActive(null)).toBe(false);
    expect(isWorkflowRunActive({ status: "pending" } as never)).toBe(true);
    expect(isWorkflowRunActive({ status: "running" } as never)).toBe(true);
    expect(isWorkflowRunActive({ status: "cancel_requested" } as never)).toBe(true);
    expect(isWorkflowRunActive({ status: "completed" } as never)).toBe(false);
    expect(isWorkflowRunActive({ status: "cancelled" } as never)).toBe(false);
  });
});
