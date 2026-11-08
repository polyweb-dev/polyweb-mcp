import type { Capability } from "@/domains/providers"
import { formatLatency, formatRelativeTime } from "@/shared/lib/formatTime"

export const stripProtocol = (url: string) => {
  try { return new URL(url).host } catch { return url.replace(/^https?:\/\//, "").split("/")[0] ?? url }
}

/** Outcome of one connection test run from this page. */
export interface ProviderTestResult {
  success: boolean
  latencyMs: number
  message: string
}

/** A test outcome with the moment it finished (epoch ms). */
export interface TimedTestResult extends ProviderTestResult {
  checkedAt: number
}

const CAPABILITY_LABELS: Record<Capability, string> = {
  search: "Search",
  fetch: "Fetch",
  extract: "Extract",
  neural_search: "Neural search",
  live_crawl: "Live crawl",
  keyless_tier: "Keyless tier",
}

/** Plain-language capability list, never the raw enum values. */
export function capabilityList(capabilities: readonly Capability[]): string {
  return capabilities.map((capability) => CAPABILITY_LABELS[capability]).join(", ")
}

/** One-line text of the last test result for the dialog. */
export function lastResultText(result: TimedTestResult | undefined, now: number): string {
  if (result === undefined) return "—"
  const when = formatRelativeTime(result.checkedAt, now)
  if (result.success) return `Healthy · ${formatLatency(result.latencyMs)} · ${when}`
  return `Failing · ${when}: ${result.message}`
}
