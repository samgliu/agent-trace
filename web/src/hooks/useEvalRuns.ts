import { useCallback, useEffect, useState } from "react";
import { apiPostJson, fetchJson } from "../utils/apiClient";
import {
  getEvalRun,
  getSupportTriageEvalComparison,
  getSupportTriageEvalFailureTrends,
  listEvalRuns,
  resumeEvalRun,
  runSupportTriageEvalSuite,
  startSupportTriageEvalSuite,
  type EvalComparison,
  type EvalExecutionMode,
  type EvalFailureTrends,
  type EvalRunSummary,
  type EvalSuiteRun,
} from "../utils/evals";
import type { EvalRunStatus } from "../types";

export function useEvalRuns(onRefresh: () => void) {
  const [run, setRun] = useState<EvalSuiteRun | null>(null);
  const [history, setHistory] = useState<EvalRunSummary[]>([]);
  const [comparison, setComparison] = useState<EvalComparison | null>(null);
  const [failureTrends, setFailureTrends] = useState<EvalFailureTrends | null>(null);
  const [status, setStatus] = useState<EvalRunStatus>({ status: "idle" });
  const [mode, setMode] = useState<EvalExecutionMode>("deterministic");

  const loadRuns = useCallback(async () => {
    try {
      const nextHistory = await listEvalRuns(fetchJson);
      setHistory(nextHistory.items);
      setComparison(await getSupportTriageEvalComparison(fetchJson));
      setFailureTrends(await getSupportTriageEvalFailureTrends(fetchJson, "llm"));
    } catch {
      setHistory([]);
      setComparison(null);
      setFailureTrends(null);
    }
  }, []);

  const loadRun = useCallback(async (runId: string) => {
    try {
      const nextRun = await getEvalRun(fetchJson, runId);
      setRun(nextRun);
      setMode(nextRun.execution_mode);
      if (nextRun.error) {
        setStatus({ status: "error", message: nextRun.error });
      } else {
        setStatus(nextRun.status === "running" ? { status: "running" } : { status: "idle" });
      }
    } catch {
      // Keep the current eval state during transient SSE refresh races.
    }
  }, []);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  const runEvals = useCallback(async () => {
    setStatus({ status: "running" });
    try {
      const result =
        mode === "llm"
          ? await startSupportTriageEvalSuite(apiPostJson, mode)
          : await runSupportTriageEvalSuite(apiPostJson, mode);
      setRun(result);
      setMode(result.execution_mode);
      setHistory((items) => [result, ...items.filter((item) => item.run_id !== result.run_id)].slice(0, 5));
      setComparison(await getSupportTriageEvalComparison(fetchJson));
      setFailureTrends(await getSupportTriageEvalFailureTrends(fetchJson, "llm"));
      setStatus(result.status === "running" ? { status: "running" } : { status: "idle" });
      onRefresh();
    } catch (error) {
      setStatus({ status: "error", message: error instanceof Error ? error.message : "Could not run evals." });
    }
  }, [mode, onRefresh]);

  const resumeEvals = useCallback(async () => {
    if (!run) {
      return;
    }
    setStatus({ status: "running" });
    try {
      const result = await resumeEvalRun(apiPostJson, run.run_id);
      setRun(result);
      setMode(result.execution_mode);
      setHistory((items) => [result, ...items.filter((item) => item.run_id !== result.run_id)].slice(0, 5));
      setComparison(await getSupportTriageEvalComparison(fetchJson));
      setFailureTrends(await getSupportTriageEvalFailureTrends(fetchJson, "llm"));
      setStatus(result.status === "running" ? { status: "running" } : { status: "idle" });
      onRefresh();
    } catch (error) {
      setStatus({ status: "error", message: error instanceof Error ? error.message : "Could not resume evals." });
    }
  }, [onRefresh, run]);

  return {
    run,
    history,
    comparison,
    failureTrends,
    status,
    mode,
    setMode,
    loadRun,
    loadRuns,
    runEvals,
    resumeEvals,
  };
}
