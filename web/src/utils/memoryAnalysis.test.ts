import { describe, expect, it } from "vitest";
import { buildMemorySummary } from "./memoryAnalysis";

describe("memory analysis", () => {
  it("summarizes memory reads, writes, stores, and warnings", () => {
    expect(
      buildMemorySummary([
        {
          span_id: "write_1",
          name: "Write Working Memory",
          span_type: "memory_write",
          span_data: { memory_store: "conversation_working_memory" },
        },
        {
          span_id: "read_1",
          name: "Read Customer Memory",
          span_type: "memory_read",
          span_data: {
            memory_store: "customer_history",
            retrieved_memory_count: 1,
            memory_relevance_score: 0.42,
            memory_age_seconds: 86400 * 180,
            memory_used_in_response: false,
          },
        },
      ]),
    ).toEqual({
      readCount: 1,
      writeCount: 1,
      stores: ["conversation_working_memory", "customer_history"],
      retrievedCount: 1,
      averageRelevance: 0.42,
      usedCount: 0,
      ignoredCount: 1,
      warnings: [
        { spanId: "read_1", label: "Ignored memory", detail: "Read Customer Memory", tone: "warning" },
        { spanId: "read_1", label: "Low relevance", detail: "0.42", tone: "warning" },
        { spanId: "read_1", label: "Stale memory", detail: "180 days old", tone: "danger" },
      ],
    });
  });

  it("returns empty memory summary when no memory spans exist", () => {
    expect(buildMemorySummary([])).toEqual({
      readCount: 0,
      writeCount: 0,
      stores: [],
      retrievedCount: 0,
      averageRelevance: null,
      usedCount: 0,
      ignoredCount: 0,
      warnings: [],
    });
  });
});
