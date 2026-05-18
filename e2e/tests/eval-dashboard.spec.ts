import { expect, test } from "@playwright/test";
import { prepareApp } from "./support";

test.beforeEach(async ({ page }) => {
  await prepareApp(page);
});

test("eval dashboard shows running progress, fallback model, and failed check detail", async ({ page }) => {
  const runningRun = {
    run_id: "eval_e2e_llm_running",
    suite_id: "support-triage-core",
    name: "Support triage core",
    execution_mode: "llm",
    model_provider: "gemini",
    model_name: "gemini-primary",
    status: "running",
    total: 2,
    passed: 0,
    failed: 0,
    pass_rate: 0,
    created_at: "2026-05-18T05:00:00Z",
    results: [
      {
        case_id: "e2e-fallback-regression",
        name: "Fallback regression case",
        trace_id: "trace_e2e_eval_fallback",
        passed: false,
        score: 0.5,
        checks: [
          {
            name: "policy_id",
            expected: "policy_refund_duplicate_charge",
            actual: "policy_general_refund",
            passed: false,
          },
          {
            name: "response_excludes:duplicate",
            expected: "excludes duplicate",
            actual: "duplicate charge refund review",
            passed: false,
          },
        ],
        model_events: [
          {
            span_name: "Policy Agent",
            model: "gemini-fallback",
            fallback_used: true,
            attempts: [
              {
                model: "gemini-primary",
                status: "failed",
                error: "LLM provider request failed with HTTP 503: UNAVAILABLE",
              },
              { model: "gemini-fallback", status: "succeeded" },
            ],
          },
        ],
      },
    ],
  };

  await page.route("**/eval-runs?limit=5", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], limit: 5, offset: 0, total: 0 }),
    });
  });
  await page.route("**/eval-runs/support-triage/comparison", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        suite_id: "support-triage-core",
        status: "missing_runs",
        deterministic_run: null,
        llm_run: null,
        pass_rate_delta: null,
        llm_regressions: [],
        llm_improvements: [],
        both_failed: [],
      }),
    });
  });
  await page.route("**/evals/support-triage/run/async?mode=llm", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(runningRun) });
  });

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Support agent quality" })).toBeVisible();

  const evalPanel = page.locator(".evalDashboard").filter({ hasText: "Support agent quality" }).first();
  await evalPanel.getByRole("combobox").selectOption("llm");
  await evalPanel.getByRole("button", { name: "Run evals" }).click();

  await expect(evalPanel.getByText("LLM eval is running")).toBeVisible();
  await expect(evalPanel.getByText("1/2 cases complete")).toBeVisible();
  await expect(evalPanel.getByRole("button", { name: /Fallback regression case/ })).toBeVisible();
  await expect(evalPanel.getByText("gemini-fallback")).toBeVisible();
  await expect(evalPanel.getByText("Fallback used after gemini-primary")).toBeVisible();
  await expect(evalPanel.getByText("Expected: policy_refund_duplicate_charge")).toBeVisible();
  await expect(evalPanel.getByText("Actual: policy_general_refund")).toBeVisible();
  await expect(evalPanel.getByText("Improvement plan")).toBeVisible();
  await expect(evalPanel.getByText("multi-agent routing and policy/action planning")).toBeVisible();
  await expect(evalPanel.getByText("agent_apps/customer_service/runner.py").first()).toBeVisible();
});

test("recent eval runs can be opened from history", async ({ page }) => {
  const summary = {
    run_id: "eval_e2e_history",
    suite_id: "support-triage-core",
    name: "Support triage core",
    execution_mode: "llm",
    model_provider: "gemini",
    model_name: "gemini-primary",
    status: "failed",
    total: 2,
    passed: 1,
    failed: 1,
    pass_rate: 0.5,
    created_at: "2026-05-18T05:00:00Z",
  };
  const detail = {
    ...summary,
    results: [
      {
        case_id: "e2e-history-failure",
        name: "Historical failure case",
        trace_id: "trace_e2e_history_failure",
        passed: false,
        score: 0.5,
        checks: [
          {
            name: "approval_required",
            expected: true,
            actual: false,
            passed: false,
          },
        ],
      },
      {
        case_id: "e2e-history-pass",
        name: "Historical pass case",
        trace_id: "trace_e2e_history_pass",
        passed: true,
        score: 1,
        checks: [],
      },
    ],
  };

  await page.route("**/eval-runs?limit=5", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [summary], limit: 5, offset: 0, total: 1 }),
    });
  });
  await page.route("**/eval-runs/support-triage/comparison", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        suite_id: "support-triage-core",
        status: "missing_deterministic",
        deterministic_run: null,
        llm_run: summary,
        pass_rate_delta: null,
        llm_regressions: [],
        llm_improvements: [],
        both_failed: [],
      }),
    });
  });
  await page.route("**/eval-runs/eval_e2e_history", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detail) });
  });

  await page.goto("/");

  const evalPanel = page.locator(".evalDashboard").filter({ hasText: "Support agent quality" }).first();
  await evalPanel.getByRole("button", { name: /LLM-backed/ }).click();

  await expect(evalPanel.getByRole("button", { name: /Historical failure case/ })).toBeVisible();
  await expect(evalPanel.getByText("Expected: true")).toBeVisible();
  await expect(evalPanel.getByText("Actual: false")).toBeVisible();
  await expect(evalPanel.getByText("approval policy and validator guardrails")).toBeVisible();
  await expect(evalPanel.getByRole("button", { name: /LLM-backed/ })).toHaveAttribute("aria-current", "true");
});
