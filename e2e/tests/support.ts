import { expect, type Page } from "@playwright/test";

export const browserApiBaseURL = process.env.PLAYWRIGHT_BROWSER_API_BASE_URL ?? "http://localhost:8000";
export const dockerApiBaseURL = process.env.PLAYWRIGHT_DOCKER_API_BASE_URL ?? "http://api:8000";
const appBaseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173";
const authToken = process.env.PLAYWRIGHT_AUTH_TOKEN || process.env.AGENTTRACE_ADMIN_TOKEN || "";
const viewerToken = process.env.AGENTTRACE_VIEWER_TOKEN || "";

type PrepareAppOptions = {
  auth?: "auto" | "manual" | "session";
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
  const auth = options.auth ?? "auto";

  await expect
    .poll(() => endpointStatus(appBaseURL), { timeout: 30_000, message: "web service is ready" })
    .toBe(200);
  await expect
    .poll(() => endpointStatus(`${dockerApiBaseURL}/health`), { timeout: 30_000, message: "api service is ready" })
    .toBe(200);

  if (events === "real") {
    if (auth === "auto" && hasAuthToken()) {
      await page.addInitScript(
        ({ authToken, browserApiBaseURL, dockerApiBaseURL }) => {
          class AgentTraceFetchEventSource extends EventTarget {
            static CONNECTING = 0;
            static OPEN = 1;
            static CLOSED = 2;
            readonly CONNECTING = 0;
            readonly OPEN = 1;
            readonly CLOSED = 2;
            onerror: ((event: Event) => void) | null = null;
            onmessage: ((event: MessageEvent) => void) | null = null;
            onopen: ((event: Event) => void) | null = null;
            readyState = AgentTraceFetchEventSource.CONNECTING;
            url: string;
            withCredentials: boolean;
            private abortController = new AbortController();

            constructor(url: string | URL, eventSourceInitDict?: EventSourceInit) {
              super();
              this.url = String(url).replace(browserApiBaseURL, dockerApiBaseURL);
              this.withCredentials = Boolean(eventSourceInitDict?.withCredentials);
              void this.connect();
            }

            close() {
              this.readyState = AgentTraceFetchEventSource.CLOSED;
              this.abortController.abort();
            }

            private async connect() {
              try {
                const response = await fetch(this.url, {
                  headers: { authorization: `Bearer ${authToken}` },
                  signal: this.abortController.signal,
                });
                if (!response.ok || !response.body) {
                  throw new Error(`SSE failed: ${response.status}`);
                }
                this.readyState = AgentTraceFetchEventSource.OPEN;
                const openEvent = new Event("open");
                this.dispatchEvent(openEvent);
                this.onopen?.(openEvent);
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                while (this.readyState !== AgentTraceFetchEventSource.CLOSED) {
                  const { done, value } = await reader.read();
                  if (done) break;
                  buffer += decoder.decode(value, { stream: true });
                  const events = buffer.split("\n\n");
                  buffer = events.pop() ?? "";
                  events.forEach((rawEvent) => this.dispatchServerEvent(rawEvent));
                }
              } catch (error) {
                if (this.readyState !== AgentTraceFetchEventSource.CLOSED) {
                  const errorEvent = new Event("error");
                  this.dispatchEvent(errorEvent);
                  this.onerror?.(errorEvent);
                  console.error(error);
                }
              }
            }

            private dispatchServerEvent(rawEvent: string) {
              const lines = rawEvent.split("\n");
              const eventType = lines.find((line) => line.startsWith("event:"))?.slice("event:".length).trim() || "message";
              const data = lines
                .filter((line) => line.startsWith("data:"))
                .map((line) => line.slice("data:".length).trimStart())
                .join("\n");
              const event = new MessageEvent(eventType, { data });
              this.dispatchEvent(event);
              if (eventType === "message") {
                this.onmessage?.(event);
              }
            }
          }

          window.EventSource = AgentTraceFetchEventSource as unknown as typeof EventSource;
        },
        { authToken, browserApiBaseURL, dockerApiBaseURL },
      );
    } else {
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
  }

  let sessionCookie: string | null = null;
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
    const headers = { ...request.headers() };
    if (auth === "auto") {
      Object.assign(headers, authenticatedHeaders(headers));
    }
    if (auth === "session" && sessionCookie) {
      headers.cookie = `${headers.cookie ? `${headers.cookie}; ` : ""}${sessionCookie}`;
    }
    try {
      const response = await route.fetch({
        url,
        headers,
      });
      if (auth === "session") {
        const setCookie = response.headers()["set-cookie"];
        if (request.url().endsWith("/auth/login") && setCookie) {
          const match = setCookie.match(/agenttrace_session=[^;]+/);
          sessionCookie = match?.[0] ?? sessionCookie;
        }
        if (request.url().endsWith("/auth/logout")) {
          sessionCookie = null;
        }
      }
      await route.fulfill({ response });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      if (
        page.isClosed() ||
        message.includes("Target page, context or browser has been closed") ||
        message.includes("Fetch response has been disposed")
      ) {
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
    headers: authenticatedHeaders({ "content-type": "application/json" }),
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
      headers: authenticatedHeaders({ "content-type": "application/json" }),
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

export function hasAuthToken(): boolean {
  return authToken.trim().length > 0;
}

export function playwrightAuthToken(): string {
  return authToken;
}

export function hasViewerAuthToken(): boolean {
  return viewerToken.trim().length > 0;
}

export function playwrightViewerToken(): string {
  return viewerToken;
}

function authenticatedHeaders(headers: Record<string, string>): Record<string, string> {
  if (!hasAuthToken()) {
    return headers;
  }
  return { ...headers, authorization: `Bearer ${authToken}` };
}
