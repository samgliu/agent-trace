import { expect, test } from "@playwright/test";
import { hasAuthToken, playwrightAuthToken, prepareApp } from "./support";

test("dashboard token login protects the app without frontend secrets", async ({ page }) => {
  test.skip(!hasAuthToken(), "Auth e2e requires an auth-enabled API and PLAYWRIGHT_AUTH_TOKEN.");

  await prepareApp(page, { auth: "manual" });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sign in to AgentTrace" })).toBeVisible();

  await page.getByLabel("Access token").fill("wrong-token");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid access token.")).toBeVisible();

  await page.getByLabel("Access token").fill(playwrightAuthToken());
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page.getByText("Operations dashboard")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to AgentTrace" })).toBeVisible();
});
