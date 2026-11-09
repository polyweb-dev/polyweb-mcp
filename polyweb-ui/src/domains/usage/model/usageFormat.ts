const OPERATION_LABELS: Readonly<Record<string, string>> = {
  search: "Search",
  fetch: "Fetch",
  cost_estimate: "Cost estimate",
}

/** Display label of one usage operation. */
export function usageOperationLabel(operation: string): string {
  return OPERATION_LABELS[operation] ?? operation
}
