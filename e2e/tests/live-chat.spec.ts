import { expect, test } from "@playwright/test";
import { prepareApp } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareApp(page, { events: "real" });
});

test("live chat uses SSE to complete the transcript and open the generated trace", async ({ page }) => {
  await page.goto("/");

  const chat = page.getByRole("region", { name: "Live customer-service agent" });
  const message = "Order number #1234. The bananas were moldy and unsafe, so I threw them out.";

  await expect(chat.getByRole("heading", { name: "Chat monitor" })).toBeVisible();
  await chat.getByLabel("Message").fill(message);

  const turnResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/chat/sessions/") &&
      response.url().endsWith("/messages/async") &&
      response.request().method() === "POST",
  );
  await chat.getByRole("button", { name: "Send" }).click();
  await turnResponse;

  await expect(chat.getByText(message)).toBeVisible();

  const traceLink = chat.getByRole("button", { name: /Trace: trace_chat_msg_/ }).last();
  await expect(traceLink).toBeVisible({ timeout: 30_000 });
  await expect(chat.getByText("assistant", { exact: true }).last()).toBeVisible();

  const traceLabel = await traceLink.textContent();
  const traceId = traceLabel?.match(/Trace: (trace_chat_msg_[a-z0-9]+)/)?.[1];
  expect(traceId).toBeTruthy();

  await traceLink.click();
  await expect(page.getByRole("region", { name: "Selected trace" }).getByText(traceId!)).toBeVisible();
  await expect(page.getByText("Trace Timeline")).toBeVisible();
  await expect(page.getByRole("button", { name: /Customer Response Generator/ })).toBeVisible();
});
