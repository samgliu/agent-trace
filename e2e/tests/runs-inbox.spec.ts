import { expect, test } from "@playwright/test";
import { prepareApp, seedTrace, uniqueId } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareApp(page);
});

test("filters can find approval runs and clear an empty state", async ({ page }) => {
  const approvalTraceId = uniqueId("trace_e2e_filter_approval");
  const emptyWorkflow = uniqueId("e2e-empty-workflow");
  const emptyTraceId = uniqueId("trace_e2e_empty");

  await seedTrace({
    traceId: approvalTraceId,
    approvalStatus: "blocked",
    status: "recovered",
    startedAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  });
  await seedTrace({ traceId: emptyTraceId, workflowName: emptyWorkflow, status: "passed" });

  await page.goto("/");

  await page.getByText("Signals").click();
  await page.getByRole("combobox", { name: "Approval", exact: true }).selectOption("pending");

  const runsInbox = page.getByRole("complementary", { name: "Runs inbox" });
  await expect(runsInbox.getByRole("button", { name: new RegExp(`${approvalTraceId}.*Needs approval`) })).toBeVisible();

  await page.getByRole("combobox", { name: "Workflow", exact: true }).selectOption(emptyWorkflow);
  await page.getByRole("combobox", { name: "Status", exact: true }).selectOption("failed");

  await expect(page.getByRole("heading", { name: "No matching runs" })).toBeVisible();
  await page.getByRole("button", { name: "Clear filters" }).click();

  await expect(page.getByRole("heading", { name: "No matching runs" })).toBeHidden();
  await expect(page.getByText(/matching runs/)).toBeVisible();
});

test("runs inbox paginates at 25 traces per page", async ({ page }) => {
  const workflowName = uniqueId("e2e-pagination-workflow");
  const traceIds = Array.from({ length: 30 }, (_, index) => uniqueId(`trace_e2e_page_${index + 1}`));

  await Promise.all(
    traceIds.map((traceId, index) =>
      seedTrace({
        traceId,
        workflowName,
        status: "passed",
        startedAt: new Date(Date.now() + index * 1000).toISOString(),
      }),
    ),
  );

  await page.goto("/");
  await page.getByRole("combobox", { name: "Workflow", exact: true }).selectOption(workflowName);

  const runsInbox = page.getByRole("complementary", { name: "Runs inbox" });
  await expect(runsInbox.getByText("30 matching runs")).toBeVisible();
  await expect(runsInbox.getByText("1-25")).toBeVisible();
  await expect(runsInbox.getByRole("button", { name: "Previous" })).toBeDisabled();
  await expect(runsInbox.getByRole("button", { name: "Next" })).toBeEnabled();

  await runsInbox.getByRole("button", { name: "Next" }).click();
  await expect(runsInbox.getByText("26-30")).toBeVisible();
  await expect(runsInbox.getByRole("button", { name: "Previous" })).toBeEnabled();
  await expect(runsInbox.getByRole("button", { name: "Next" })).toBeDisabled();
});
