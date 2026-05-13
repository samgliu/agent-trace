import { expect, test } from "@playwright/test";
import { prepareApp, seedTrace, uniqueId } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareApp(page, { events: "real" });
});

test("SSE refreshes the runs inbox when a new trace is ingested", async ({ page }) => {
  const traceId = uniqueId("trace_e2e_sse_ingest");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "AgentTrace" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Runs inbox" }).getByText(traceId)).toBeHidden();

  await seedTrace({ traceId, status: "passed", startedAt: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString() });

  await expect(
    page.getByRole("complementary", { name: "Runs inbox" }).getByRole("button", { name: new RegExp(traceId) }),
  ).toBeVisible({ timeout: 10_000 });
});
