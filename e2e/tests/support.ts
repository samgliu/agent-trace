import { expect, type Page } from "@playwright/test";

const browserApiBaseURL = process.env.PLAYWRIGHT_BROWSER_API_BASE_URL ?? "http://localhost:8000";
export const dockerApiBaseURL = process.env.PLAYWRIGHT_DOCKER_API_BASE_URL ?? "http://api:8000";
const appBaseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5173";

type PrepareAppOptions = {
  events?: "stub" | "real";
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
    const response = await route.fetch({ url });
    await route.fulfill({ response });
  });
}

async function endpointStatus(url: string): Promise<number> {
  try {
    const response = await fetch(url);
    return response.status;
  } catch {
    return 0;
  }
}
