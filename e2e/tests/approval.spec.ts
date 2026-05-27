import { expect, test } from "@playwright/test";
import { prepareApp, seedTrace, uniqueId } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareApp(page);
});

test("approval gate can be approved, rejected, and reverted", async ({ page }) => {
  const traceId = uniqueId("trace_e2e_approval");
  const workflowName = uniqueId("e2e-approval-workflow");
  await seedTrace({
    traceId,
    workflowName,
    approvalStatus: "blocked",
    status: "recovered",
    startedAt: new Date(Date.now() + 60 * 60 * 1000).toISOString(),
  });

  await page.goto("/");
  await page.getByRole("combobox", { name: "Workflow", exact: true }).selectOption(workflowName);
  const runButton = page.getByRole("complementary", { name: "Runs inbox" }).getByRole("button", { name: new RegExp(traceId) });
  await expect(runButton).toBeVisible();
  await runButton.click();

  const selectedTrace = page.getByRole("region", { name: "Selected trace" });
  const approvalGates = page.getByRole("region", { name: "Approval gates" });

  await expect(selectedTrace.getByText(traceId)).toBeVisible();
  await expect(approvalGates.getByText("Human Approval Gate")).toBeVisible();
  await expect(approvalGates.getByText("blocked")).toBeVisible();
  await expect(approvalGates.getByRole("region", { name: "Decision history" }).getByText("No recorded decisions yet.")).toBeVisible();
  await expect(approvalGates.getByRole("button", { name: "Revert", exact: true })).toBeDisabled();

  await approvalGates.getByRole("button", { name: "Approve", exact: true }).click();
  await expect(approvalGates.getByRole("button", { name: "Human Approval Gate approved", exact: true })).toBeVisible();
  await expect(approvalGates.getByRole("button", { name: "Approve", exact: true })).toBeDisabled();
  await expect(approvalGates.getByRole("button", { name: "Revert", exact: true })).toBeEnabled();

  await approvalGates.getByRole("button", { name: "Revert", exact: true }).click();
  await expect(approvalGates.getByRole("button", { name: "Human Approval Gate blocked", exact: true })).toBeVisible();

  await approvalGates.getByRole("button", { name: "Reject", exact: true }).click();
  await expect(approvalGates.getByRole("button", { name: "Human Approval Gate rejected", exact: true })).toBeVisible();
  await expect(approvalGates.getByRole("button", { name: "Reject", exact: true })).toBeDisabled();
  await expect(approvalGates.getByRole("button", { name: "Revert", exact: true })).toBeEnabled();

  const decisionHistory = approvalGates.getByRole("region", { name: "Decision history" });
  await expect(decisionHistory.getByText("approved")).toBeVisible();
  await expect(decisionHistory.getByText("reverted")).toBeVisible();
  await expect(decisionHistory.getByText("rejected")).toBeVisible();
});
