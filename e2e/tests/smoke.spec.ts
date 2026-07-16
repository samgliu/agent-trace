import { expect, test } from "@playwright/test";
import { prepareApp, seedTrace, uniqueId } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareApp(page);
});

test("dashboard loads trace operations summary", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "AgentTrace" })).toBeVisible();
  await expect(page.getByText("Operations dashboard")).toBeVisible();
  await expect(page.getByText("Runs", { exact: true })).toBeVisible();
  await expect(page.getByText("Approvals waiting")).toBeVisible();
  await expect(page.getByText("Live customer-service agent")).toBeVisible();
  await expect(page.getByText("Trace Timeline")).toBeVisible();
});

test("agent flow cards focus matching timeline spans", async ({ page }) => {
  const traceId = uniqueId("trace_e2e_agent_flow");
  await seedTrace({ traceId, status: "passed", startedAt: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString() });

  await page.goto("/");
  await page.getByRole("complementary", { name: "Runs inbox" }).getByRole("button", { name: new RegExp(traceId) }).click();

  const flow = page.getByLabel("Agent flow");
  await expect(flow.getByRole("heading", { name: "Agent Flow" })).toBeVisible();
  await expect(flow.getByRole("button", { name: /Supervisor/ })).toBeVisible();
  await flow.getByRole("button", { name: /Customer Response/ }).click();

  await expect(page.locator(".spanRow.selected").filter({ hasText: "Customer Response Generator" })).toBeVisible();
});

test("trace inspector redacts sensitive values by default", async ({ page }) => {
  const traceId = uniqueId("trace_e2e_privacy");
  await seedTrace({
    traceId,
    status: "passed",
    sensitive: true,
    startedAt: new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString(),
  });

  await page.goto("/");
  await page.getByRole("complementary", { name: "Runs inbox" }).getByRole("button", { name: new RegExp(traceId) }).click();

  await expect(page.getByText("Privacy: Redacted")).toBeVisible();
  await page.getByLabel("Agent flow").getByRole("button", { name: /Customer Response/ }).click();

  const inspector = page.locator(".spanDetail");
  await expect(inspector.getByText("[REDACTED_EMAIL]").first()).toBeVisible();
  await expect(inspector.getByText("[REDACTED_PAYMENT]").first()).toBeVisible();
  await expect(inspector.getByText("customer@example.com")).not.toBeVisible();
});
