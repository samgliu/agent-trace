import React, { useState } from "react";
import { AlertCircle, ArrowRight, Braces, CircleDollarSign, GitPullRequestArrow, RotateCcw, ShieldCheck, UserCheck, Wrench } from "lucide-react";
import type { ApprovalAction, GroundingSummary, Metrics, Span } from "../../types";
import { extractAgentContract, formatAgentContractStatus, type AgentContract } from "../../utils/agentContract";
import { getApprovalStatus, type ApprovalStatus } from "../../utils/approval";
import { canManageApprovals, type AuthRole } from "../../utils/authz";
import { extractUnsupportedClaims } from "../../utils/claims";
import { formatShortTimestamp } from "../../utils/format";
import { buildMemorySummary, type MemorySummary } from "../../utils/memoryAnalysis";
import { buildSpanFacts } from "../../utils/spanFacts";
import { extractValidatorReport, type ValidatorReport } from "../../utils/validationReport";

export function AnalysisPanel({
  metrics,
  grounding,
  spans,
  rawTrace,
  authRole,
  selectedSpanId,
  onSelectSpan,
  onApprovalAction,
}: {
  metrics: Metrics;
  grounding: GroundingSummary;
  spans: Span[];
  rawTrace: unknown;
  authRole: AuthRole | null;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const mcpSpans = spans.filter((span) => span.span_data.tool_protocol === "mcp");
  const guardrails = spans.filter((span) => span.span_type === "guardrail" || span.span_type === "validation");
  const approvals = spans.filter((span) => span.span_type === "approval");
  const escalations = spans.filter((span) => span.name === "Escalation Agent" || span.span_data.agent_role === "escalation");
  const pendingApprovals = approvals.filter((span) => getApprovalStatus(span.span_type, span.span_data)?.isPending);
  const handoffs = spans.filter((span) => span.span_type === "handoff");
  const memorySpans = spans.filter((span) => span.span_type === "memory_read" || span.span_type === "memory_write");
  const memoryReads = memorySpans.filter((span) => span.span_type === "memory_read").length;
  const memoryWrites = memorySpans.filter((span) => span.span_type === "memory_write").length;
  const memorySummary = buildMemorySummary(spans);
  const erroredSpans = spans.filter((span) => span.error);
  const selectedSpan = spans.find((span) => span.span_id === selectedSpanId) ?? spans[0];
  const approvalActionsEnabled = canManageApprovals(authRole);

  return (
    <section className="panel analysisPanel">
      <div className="panelHeader">
        <h3>Analysis</h3>
        <span>{metrics.span_count} events</span>
      </div>
      <div className="analysisList">
        <Insight
          icon={<ShieldCheck size={16} />}
          label="Grounding"
          value={`${grounding.status} · ${grounding.unsupported_claim_count} unsupported`}
        />
        <Insight icon={<ArrowRight size={16} />} label="Handoffs" value={`${handoffs.length} supervisor routes`} />
        <Insight icon={<Wrench size={16} />} label="MCP tools" value={`${mcpSpans.length} calls captured`} />
        <Insight icon={<Braces size={16} />} label="Memory" value={`${memoryReads} reads · ${memoryWrites} writes`} />
        <Insight icon={<ShieldCheck size={16} />} label="Guardrails" value={`${guardrails.length} validation span`} />
        <Insight icon={<UserCheck size={16} />} label="Approvals" value={`${pendingApprovals.length} waiting · ${approvals.length} total`} />
        <Insight icon={<GitPullRequestArrow size={16} />} label="Escalations" value={`${escalations.length} handoff`} />
        <Insight icon={<AlertCircle size={16} />} label="Errors" value={`${erroredSpans.length} errored span`} />
        <Insight icon={<CircleDollarSign size={16} />} label="Most expensive" value={metrics.most_expensive_span?.name ?? "-"} />
      </div>
      <ApprovalQueue
        approvals={approvals}
        canManageApprovals={approvalActionsEnabled}
        onSelectSpan={onSelectSpan}
        onApprovalAction={onApprovalAction}
      />
      <EscalationPanel escalations={escalations} onSelectSpan={onSelectSpan} />
      <GroundingPanel grounding={grounding} onSelectSpan={onSelectSpan} />
      <MemoryPanel summary={memorySummary} onSelectSpan={onSelectSpan} />
      <div className="typeBreakdown">
        {Object.entries(metrics.spans_by_type).map(([type, count]) => (
          <div key={type} className="typeBar">
            <span>{type}</span>
            <div>
              <i style={{ width: `${Math.max(8, count * 18)}px` }} />
            </div>
            <strong>{count}</strong>
          </div>
        ))}
      </div>
      {mcpSpans.length > 0 ? (
        <div className="quickLinks">
          <small>MCP tool calls</small>
          {mcpSpans.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {memorySpans.length > 0 ? (
        <div className="quickLinks">
          <small>Memory events</small>
          {memorySpans.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {erroredSpans.length > 0 ? (
        <div className="quickLinks errorLinks">
          <small>Errored spans</small>
          {erroredSpans.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {guardrails.length > 0 ? (
        <div className="quickLinks">
          <small>Guardrails and validation</small>
          {guardrails.map((span) => (
            <button key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
              {span.name}
            </button>
          ))}
        </div>
      ) : null}
      {selectedSpan ? (
        <SpanDetail
          span={selectedSpan}
          rawTrace={rawTrace}
          canManageApprovals={approvalActionsEnabled}
          onApprovalAction={onApprovalAction}
        />
      ) : null}
    </section>
  );
}

function ApprovalQueue({
  approvals,
  canManageApprovals,
  onSelectSpan,
  onApprovalAction,
}: {
  approvals: Span[];
  canManageApprovals: boolean;
  onSelectSpan: (spanId: string) => void;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  if (approvals.length === 0) {
    return null;
  }

  return (
    <section className="approvalQueue" aria-label="Approval gates">
      <div className="approvalQueueHeader">
        <div>
          <strong>Approval gates</strong>
          <small>{approvals.length} human checkpoint in this trace</small>
        </div>
        <UserCheck size={18} />
      </div>
      {approvals.map((span) => {
        const status = getApprovalStatus(span.span_type, span.span_data);
        if (!status) return null;
        return (
          <div className={status.isPending ? "approvalQueueItem pending" : "approvalQueueItem"} key={span.span_id}>
            <button className="approvalQueueTitle" onClick={() => onSelectSpan(span.span_id)}>
              <strong>{span.name}</strong>
              <span>{status.approvalStatus}</span>
            </button>
            <div className="approvalQueueMeta">
              <span>{status.riskLevel ?? "risk unknown"}</span>
              <span>{status.permissionScope ?? "scope unknown"}</span>
            </div>
            <ApprovalActions
              spanId={span.span_id}
              status={status}
              canManageApprovals={canManageApprovals}
              onApprovalAction={onApprovalAction}
            />
            <ApprovalHistory status={status} />
          </div>
        );
      })}
    </section>
  );
}

function EscalationPanel({ escalations, onSelectSpan }: { escalations: Span[]; onSelectSpan: (spanId: string) => void }) {
  if (escalations.length === 0) {
    return null;
  }

  return (
    <section className="escalationPanel" aria-label="Escalation handoffs">
      <div className="escalationHeader">
        <div>
          <strong>Escalation handoffs</strong>
          <small>{escalations.length} automation stop in this trace</small>
        </div>
        <GitPullRequestArrow size={18} />
      </div>
      {escalations.map((span) => {
        const output = objectValue(span.output);
        const escalationType = stringValue(output?.escalation_type) ?? stringValue(span.span_data.escalation_type) ?? "human_review";
        const nextOwner = stringValue(output?.next_owner) ?? stringValue(span.span_data.next_owner) ?? "unassigned";
        const reason = stringValue(output?.reason) ?? "Manual review required.";
        const handoffSummary = stringValue(output?.handoff_summary);
        const evidence = Array.isArray(output?.evidence) ? output.evidence.map(String) : [];
        return (
          <button className="escalationItem" key={span.span_id} onClick={() => onSelectSpan(span.span_id)}>
            <span>{escalationType.replaceAll("_", " ")}</span>
            <strong>{nextOwner.replaceAll("_", " ")}</strong>
            <small>{reason}</small>
            {handoffSummary ? <em>{handoffSummary}</em> : null}
            {evidence.length > 0 ? <i>{evidence.slice(0, 4).join(" · ")}</i> : null}
          </button>
        );
      })}
    </section>
  );
}

function GroundingPanel({
  grounding,
  onSelectSpan,
}: {
  grounding: GroundingSummary;
  onSelectSpan: (spanId: string) => void;
}) {
  if (grounding.validation_span_count === 0) {
    return null;
  }

  return (
    <div className={grounding.unsupported_claim_count > 0 ? "groundingPanel warning" : "groundingPanel"}>
      <div className="groundingHeader">
        <strong>Grounding summary</strong>
        <span>{grounding.recovered ? "Recovered" : grounding.status}</span>
      </div>
      {grounding.unsupported_claims.length > 0 ? (
        <div className="groundingClaims">
          <small>Unsupported claims</small>
          {grounding.unsupported_claims.map((claim, index) => (
            <button key={`${claim.span_id}-${index}`} onClick={() => onSelectSpan(claim.span_id)}>
              <strong>{claim.claim}</strong>
              <span>{claim.reason ?? claim.span_name}</span>
            </button>
          ))}
        </div>
      ) : (
        <p className="groundingOk">No unsupported claims detected.</p>
      )}
    </div>
  );
}

function MemoryPanel({ summary, onSelectSpan }: { summary: MemorySummary; onSelectSpan: (spanId: string) => void }) {
  if (summary.readCount + summary.writeCount === 0) {
    return null;
  }

  return (
    <div className={summary.warnings.length > 0 ? "memoryPanel warning" : "memoryPanel"}>
      <div className="memoryHeader">
        <strong>Memory analysis</strong>
        <span>{summary.warnings.length > 0 ? `${summary.warnings.length} warning` : "Healthy"}</span>
      </div>
      <div className="memoryStats">
        <span>Reads <strong>{summary.readCount}</strong></span>
        <span>Writes <strong>{summary.writeCount}</strong></span>
        <span>Retrieved <strong>{summary.retrievedCount}</strong></span>
        <span>Relevance <strong>{summary.averageRelevance === null ? "-" : summary.averageRelevance.toFixed(2)}</strong></span>
        <span>Used <strong>{summary.usedCount}</strong></span>
        <span>Ignored <strong>{summary.ignoredCount}</strong></span>
      </div>
      {summary.stores.length > 0 ? (
        <div className="memoryStores">
          <small>Stores</small>
          <span>{summary.stores.join(" · ")}</span>
        </div>
      ) : null}
      {summary.warnings.length > 0 ? (
        <div className="memoryWarnings">
          <small>Warnings</small>
          {summary.warnings.map((warning, index) => (
            <button className={warning.tone} key={`${warning.spanId}-${warning.label}-${index}`} onClick={() => onSelectSpan(warning.spanId)}>
              <strong>{warning.label}</strong>
              <span>{warning.detail}</span>
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function SpanDetail({
  span,
  rawTrace,
  canManageApprovals,
  onApprovalAction,
}: {
  span: Span;
  rawTrace: unknown;
  canManageApprovals: boolean;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const [activeTab, setActiveTab] = useState<"overview" | "span" | "trace">("overview");
  const unsupportedClaims = extractUnsupportedClaims(span.output);
  const approvalStatus = getApprovalStatus(span.span_type, span.span_data);
  const facts = buildSpanFacts(span);
  const modelOutputText = typeof span.span_data.model_output_text === "string" ? span.span_data.model_output_text : null;
  const validatorReport = extractValidatorReport(span.output);
  const agentContract = extractAgentContract(span.span_data);

  return (
    <div className="spanDetail">
      <div className="spanDetailHeader">
        <div>
          <small>Selected span</small>
          <strong>{span.name}</strong>
        </div>
        <span>{span.span_type}</span>
      </div>

      <div className="spanFacts">
        {facts.map((fact) => (
          <div key={fact.label}>
            <small>{fact.label}</small>
            <strong>{fact.value}</strong>
          </div>
        ))}
      </div>

      <div className="inspectorTabs" role="tablist" aria-label="Span inspector">
        <button className={activeTab === "overview" ? "active" : ""} onClick={() => setActiveTab("overview")}>
          Overview
        </button>
        <button className={activeTab === "span" ? "active" : ""} onClick={() => setActiveTab("span")}>
          Span JSON
        </button>
        <button className={activeTab === "trace" ? "active" : ""} onClick={() => setActiveTab("trace")}>
          Raw trace
        </button>
      </div>

      {activeTab === "overview" ? (
        <>
          {unsupportedClaims.length > 0 ? (
            <div className="claimAlert">
              <strong>Unsupported claims</strong>
              {unsupportedClaims.map((claim, index) => (
                <p key={`${claim.claim}-${index}`}>
                  {claim.claim}
                  {claim.reason ? <span>{claim.reason}</span> : null}
                </p>
              ))}
            </div>
          ) : null}

          {approvalStatus ? (
            <ApprovalNotice
              spanId={span.span_id}
              status={approvalStatus}
              canManageApprovals={canManageApprovals}
              onApprovalAction={onApprovalAction}
            />
          ) : null}

          {validatorReport ? <ValidatorReportCard report={validatorReport} /> : null}
          {agentContract ? <AgentContractCard contract={agentContract} /> : null}
          {modelOutputText ? <JsonBlock label="Model output" value={modelOutputText} /> : null}
          <JsonBlock label="Input" value={span.input} />
          <JsonBlock label="Output" value={span.output} />
          <JsonBlock label="Metadata" value={span.span_data} />
          {span.error ? <JsonBlock label="Error" value={span.error} /> : null}
        </>
      ) : null}

      {activeTab === "span" ? <JsonBlock label="Normalized span" value={span} /> : null}
      {activeTab === "trace" ? <JsonBlock label="Original trace payload" value={rawTrace} /> : null}
    </div>
  );
}

function AgentContractCard({ contract }: { contract: AgentContract }) {
  return (
    <div className={`agentContractCard ${contract.status}`}>
      <div className="agentContractHeader">
        <strong>Agent contract</strong>
        <span>{formatAgentContractStatus(contract.status)}</span>
      </div>
      <div className="agentContractGrid">
        <ContractList label="Required inputs" values={contract.requiredInputs} />
        <ContractList label="Consumed context" values={contract.consumedContext} />
        <ContractList label="Produced outputs" values={contract.producedOutputs} />
      </div>
      {contract.validationReason || contract.corrections.length > 0 ? (
        <div className="agentContractCorrections">
          {contract.validationReason ? (
            <>
              <small>Validation reason</small>
              <p>{contract.validationReason.replaceAll("_", " ")}</p>
            </>
          ) : null}
          {contract.corrections.length > 0 ? (
            <>
              <small>Corrections</small>
              <p>{contract.corrections.join(", ").replaceAll("_", " ")}</p>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function ContractList({ label, values }: { label: string; values: string[] }) {
  return (
    <div>
      <small>{label}</small>
      {values.length > 0 ? (
        <ul>
          {values.map((value) => (
            <li key={value}>{value.replaceAll("_", " ")}</li>
          ))}
        </ul>
      ) : (
        <p>none</p>
      )}
    </div>
  );
}

function ValidatorReportCard({ report }: { report: ValidatorReport }) {
  return (
    <div className="validatorReport">
      <div className="validatorReportHeader">
        <strong>Validator report</strong>
        <span className={report.customerSafeToSend ? "safe" : "blocked"}>
          {report.customerSafeToSend ? "Safe to send" : "Needs control"}
        </span>
      </div>
      <div className="validatorReportGrid">
        <ReportFact label="Grounding" value={report.groundingStatus} />
        <ReportFact label="Policy" value={report.policyStatus} />
        <ReportFact label="Approval" value={report.approvalRequired ? "required" : "not required"} />
        <ReportFact label="Risk review" value={report.riskReviewRequired ? "required" : "not required"} />
        <ReportFact label="Unsupported" value={String(report.unsupportedClaimCount)} />
        <ReportFact label="Missing evidence" value={report.missingEvidence.length > 0 ? report.missingEvidence.join(", ") : "none"} />
      </div>
      {report.validatorCorrections.length > 0 ? (
        <div className="validatorCorrections">
          <small>Corrections</small>
          <p>{report.validatorCorrections.join(", ")}</p>
        </div>
      ) : null}
    </div>
  );
}

function ReportFact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <small>{label}</small>
      <strong>{value}</strong>
    </div>
  );
}

function ApprovalNotice({
  spanId,
  status,
  canManageApprovals,
  onApprovalAction,
}: {
  spanId: string;
  status: ApprovalStatus;
  canManageApprovals: boolean;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  return (
    <div className="approvalNotice">
      <strong>Approval required</strong>
      <dl>
        <div>
          <dt>Status</dt>
          <dd>{status.approvalStatus}</dd>
        </div>
        <div>
          <dt>Risk</dt>
          <dd>{status.riskLevel ?? "-"}</dd>
        </div>
        <div>
          <dt>Scope</dt>
          <dd>{status.permissionScope ?? "-"}</dd>
        </div>
        <div>
          <dt>Decision</dt>
          <dd>{status.decisionAction ?? "-"}</dd>
        </div>
        <div>
          <dt>Actor</dt>
          <dd>{formatDecisionActor(status)}</dd>
        </div>
        <div>
          <dt>Decided</dt>
          <dd>{status.decisionAt ? formatShortTimestamp(status.decisionAt) : "-"}</dd>
        </div>
      </dl>
      <ApprovalActions
        spanId={spanId}
        status={status}
        canManageApprovals={canManageApprovals}
        onApprovalAction={onApprovalAction}
      />
      <ApprovalHistory status={status} />
      <small>{canManageApprovals ? "Approval decisions are retained on the approval span." : "Operator role required to change approvals."}</small>
    </div>
  );
}

function ApprovalHistory({ status }: { status: ApprovalStatus }) {
  return (
    <section className="approvalHistory" aria-label="Decision history">
      <strong>Decision history</strong>
      {status.decisionHistory.length === 0 ? (
        <p>No recorded decisions yet.</p>
      ) : (
        <ol>
          {status.decisionHistory.map((decision, index) => (
            <li key={`${decision.decisionAt}-${decision.decisionAction}-${index}`}>
              <div>
                <b>{decision.decisionAction}</b>
                <span>{decision.decisionActor ? `${decision.decisionActor.displayName} (${decision.decisionActor.role})` : "Unknown actor"}</span>
              </div>
              <time dateTime={decision.decisionAt}>{formatShortTimestamp(decision.decisionAt)}</time>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function formatDecisionActor(status: ApprovalStatus): string {
  if (!status.decisionActor) {
    return "-";
  }
  return `${status.decisionActor.displayName} (${status.decisionActor.role})`;
}

function ApprovalActions({
  spanId,
  status,
  canManageApprovals,
  onApprovalAction,
}: {
  spanId: string;
  status: ApprovalStatus;
  canManageApprovals: boolean;
  onApprovalAction: (spanId: string, action: ApprovalAction) => Promise<void>;
}) {
  const isApproved = status.approvalStatus === "approved";
  const isRejected = status.approvalStatus === "rejected";
  const disabledTitle = canManageApprovals ? undefined : "Operator role required";

  return (
    <div className="approvalActions">
      <button
        className="approveButton"
        disabled={!canManageApprovals || isApproved}
        title={disabledTitle}
        onClick={() => void onApprovalAction(spanId, "approve")}
      >
        <UserCheck size={15} />
        Approve
      </button>
      <button
        className="rejectButton"
        disabled={!canManageApprovals || isRejected}
        title={disabledTitle}
        onClick={() => void onApprovalAction(spanId, "reject")}
      >
        <AlertCircle size={15} />
        Reject
      </button>
      <button
        className="revertButton"
        disabled={!canManageApprovals || !status.isResolved}
        title={disabledTitle}
        onClick={() => void onApprovalAction(spanId, "revert")}
      >
        <RotateCcw size={15} />
        Revert
      </button>
    </div>
  );
}

function JsonBlock({ label, value }: { label: string; value: unknown }) {
  const displayValue = value === null || value === undefined ? "-" : typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return (
    <div className="jsonBlock">
      <small>{label}</small>
      <pre>{displayValue}</pre>
    </div>
  );
}

function Insight({ icon, label, value }: { icon: React.ReactNode; label: string; value: string }) {
  return (
    <div className="insight">
      <div className="insightIcon">{icon}</div>
      <div>
        <small>{label}</small>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function objectValue(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}
