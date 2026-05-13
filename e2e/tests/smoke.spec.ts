import { expect, test } from "@playwright/test";
import { prepareApp } from "./support";

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
