import { expect, type Page } from "@playwright/test";

const browserApiBaseURL = process.env.PLAYWRIGHT_BROWSER_API_BASE_URL ?? "http://localhost:8000";
export const dockerApiBaseURL = process.env.PLAYWRIGHT_DOCKER_API_BASE_URL ?? "http://api:8000";
const appBaseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173";

type PrepareAppOptions = {
  events?: "stub" | "real";
};

type SeedTraceOptions = {
  traceId: string;
  workflowName?: string;
  status?: "passed" | "failed" | "running" | "recovered";
  approvalStatus?: "blocked" | "approved" | "rejected";
  hasError?: boolean;
  startedAt?: string;
};

export async function prepareApp(page: Page, options: PrepareAppOptions = {}): Promise<void> {
  const events = options.events ?? "stub";

  await expect
    .poll(() => endpointStatus(appBaseURL), { timeout: 30_000, message: "web service is ready" })
    .toBe(200);
  await expect
    .poll(() => endpointStatus(`${dockerApiBaseURL}/health`), { timeout: 30_000, message: "api service is ready" })
    .toBe(200);

  if (events === "real") {
    await page.addInitScript(
      ({ browserApiBaseURL, dockerApiBaseURL }) => {
        const NativeEventSource = window.EventSource;
        window.EventSource = class AgentTraceEventSource extends NativeEventSource {
          constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
            super(String(url).replace(browserApiBaseURL, dockerApiBaseURL), eventSourceInitDict);
          }
        };
      },
      { browserApiBaseURL, dockerApiBaseURL },
    );
  }

  await page.route(`${browserApiBaseURL}/**`, async (route) => {
    const request = route.request();
    if (events === "stub" && request.url() === `${browserApiBaseURL}/events`) {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'event: connected\ndata: {"type":"connected"}\n\n',
      });
      return;
    }
    const url = request.url().replace(browserApiBaseURL, dockerApiBaseURL);
    try {
      const response = await route.fetch({ url });
      await route.fulfill({ response });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (page.isClosed() || message.includes("Target page, context or browser has been closed")) {
        return;
      }
      throw error;
    }
  });
}

export function uniqueId(prefix: string): string {
  return `${prefix}_${Date.now()}_${Math.random().toString(16).slice(2, 8)}`;
}

export async function seedTrace(options: SeedTraceOptions): Promise<void> {
  const startedAt = options.startedAt ?? new Date().toISOString();
  const endedAt = options.status === "running" ? null : new Date(Date.parse(startedAt) + 1200).toISOString();
  const spans: Array<Record<string, unknown>> = [
    {
      span_id: `${options.traceId}_supervisor`,
      span_type: "agent",
      name: "Supervisor Agent",
      started_at: startedAt,
      ended_at: endedAt,
      input: { message: "E2E seeded trace" },
      output: { final_status: options.status ?? "passed" },
      span_data: { agent_name: "Supervisor Agent" },
      input_tokens: 100,
      output_tokens: 40,
      estimated_cost: 0.0004,
    },
    {
      span_id: `${options.traceId}_response`,
      parent_id: `${options.traceId}_supervisor`,
      span_type: "generation",
      name: "Customer Response Generator",
      started_at: startedAt,
      ended_at: endedAt,
      input: { policy: "e2e_policy" },
      output: { final_response: "A monitored support response was generated for this seeded e2e trace." },
      span_data: { model: "deterministic" },
      input_tokens: 80,
      output_tokens: 30,
      estimated_cost: 0.0003,
    },
  ];

  if (options.approvalStatus) {
    spans.push({
      span_id: `${options.traceId}_approval`,
      parent_id: `${options.traceId}_supervisor`,
      span_type: "approval",
      name: "Human Approval Gate",
      started_at: startedAt,
      ended_at: endedAt,
      input: { requested_action: "refund_review", risk_level: "high" },
      output: {
        approval_required: true,
        approval_status: options.approvalStatus,
        approved_by: options.approvalStatus === "approved" ? "demo_user" : null,
        reason: "E2E approval workflow fixture.",
      },
      span_data: {
        approval_required: true,
        approval_status: options.approvalStatus,
        approved_by: options.approvalStatus === "approved" ? "demo_user" : null,
        approved_at: options.approvalStatus === "approved" ? endedAt : null,
        risk_level: "high",
        permission_scope: "billing.refund.review",
      },
    });
  }

  if (options.hasError) {
    spans.push({
      span_id: `${options.traceId}_tool_failure`,
      parent_id: `${options.traceId}_supervisor`,
      span_type: "function_tool",
      name: "lookup_customer",
      started_at: startedAt,
      ended_at: endedAt,
      input: { email: "timeout@example.com" },
      output: null,
      error: { message: "E2E seeded tool failure" },
      span_data: { tool_protocol: "mcp", tool_name: "lookup_customer" },
    });
  }

  const response = await fetch(`${dockerApiBaseURL}/traces`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      trace_id: options.traceId,
      workflow_name: options.workflowName ?? "support-triage",
      group_id: "e2e",
      status: options.status ?? "passed",
      started_at: startedAt,
      ended_at: endedAt,
      metadata: { scenario: "e2e_seed" },
      spans,
    }),
  });
  expect(response.ok, `seed trace ${options.traceId}`).toBeTruthy();

  for (const span of spans) {
    const spanResponse = await fetch(`${dockerApiBaseURL}/traces/${options.traceId}/spans`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(span),
    });
    expect(spanResponse.ok, `seed span ${String(span.span_id)}`).toBeTruthy();
  }
}

async function endpointStatus(url: string): Promise<number> {
  try {
    const response = await fetch(url);
    return response.status;
  } catch {
    return 0;
  }
}
