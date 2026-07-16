import { useCallback, useState } from "react";
import type { TraceDetail, LiveWorkflowInput } from "../types";
import { apiPostJson, fetchJson } from "../utils/apiClient";
import {
  cancelWorkflowRun,
  getWorkflowRun,
  retryWorkflowRun,
  startSupportTriageLiveRun,
  type WorkflowRun,
} from "../utils/workflowRuns";

type TraceSelection = {
  traceId: string;
  spanId: string | null;
};

type UseLiveWorkflowRunOptions = {
  onRefresh: () => void;
  onSelectTrace: (selection: TraceSelection) => void;
};

export function useLiveWorkflowRun({ onRefresh, onSelectTrace }: UseLiveWorkflowRunOptions) {
  const [run, setRun] = useState<WorkflowRun<TraceDetail> | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selectRunTrace = useCallback(
    (nextRun: WorkflowRun<TraceDetail>) => {
      if (!nextRun.trace_id) {
        return;
      }
      onSelectTrace({
        traceId: nextRun.trace_id,
        spanId: nextRun.trace?.spans[0]?.span_id ?? null,
      });
    },
    [onSelectTrace],
  );

  const refreshRun = useCallback(
    async (runId: string) => {
      try {
        const nextRun = await getWorkflowRun<TraceDetail>(fetchJson, runId);
        setRun(nextRun);
        selectRunTrace(nextRun);
        if (nextRun.status === "failed") {
          setError(nextRun.error ?? "Workflow run failed.");
        }
      } catch (refreshError) {
        setError(refreshError instanceof Error ? refreshError.message : "Could not refresh workflow run.");
      }
    },
    [selectRunTrace],
  );

  const start = useCallback(
    async (input: LiveWorkflowInput) => {
      setError(null);
      try {
        const nextRun = await startSupportTriageLiveRun<TraceDetail>(apiPostJson, {
          message: input.message,
          customerEmail: input.customerEmail,
          llmProvider: input.llmProvider,
        });
        setRun(nextRun);
        selectRunTrace(nextRun);
        onRefresh();
      } catch (startError) {
        setError(startError instanceof Error ? startError.message : "Could not start workflow run.");
      }
    },
    [onRefresh, selectRunTrace],
  );

  const cancel = useCallback(async () => {
    if (!run) {
      return;
    }
    setError(null);
    try {
      const nextRun = await cancelWorkflowRun<TraceDetail>(apiPostJson, run.run_id);
      setRun(nextRun);
      onRefresh();
    } catch (cancelError) {
      setError(cancelError instanceof Error ? cancelError.message : "Could not cancel workflow run.");
    }
  }, [onRefresh, run]);

  const retry = useCallback(async () => {
    if (!run) {
      return;
    }
    setError(null);
    try {
      const nextRun = await retryWorkflowRun<TraceDetail>(apiPostJson, run.run_id);
      setRun(nextRun);
      selectRunTrace(nextRun);
      onRefresh();
    } catch (retryError) {
      setError(retryError instanceof Error ? retryError.message : "Could not retry workflow run.");
    }
  }, [onRefresh, run, selectRunTrace]);

  return {
    run,
    runId: run?.run_id ?? null,
    error,
    start,
    cancel,
    retry,
    refreshRun,
  };
}
