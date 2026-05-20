import { describe, expect, it } from "vitest";
import { executionStatus, groundingTone, statusTone } from "./status";

describe("status helpers", () => {
  it("normalizes execution status labels", () => {
    expect(executionStatus("grounded")).toBe("passed");
    expect(executionStatus("recovered")).toBe("passed");
    expect(executionStatus("failed")).toBe("failed");
  });

  it("maps status tones", () => {
    expect(statusTone("failed")).toBe("danger");
    expect(statusTone("running")).toBe("warning");
    expect(statusTone("passed")).toBe("neutral");
    expect(groundingTone("grounded")).toBe("success");
    expect(groundingTone("recovered")).toBe("warning");
    expect(groundingTone("failed")).toBe("danger");
  });
});
