import { describe, expect, it } from "vitest";
import { sourceKindLabel, sourceLabel, stringMetadata } from "./source";

describe("source helpers", () => {
  it("formats known source labels", () => {
    expect(sourceLabel("openai-agents")).toBe("OpenAI Agents");
    expect(sourceLabel("agenttrace")).toBe("AgentTrace");
    expect(sourceLabel("langgraph")).toBe("langgraph");
  });

  it("formats known source kinds", () => {
    expect(sourceKindLabel("trace_export")).toBe("trace export");
    expect(sourceKindLabel("event_stream")).toBe("event stream");
    expect(sourceKindLabel("live_api")).toBe("live API");
  });

  it("extracts string metadata only", () => {
    expect(stringMetadata("live_api")).toBe("live_api");
    expect(stringMetadata("")).toBeNull();
    expect(stringMetadata(123)).toBeNull();
  });
});
