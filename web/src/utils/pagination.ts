export const TRACE_PAGE_SIZE = 25;

export function nextOffset(offset: number, pageSize = TRACE_PAGE_SIZE): number {
  return Math.max(0, offset) + pageSize;
}

export function previousOffset(offset: number, pageSize = TRACE_PAGE_SIZE): number {
  return Math.max(0, Math.max(0, offset) - pageSize);
}

export function hasNextPage(offset: number, total: number, pageSize = TRACE_PAGE_SIZE): boolean {
  return nextOffset(offset, pageSize) < total;
}

export function pageRange(offset: number, visibleCount: number, total: number): string {
  if (total <= 0 || visibleCount <= 0) return "0-0";
  const start = Math.min(Math.max(0, offset) + 1, total);
  const end = Math.min(Math.max(0, offset) + visibleCount, total);
  return `${start}-${end}`;
}

export function clampedOffset(offset: number, total: number, pageSize = TRACE_PAGE_SIZE): number {
  if (total <= 0) return 0;
  const lastPageOffset = Math.floor((total - 1) / pageSize) * pageSize;
  return Math.min(Math.max(0, offset), lastPageOffset);
}
