import {
  Activity,
  AlertCircle,
  Bot,
  CheckCircle2,
  FlaskConical,
  GitBranch,
  RotateCcw,
} from "lucide-react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type MouseHandlerDataParam,
} from "recharts";
import { SummaryFact } from "../common/SummaryFact";
import type { EvalRunStatus } from "../../types";
import {
  buildEvalImprovementPlan,
  buildEvalTrendSeries,
  evalCategorySummaries,
  evalCheckCategory,
  evalComparisonStatusLabel,
  evalModeLabel,
  evalModelSummary,
  evalPassRateLabel,
  evalProgress,
  evalRunHasProviderIssue,
  evalRunIsActive,
  evalStatusLabel,
  failedEvalCases,
  failedEvalChecks,
  formatEvalValue,
  type EvalComparison,
  type EvalExecutionMode,
  type EvalRunSummary,
  type EvalSuiteRun,
  type EvalTrendPoint,
} from "../../utils/evals";
import { formatShortTimestamp } from "../../utils/format";

export function EvalDashboardPanel({
  run,
  history,
  comparison,
  status,
  mode,
  onModeChange,
  onRun,
  onResume,
  onSelectEvalRun,
  onSelectTrace,
}: {
  run: EvalSuiteRun | null;
  history: EvalRunSummary[];
  comparison: EvalComparison | null;
  status: EvalRunStatus;
  mode: EvalExecutionMode;
  onModeChange: (mode: EvalExecutionMode) => void;
  onRun: () => Promise<void>;
  onResume: () => Promise<void>;
  onSelectEvalRun: (runId: string) => Promise<void>;
  onSelectTrace: (traceId: string) => void;
}) {
  const failures = failedEvalCases(run);
  const categorySummaries = evalCategorySummaries(run);
  const activeRun = evalRunIsActive(run);
  const running = status.status === "running" || activeRun;
  const progress = evalProgress(run);
  const visibleResults = run ? (failures.length > 0 ? failures : run.results).slice(0, 4) : [];
  const improvementPlan = buildEvalImprovementPlan(run);
  const resumable = Boolean(run && run.execution_mode === "llm" && evalRunHasProviderIssue(run) && run.results.length < run.total);

  return (
    <section className="evalDashboard">
      <div className="evalDashboardHeader">
        <div>
          <small>Evaluation dashboard</small>
          <h2>Support agent quality</h2>
        </div>
        <div className="evalRunControls">
          <select value={mode} onChange={(event) => onModeChange(event.target.value as EvalExecutionMode)} disabled={running}>
            <option value="deterministic">Deterministic baseline</option>
            <option value="llm">Configured LLM</option>
          </select>
          <button type="button" onClick={() => void onRun()} disabled={running}>
            {running ? <Activity size={15} /> : <FlaskConical size={15} />}
            Run evals
          </button>
          {resumable ? (
            <button className="secondary" type="button" onClick={() => void onResume()} disabled={running}>
              <RotateCcw size={15} />
              Resume eval
            </button>
          ) : null}
        </div>
      </div>
      <div className="evalSummaryGrid">
        <SummaryFact icon={<CheckCircle2 size={16} />} label="Status" value={evalStatusLabel(run)} />
        <SummaryFact icon={<Bot size={16} />} label="Mode" value={run ? evalModeLabel(run.execution_mode) : evalModeLabel(mode)} />
        <SummaryFact icon={<Activity size={16} />} label="Pass rate" value={run ? evalPassRateLabel(run.pass_rate) : "-"} />
        <SummaryFact icon={<GitBranch size={16} />} label="Cases" value={run ? (activeRun ? `${progress.completed}/${progress.total}` : `${run.passed}/${run.total}`) : "-"} />
        <SummaryFact icon={<AlertCircle size={16} />} label="Failures" value={run ? String(run.failed) : "-"} />
      </div>
      {activeRun ? (
        <div className="evalProgressPanel" role="status" aria-live="polite">
          <div className="evalProgressHeader">
            <div>
              <strong>LLM eval is running</strong>
              <span>Completed cases appear below as they finish.</span>
            </div>
            <em>{progress.label}</em>
          </div>
          <div className="evalProgressTrack" aria-label={progress.label}>
            <span className="evalProgressBar" style={{ width: `${progress.percent}%` }} />
          </div>
        </div>
      ) : null}
      <div className="evalCategoryStrip">
        {categorySummaries.map((summary) => (
          <span className={summary.failed > 0 ? "failed" : "passed"} key={summary.category}>
            {summary.category} <strong>{summary.failed}</strong>
          </span>
        ))}
      </div>
      <EvalTrendChart history={history} selectedRunId={run?.run_id ?? null} onSelectEvalRun={onSelectEvalRun} />
      <div
        className={
          comparison?.status === "degraded_llm" || evalRunHasProviderIssue(comparison?.llm_run ?? null)
            ? "evalComparison degraded"
            : comparison?.status === "ready" && comparison.llm_regressions.length > 0
              ? "evalComparison drift"
              : "evalComparison"
        }
      >
        <div>
          <small>Deterministic vs LLM</small>
          <strong>{evalComparisonStatusLabel(comparison)}</strong>
        </div>
        <span>
          Delta <strong>{evalRunHasProviderIssue(comparison?.llm_run ?? null) ? "degraded" : comparison?.pass_rate_delta === null || comparison?.pass_rate_delta === undefined ? "-" : `${Math.round(comparison.pass_rate_delta * 100)} pts`}</strong>
        </span>
        <span>
          Regressions <strong>{evalRunHasProviderIssue(comparison?.llm_run ?? null) ? "not scored" : comparison?.llm_regressions.length ?? "-"}</strong>
        </span>
        <span>
          Model <strong>{comparison?.llm_run ? `${comparison.llm_run.model_provider}/${comparison.llm_run.model_name}` : "-"}</strong>
        </span>
      </div>
      {status.status === "error" ? <p className="evalError">{status.message}</p> : null}
      {run && visibleResults.length > 0 ? (
        <div className="evalCases">
          {visibleResults.map((result) => (
            <div className={result.passed ? "evalCaseCard passed" : "evalCaseCard failed"} key={result.case_id}>
              <button type="button" onClick={() => onSelectTrace(result.trace_id)}>
                <span>{result.name}</span>
                <strong>{Math.round(result.score * 100)}%</strong>
              </button>
              {evalModelSummary(result) ? <EvalModelBadge result={result} /> : null}
              {!result.passed ? (
                <div className="evalCheckDetails">
                  {failedEvalChecks(result).slice(0, 3).map((check) => (
                    <div key={check.name}>
                      <small>{evalCheckCategory(check.name)}</small>
                      <strong>{check.name}</strong>
                      <span>Expected: {formatEvalValue(check.expected)}</span>
                      <span>Actual: {formatEvalValue(check.actual)}</span>
                    </div>
                  ))}
                  {failedEvalChecks(result).length > 3 ? <em>{failedEvalChecks(result).length - 3} more failed checks</em> : null}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ) : activeRun ? (
        <p className="evalEmpty">Waiting for the first case result...</p>
      ) : (
        <p className="evalEmpty">Run the deterministic suite to check routing, approvals, memory, and tool failures.</p>
      )}
      {improvementPlan.length > 0 ? (
        <div className="evalImprovementPlan">
          <div className="evalImprovementHeader">
            <small>Improvement plan</small>
            <strong>Use failures to patch the agent</strong>
          </div>
          {improvementPlan.slice(0, 4).map((item) => (
            <article className="evalImprovementItem" key={item.category}>
              <div>
                <span>{item.category}</span>
                <strong>{item.owner_area}</strong>
                <p>{item.recommended_action}</p>
              </div>
              <div className="evalImprovementFiles">
                {item.suggested_files.map((file) => (
                  <code key={file}>{file}</code>
                ))}
              </div>
              <div className="evalImprovementCases">
                {item.cases.slice(0, 3).map((failure) => (
                  <button key={`${failure.case_id}-${failure.check}`} type="button" onClick={() => onSelectTrace(failure.trace_id)}>
                    <span>{failure.case_id}</span>
                    <strong>{failure.check}</strong>
                    <em>
                      {formatEvalValue(failure.expected)} {"->"} {formatEvalValue(failure.actual)}
                    </em>
                  </button>
                ))}
                {item.cases.length > 3 ? <em>{item.cases.length - 3} more failed checks</em> : null}
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {history.length > 0 ? (
        <div className="evalHistory">
          <small>Recent eval runs</small>
          {history.map((item) => (
            <button
              aria-current={run?.run_id === item.run_id ? "true" : undefined}
              className={item.failed === 0 ? "passed" : "failed"}
              key={item.run_id}
              onClick={() => void onSelectEvalRun(item.run_id)}
              type="button"
            >
              <span>{formatShortTimestamp(item.created_at)}</span>
              <strong>{evalPassRateLabel(item.pass_rate)}</strong>
              <em>{evalModeLabel(item.execution_mode)}</em>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function EvalTrendChart({
  history,
  selectedRunId,
  onSelectEvalRun,
}: {
  history: EvalRunSummary[];
  selectedRunId: string | null;
  onSelectEvalRun: (runId: string) => Promise<void>;
}) {
  const series = buildEvalTrendSeries(history);
  const totalRuns = series.deterministic.length + series.llm.length;
  if (totalRuns === 0) {
    return null;
  }

  return (
    <div className="evalTrendPanel">
      <div className="evalTrendHeader">
        <div>
          <small>Eval trend</small>
          <strong>Recent pass rate by mode</strong>
        </div>
        <span>{totalRuns} runs</span>
      </div>
      <div className="evalTrendSeriesGrid">
        <EvalTrendSeriesChart
          mode="deterministic"
          points={series.deterministic}
          selectedRunId={selectedRunId}
          onSelectEvalRun={onSelectEvalRun}
        />
        <EvalTrendSeriesChart mode="llm" points={series.llm} selectedRunId={selectedRunId} onSelectEvalRun={onSelectEvalRun} />
      </div>
      <div className="evalTrendMeta">
        {[...series.deterministic, ...series.llm]
          .sort((left, right) => new Date(left.createdAt).getTime() - new Date(right.createdAt).getTime())
          .slice(-4)
          .map((point) => (
            <button
              aria-current={selectedRunId === point.runId ? "true" : undefined}
              key={point.runId}
              onClick={() => void onSelectEvalRun(point.runId)}
              type="button"
            >
              <span>{formatShortTimestamp(point.createdAt)}</span>
              <strong>{point.passRate}%</strong>
              <em>{evalModeLabel(point.mode)}</em>
            </button>
          ))}
      </div>
    </div>
  );
}

function EvalTrendSeriesChart({
  mode,
  points,
  selectedRunId,
  onSelectEvalRun,
}: {
  mode: EvalExecutionMode;
  points: EvalTrendPoint[];
  selectedRunId: string | null;
  onSelectEvalRun: (runId: string) => Promise<void>;
}) {
  function handleChartClick(event: MouseHandlerDataParam) {
    const point = points.find((item) => item.label === event.activeLabel);
    if (point) {
      void onSelectEvalRun(point.runId);
    }
  }

  const latest = points.at(-1);
  return (
    <div className={mode === "llm" ? "evalTrendSeries llm" : "evalTrendSeries"}>
      <div className="evalTrendSeriesHeader">
        <strong>{evalModeLabel(mode)}</strong>
        <span>{latest ? `${latest.passRate}% latest` : "No runs"}</span>
      </div>
      {points.length > 0 ? (
        <div className="evalTrendChart" role="img" aria-label={`${evalModeLabel(mode)} eval pass-rate trend`}>
          <ResponsiveContainer width="100%" height={150}>
            <LineChart data={points} margin={{ top: 12, right: 10, bottom: 0, left: -20 }} onClick={handleChartClick}>
              <CartesianGrid stroke="#edf1f3" vertical={false} />
              <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "#637179", fontSize: 11 }} />
              <YAxis domain={[0, 100]} tickLine={false} axisLine={false} tick={{ fill: "#637179", fontSize: 11 }} tickFormatter={(value) => `${value}%`} />
              <Tooltip content={<EvalTrendTooltip />} cursor={{ stroke: "#9bb7af", strokeWidth: 1 }} />
              <Line
                type="monotone"
                dataKey="passRate"
                stroke={mode === "llm" ? "#6f4ab8" : "#246b5b"}
                strokeWidth={2}
                dot={{ r: 4, strokeWidth: 2, fill: "#ffffff" }}
                activeDot={{
                  r: 6,
                  strokeWidth: 2,
                  fill: selectedRunId === latest?.runId ? "#172026" : mode === "llm" ? "#6f4ab8" : "#246b5b",
                  cursor: "pointer",
                }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <p className="evalTrendEmpty">Run {evalModeLabel(mode).toLowerCase()} evals to start this trend.</p>
      )}
    </div>
  );
}

function EvalTrendTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload?: EvalTrendPoint }> }) {
  const point = payload?.[0]?.payload;
  if (!active || !point) {
    return null;
  }
  return (
    <div className="evalTrendTooltip">
      <small>{formatShortTimestamp(point.createdAt)}</small>
      <strong>{point.passRate}% pass rate</strong>
      <span>
        {point.passed}/{point.total} passed, {point.failed} failed
      </span>
      <em>
        {evalModeLabel(point.mode)} · {point.model}
      </em>
    </div>
  );
}

function EvalModelBadge({ result }: { result: EvalSuiteRun["results"][number] }) {
  const event = evalModelSummary(result);
  if (!event) {
    return null;
  }
  const failedAttempt = event.attempts?.find((attempt) => attempt.status === "failed");
  return (
    <div className={event.fallback_used ? "evalModelBadge fallback" : "evalModelBadge"}>
      <span>{event.span_name}</span>
      <strong>{event.model ?? "model unknown"}</strong>
      {event.fallback_used ? <em>Fallback used{failedAttempt?.model ? ` after ${failedAttempt.model}` : ""}</em> : null}
    </div>
  );
}
