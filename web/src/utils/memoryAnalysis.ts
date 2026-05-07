export type MemorySpanInput = {
  span_id: string;
  name: string;
  span_type: string;
  span_data: Record<string, unknown>;
};

export type MemoryWarning = {
  spanId: string;
  label: string;
  detail: string;
  tone: "warning" | "danger";
};

export type MemorySummary = {
  readCount: number;
  writeCount: number;
  stores: string[];
  retrievedCount: number;
  averageRelevance: number | null;
  usedCount: number;
  ignoredCount: number;
  warnings: MemoryWarning[];
};

const STALE_MEMORY_SECONDS = 86400 * 90;
const LOW_RELEVANCE_SCORE = 0.65;

export function buildMemorySummary(spans: MemorySpanInput[]): MemorySummary {
  const memorySpans = spans.filter((span) => span.span_type === "memory_read" || span.span_type === "memory_write");
  const reads = memorySpans.filter((span) => span.span_type === "memory_read");
  const writes = memorySpans.filter((span) => span.span_type === "memory_write");
  const relevanceScores = reads
    .map((span) => numberValue(span.span_data.memory_relevance_score))
    .filter((value): value is number => value !== null);
  const warnings = reads.flatMap(memoryWarnings);
  const usedCount = reads.filter((span) => span.span_data.memory_used_in_response === true).length;

  return {
    readCount: reads.length,
    writeCount: writes.length,
    stores: Array.from(
      new Set(memorySpans.map((span) => stringValue(span.span_data.memory_store)).filter((value): value is string => value !== null)),
    ),
    retrievedCount: reads.reduce((total, span) => total + (numberValue(span.span_data.retrieved_memory_count) ?? 0), 0),
    averageRelevance:
      relevanceScores.length > 0
        ? relevanceScores.reduce((total, value) => total + value, 0) / relevanceScores.length
        : null,
    usedCount,
    ignoredCount: reads.length - usedCount,
    warnings,
  };
}

function memoryWarnings(span: MemorySpanInput): MemoryWarning[] {
  const warnings: MemoryWarning[] = [];
  const used = span.span_data.memory_used_in_response;
  const relevance = numberValue(span.span_data.memory_relevance_score);
  const ageSeconds = numberValue(span.span_data.memory_age_seconds);
  if (used === false) {
    warnings.push({ spanId: span.span_id, label: "Ignored memory", detail: span.name, tone: "warning" });
  }
  if (relevance !== null && relevance < LOW_RELEVANCE_SCORE) {
    warnings.push({ spanId: span.span_id, label: "Low relevance", detail: relevance.toFixed(2), tone: "warning" });
  }
  if (ageSeconds !== null && ageSeconds > STALE_MEMORY_SECONDS) {
    warnings.push({ spanId: span.span_id, label: "Stale memory", detail: `${Math.round(ageSeconds / 86400)} days old`, tone: "danger" });
  }
  return warnings;
}

function stringValue(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
