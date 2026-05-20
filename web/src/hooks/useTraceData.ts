import { useCallback, useEffect, useState } from "react";
import type {
  DashboardSummary,
  GroundingSummary,
  LoadState,
  Metrics,
  TraceDetail,
  TraceFilters,
  TraceListResponse,
} from "../types";
import { fetchJson } from "../utils/apiClient";
import { clampedOffset, TRACE_PAGE_SIZE } from "../utils/pagination";
import { emptyFilters, filterQuery } from "../utils/traceFilters";

type TraceSelection = {
  traceId: string;
  spanId?: string | null;
};

type UseTraceDataOptions = {
  refreshKey: number;
};

export function useTraceData({ refreshKey }: UseTraceDataOptions) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [selectedSpanId, setSelectedSpanId] = useState<string | null>(null);
  const [filters, setFilters] = useState<TraceFilters>(emptyFilters());
  const [activeChatSessionId, setActiveChatSessionId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [traceList, dashboard, workflows] = await Promise.all([
          fetchJson<TraceListResponse>(`/traces${filterQuery(filters, activeChatSessionId)}`),
          fetchJson<DashboardSummary>("/dashboard/summary"),
          fetchJson<string[]>("/workflows"),
        ]);
        const traces = traceList.items;
        const safeOffset = clampedOffset(filters.offset, traceList.total, TRACE_PAGE_SIZE);
        if (safeOffset !== filters.offset) {
          if (!cancelled) {
            setFilters((current) => ({ ...current, offset: safeOffset }));
          }
          return;
        }
        const traceId = selectedTraceId ?? traces[0]?.trace_id;
        if (!traceId) {
          if (!cancelled) {
            setSelectedTraceId(null);
            setSelectedSpanId(null);
            setState({ status: "empty", traces, traceTotal: traceList.total, dashboard, workflows });
          }
          return;
        }
        const [selectedTrace, rawTrace, metrics, grounding] = await Promise.all([
          fetchJson<TraceDetail>(`/traces/${traceId}`),
          fetchJson<unknown>(`/traces/${traceId}/raw`),
          fetchJson<Metrics>(`/traces/${traceId}/metrics`),
          fetchJson<GroundingSummary>(`/traces/${traceId}/grounding`),
        ]);
        if (!cancelled) {
          setSelectedTraceId(traceId);
          setSelectedSpanId((currentSpanId) =>
            selectedTrace.spans.some((span) => span.span_id === currentSpanId)
              ? currentSpanId
              : selectedTrace.spans[0]?.span_id ?? null,
          );
          setState({
            status: "ready",
            traces,
            traceTotal: traceList.total,
            dashboard,
            workflows,
            selectedTrace,
            rawTrace,
            metrics,
            grounding,
          });
        }
      } catch (error) {
        if (!cancelled) {
          setState({ status: "error", message: error instanceof Error ? error.message : "Unknown error" });
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [activeChatSessionId, filters, refreshKey, selectedTraceId]);

  const selectTrace = useCallback((traceId: string) => {
    setSelectedTraceId(traceId);
  }, []);

  const selectTraceWithSpan = useCallback(({ traceId, spanId = null }: TraceSelection) => {
    setSelectedTraceId(traceId);
    setSelectedSpanId(spanId);
  }, []);

  const updateFilters = useCallback((nextFilters: TraceFilters) => {
    setSelectedTraceId(null);
    setSelectedSpanId(null);
    setFilters(nextFilters);
  }, []);

  const clearCurrentChatFilter = useCallback(() => {
    setFilters((current) => ({ ...current, currentChatOnly: false, offset: 0 }));
  }, []);

  const updatePage = useCallback((offset: number) => {
    setSelectedTraceId(null);
    setSelectedSpanId(null);
    setFilters((current) => ({ ...current, offset }));
  }, []);

  return {
    state,
    filters,
    selectedSpanId,
    setActiveChatSessionId,
    selectTrace,
    selectTraceWithSpan,
    setSelectedSpanId,
    updateFilters,
    updatePage,
    clearCurrentChatFilter,
  };
}
