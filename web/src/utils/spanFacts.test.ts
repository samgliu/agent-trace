import { describe, expect, it } from "vitest";
import { buildSpanFacts } from "./spanFacts";

describe("buildSpanFacts", () => {
  it("summarizes timing, token, cost, model, and tool details", () => {
    expect(
      buildSpanFacts({
        duration_ms: 1250,
        input_tokens: 120,
        output_tokens: 45,
        estimated_cost: 0.0007,
        span_data: {
          model: "gpt-5.4",
          tool_name: "lookup_customer",
          tool_server: "support-tools-mcp",
        },
      }),
    ).toEqual([
      { label: "Duration", value: "1.25s" },
      { label: "Tokens", value: "120/45" },
      { label: "Cost", value: "$0.0007" },
      { label: "Model", value: "gpt-5.4" },
      { label: "Tool", value: "lookup_customer · support-tools-mcp" },
    ]);
  });

  it("keeps empty optional metrics out of the inspector", () => {
    expect(
      buildSpanFacts({
        duration_ms: null,
        input_tokens: null,
        output_tokens: null,
        estimated_cost: null,
        span_data: {},
      }),
    ).toEqual([{ label: "Duration", value: "-" }]);
  });
});
