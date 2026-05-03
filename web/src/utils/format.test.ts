import { describe, expect, it } from "vitest";
import { formatCost, formatDuration, formatTokens } from "./format";

describe("format helpers", () => {
  it("formats durations", () => {
    expect(formatDuration(850)).toBe("850ms");
    expect(formatDuration(4000)).toBe("4.00s");
    expect(formatDuration(null)).toBe("-");
  });

  it("formats costs", () => {
    expect(formatCost(0.0034)).toBe("$0.0034");
    expect(formatCost(null)).toBe("-");
  });

  it("formats token pairs", () => {
    expect(formatTokens(1550, 316)).toBe("1550/316");
  });
});
