import { expect, test } from "@playwright/test";
import { dockerApiBaseURL, hasAuthToken, playwrightAuthToken, prepareApp } from "./support";

test("dashboard token login protects the app without frontend secrets", async ({ page }) => {
  test.skip(!hasAuthToken(), "Auth e2e requires an auth-enabled API and PLAYWRIGHT_AUTH_TOKEN or AGENTTRACE_ADMIN_TOKEN.");

  await prepareApp(page, { auth: "session" });
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Sign in to AgentTrace" })).toBeVisible();

  await page.getByLabel("Access token").fill("wrong-token");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Invalid access token.")).toBeVisible();

  const loginResponsePromise = page.waitForResponse(
    (response) => response.url().endsWith("/auth/login") && response.request().method() === "POST",
  );
  await page.getByLabel("Access token").fill(playwrightAuthToken());
  await page.getByRole("button", { name: "Sign in" }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.ok()).toBeTruthy();

  const sessionResponse = await fetch(`${dockerApiBaseURL}/auth/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ token: playwrightAuthToken() }),
  });
  expect(sessionResponse.ok).toBeTruthy();
  const setCookie = sessionResponse.headers.get("set-cookie");
  const sessionCookie = setCookie?.match(/agenttrace_session=([^;]+)/)?.[1];
  expect(sessionCookie).toBeTruthy();
  expect(sessionCookie).not.toBe(playwrightAuthToken());
  expect(sessionCookie).toContain(".");
  await page.reload();

  await expect(page.getByText("Operations dashboard")).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in to AgentTrace" })).toBeVisible();
});
