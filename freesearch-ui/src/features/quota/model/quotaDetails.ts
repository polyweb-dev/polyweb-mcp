import { isKeylessQuotaProvider, isMissingQuotaSnapshot, providerQuotaInput, quotaDisplay } from "@/domains/dashboard"
import type { ProviderConfig } from "@/domains/providers"
import type { DashboardQuota, QuotaConfidence } from "@/domains/dashboard"

export interface QuotaValues {
  remaining: string | null
  remainingPercent: string | null
  limit: string | null
  unitKind: ProviderConfig["quota"]["unitKind"]
  displayUnit: string | null
  confidence: QuotaConfidence | null
  resetAt: string | null
  window: string | null
}

export interface ResolvedQuota {
  display: ReturnType<typeof quotaDisplay>
  confidence: QuotaConfidence | null
  resetAt: string | null
  unitKind: ProviderConfig["quota"]["unitKind"]
  displayUnit: string | null
}

export interface QuotaCaption {
  testId: string
  text: string
}

export function quotaValues(provider: ProviderConfig, latest: DashboardQuota | undefined): QuotaValues {
  if (!latest) {
    const { remaining, remainingPercent, limit, unitKind, displayUnit, confidence, resetAt, window } =
      providerQuotaInput(provider)
    return { remaining, remainingPercent: remainingPercent ?? null, limit, unitKind, displayUnit, confidence, resetAt, window: window ?? null }
  }
  return {
    remaining: latest.remaining,
    remainingPercent: latest.remainingPercent,
    limit: latest.limit,
    unitKind: latest.unitKind,
    displayUnit: latest.displayUnit,
    confidence: latest.source,
    resetAt: latest.resetAt,
    window: latest.window,
  }
}

export function resolveQuota(
  provider: ProviderConfig,
  latestQuota: DashboardQuota | undefined,
  isOAuthPaired?: boolean
): ResolvedQuota {
  const values = quotaValues(provider, latestQuota)
  const display = quotaDisplay({
    ...values,
    providerId: provider.id,
    keyless: isKeylessQuotaProvider(provider),
    isOAuthPaired,
  })
  return {
    display,
    confidence: values.confidence,
    resetAt: values.resetAt,
    unitKind: values.unitKind,
    displayUnit: values.displayUnit,
  }
}

export function quotaCaptionFor(
  provider: ProviderConfig,
  latestQuota: DashboardQuota | undefined,
  display: ReturnType<typeof quotaDisplay>,
  isOAuthPaired?: boolean
): QuotaCaption | null {
  const noSnapshot = isMissingQuotaSnapshot(latestQuota)
  if (!noSnapshot || display.remainingPercent !== null) return null
  if (provider.id === "parallel") {
    if (isOAuthPaired) {
      return { testId: "quota-explainer-parallel", text: "Balance will appear after first use." }
    }
    return { testId: "quota-explainer-parallel", text: "No API-key balance endpoint is available. Configure a local monthly USD budget to calculate remaining capacity." }
  }
  if (provider.id === "exa") {
    return { testId: "quota-explainer-exa", text: "Per-response USD spend is tracked. A remaining percentage needs a monthly budget or Exa Admin usage credentials." }
  }
  if (provider.id === "brave") {
    return { testId: "quota-explainer-brave", text: "Brave reports monthly request quota in response headers. An absent or unbounded limit has no remaining percentage." }
  }
  if (provider.id === "keenable") {
    return { testId: "quota-explainer-keenable", text: "Keyless usage is a locally observed Hourly; the shared per-IP pool can include traffic outside this app." }
  }
  return null
}


/** Visible p95 text, empty when the provider reports no latency (never a placeholder). */
export function formatUsageP95(latency: number | null): string {
  return latency === null ? "" : latency + "ms"
}

/** True when a rolling-window reset is in the past (idle snapshot, recovers on next use). */
export function isStaleRollingQuota(resetAt: string | null): boolean {
  if (!resetAt) return false
  const time = new Date(resetAt).getTime()
  return !Number.isNaN(time) && time < Date.now()
}

export function formatQuotaDate(value: string): string {
  const date = new Date(value + "T00:00:00")
  return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString(undefined, { month: "short", day: "numeric" })
}

export function formatQuotaReset(resetAt: string | null, period: string, fallback: string): string {
  if (!resetAt || period.toLowerCase() !== "hourly") return fallback
  const date = new Date(resetAt)
  if (Number.isNaN(date.getTime())) return fallback
  return date.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit", hour12: true })
}
