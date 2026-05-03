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
