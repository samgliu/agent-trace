import React, { useMemo } from "react";
import { Activity, ArrowRight, Bot, Braces, MessageSquare, Network, ShieldCheck, UserCheck, Wrench } from "lucide-react";
import type { Span } from "../../types";
import { getApprovalStatus } from "../../utils/approval";
import { buildAgentFlow, type AgentFlowStep } from "../../utils/agentFlow";
import { formatCost, formatDuration, formatTokens } from "../../utils/format";

type SpanNode = {
  span: Span;
  children: SpanNode[];
};

export function TraceTimeline({
  spans,
  selectedSpanId,
  onSelectSpan,
}: {
  spans: Span[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
}) {
  const rootSpans = useMemo(() => buildSpanTree(spans), [spans]);

  return (
    <section className="panel timelinePanel">
      <div className="panelHeader">
        <h3>Trace Timeline</h3>
        <span>{spans.length} spans</span>
      </div>
      <div className="timeline">
        {rootSpans.map((node) => (
          <SpanRow
            key={node.span.span_id}
            node={node}
            depth={0}
            selectedSpanId={selectedSpanId}
            onSelectSpan={onSelectSpan}
          />
        ))}
      </div>
    </section>
  );
}

export function AgentFlowPanel({
  spans,
  selectedSpanId,
  onSelectSpan,
}: {
  spans: Span[];
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
}) {
  const steps = useMemo(() => buildAgentFlow(spans), [spans]);
  if (steps.length === 0) {
    return null;
  }
  return (
    <section className="agentFlowPanel" aria-label="Agent flow">
      <div className="panelHeader">
        <h3>Agent Flow</h3>
        <span>{steps.length} agents</span>
      </div>
      <div className="agentFlow">
        {steps.map((step, index) => (
          <React.Fragment key={step.spanId}>
            <AgentFlowCard
              step={step}
              selected={step.spanId === selectedSpanId}
              onSelectSpan={onSelectSpan}
            />
            {index < steps.length - 1 ? (
              <span className="agentFlowArrow" aria-hidden="true">
                <ArrowRight size={16} />
              </span>
            ) : null}
          </React.Fragment>
        ))}
      </div>
    </section>
  );
}

function AgentFlowCard({
  step,
  selected,
  onSelectSpan,
}: {
  step: AgentFlowStep;
  selected: boolean;
  onSelectSpan: (spanId: string) => void;
}) {
  const decisionSource = formatDecisionSource(step.decisionSource);
  return (
    <button
      className={["agentFlowCard", selected ? "selected" : "", step.approvalPending ? "approvalPending" : "", step.errorCount > 0 ? "errored" : ""]
        .filter(Boolean)
        .join(" ")}
      type="button"
      onClick={() => onSelectSpan(step.spanId)}
    >
      <div className="agentFlowTitle">
        <span>{agentFlowIcon(step.role)}</span>
        <strong>{step.label}</strong>
      </div>
      <div className="agentFlowFacts">
        <span>{formatDuration(step.durationMs)}</span>
        {step.model ? <span>{step.model}</span> : null}
        {decisionSource ? <span>{decisionSource.label}</span> : null}
        {step.tokenTotal > 0 ? <span>{step.tokenTotal} tokens</span> : null}
        {step.estimatedCost ? <span>{formatCost(step.estimatedCost)}</span> : null}
      </div>
      <div className="agentFlowBadges">
        {step.route ? <em>Route: {step.route.replaceAll("_", " ")}</em> : null}
        {step.handoffCount > 0 ? <em>{step.handoffCount} handoff</em> : null}
        {step.toolCount > 0 ? <em>{step.toolCount} tool</em> : null}
        {step.modelFallbackUsed ? <strong>Model fallback</strong> : null}
        {step.approvalPending ? <strong>Approval needed</strong> : null}
        {step.errorCount > 0 ? <strong>{step.errorCount} error</strong> : null}
      </div>
    </button>
  );
}

function SpanRow({
  node,
  depth,
  selectedSpanId,
  onSelectSpan,
}: {
  node: SpanNode;
  depth: number;
  selectedSpanId: string | null;
  onSelectSpan: (spanId: string) => void;
}) {
  const span = node.span;
  const approvalStatus = getApprovalStatus(span.span_type, span.span_data);
  const isEscalation = span.name === "Escalation Agent" || span.span_data.agent_role === "escalation";
  const decisionSource = formatDecisionSource(span.span_data.decision_source);
  const rowClassName = [
    "spanRow",
    span.span_id === selectedSpanId ? "selected" : "",
    approvalStatus?.isPending ? "approvalPending" : "",
    isEscalation ? "escalated" : "",
    span.error ? "errored" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <>
      <button
        className={rowClassName}
        style={{ paddingLeft: `${depth * 22 + 12}px` }}
        onClick={() => onSelectSpan(span.span_id)}
      >
        <span className={`spanType ${span.span_type}`}>{spanIcon(span.span_type)}</span>
        <div className="spanMain">
          <strong>{span.name}</strong>
          <small>{span.span_type}</small>
        </div>
        <div className="spanMeta">
          {approvalStatus?.isPending ? <span className="approvalBadge">Needs approval</span> : null}
          {isEscalation ? <span className="approvalBadge">Escalation</span> : null}
          {span.error ? <span className="errorBadge">Error</span> : null}
          {decisionSource ? <span className={`decisionBadge ${decisionSource.className}`}>{decisionSource.label}</span> : null}
          <span>{formatDuration(span.duration_ms)}</span>
          {span.input_tokens || span.output_tokens ? <span>{formatTokens(span.input_tokens ?? 0, span.output_tokens ?? 0)}</span> : null}
          {span.estimated_cost ? <span>{formatCost(span.estimated_cost)}</span> : null}
          {typeof span.span_data.tool_server === "string" ? <span>{span.span_data.tool_server}</span> : null}
        </div>
      </button>
      {node.children.map((child) => (
        <SpanRow
          key={child.span.span_id}
          node={child}
          depth={depth + 1}
          selectedSpanId={selectedSpanId}
          onSelectSpan={onSelectSpan}
        />
      ))}
    </>
  );
}

function buildSpanTree(spans: Span[]): SpanNode[] {
  const nodes = new Map<string, SpanNode>();
  for (const span of spans) {
    nodes.set(span.span_id, { span, children: [] });
  }

  const roots: SpanNode[] = [];
  for (const span of spans) {
    const node = nodes.get(span.span_id);
    if (!node) continue;
    if (span.parent_id && nodes.has(span.parent_id)) {
      nodes.get(span.parent_id)?.children.push(node);
    } else {
      roots.push(node);
    }
  }

  return roots;
}

function agentFlowIcon(role: string) {
  if (role === "supervisor") return <Network size={15} />;
  if (role === "validator") return <ShieldCheck size={15} />;
  if (role === "response") return <MessageSquare size={15} />;
  return <Bot size={15} />;
}

function spanIcon(spanType: string) {
  if (spanType === "agent") return <Bot size={15} />;
  if (spanType === "function_tool") return <Wrench size={15} />;
  if (spanType === "guardrail") return <ShieldCheck size={15} />;
  if (spanType === "handoff") return <ArrowRight size={15} />;
  if (spanType === "approval") return <UserCheck size={15} />;
  if (spanType === "memory_read" || spanType === "memory_write") return <Braces size={15} />;
  return <Activity size={15} />;
}

function formatDecisionSource(value: unknown): { label: string; className: string } | null {
  if (typeof value !== "string" || value.length === 0) {
    return null;
  }
  if (value === "llm") {
    return { label: "LLM decision", className: "llm" };
  }
  if (value === "fallback") {
    return { label: "Fallback decision", className: "fallback" };
  }
  if (value === "policy_validation") {
    return { label: "Policy validation", className: "validation" };
  }
  if (value === "deterministic") {
    return { label: "Deterministic", className: "deterministic" };
  }
  return { label: value.replaceAll("_", " "), className: "unknown" };
}
