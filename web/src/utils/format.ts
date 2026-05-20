export function formatDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  if (value >= 1000) {
    return `${(value / 1000).toFixed(2)}s`;
  }
  return `${value}ms`;
}

export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined) {
    return "-";
  }
  return `$${value.toFixed(4)}`;
}

export function formatTokens(input: number, output: number): string {
  return `${input}/${output}`;
}

export function formatRelevance(value: number | null): string {
  return value === null ? "-" : value.toFixed(2);
}

export function formatShortTimestamp(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}
