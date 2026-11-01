import { catalogNameOf, toUiId } from "@/domains/providers"

/** Display name of one wire provider id, from the static catalog. */
export function usageProviderLabel(provider: string): string {
  return catalogNameOf(toUiId(provider)) ?? provider
}

/** Latency cell text; an unmeasured event shows a dash. */
export function usageLatencyText(latencyMs: number | null): string {
  return latencyMs === null ? "—" : `${Math.round(latencyMs)} ms`
}

/** Local date and time of one ISO timestamp, else the raw text. */
export function usageTimeText(iso: string): string {
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString()
}
