import { quotaDisplay } from "@/services/quotaDisplay"
import type {
  DashboardQuota,
  ProviderConfig,
  QuotaConfidence,
} from "@/types/freesearch"

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
  const base = provider.quota
  if (!latest) {
    return {
      remaining: base.remaining,
      remainingPercent: base.remainingPercent,
      limit: base.limit,
      unitKind: base.unitKind,
      displayUnit: base.displayUnit,
      confidence: base.observedAt ? base.confidence : null,
      resetAt: base.nextReset !== "—" ? base.nextReset : null,
      window: base.window,
    }
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

export function resolveQuota(provider: ProviderConfig, latestQuota: DashboardQuota | undefined): ResolvedQuota {
  const values = quotaValues(provider, latestQuota)
  const display = quotaDisplay({
    ...values,
    providerId: provider.id,
    keyless: provider.id === "keenable" && provider.keyVaultStatus === "keyless_public",
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
  display: ReturnType<typeof quotaDisplay>
): QuotaCaption | null {
  const noSnapshot = latestQuota === undefined || (latestQuota.remaining === null && latestQuota.limit === null)
  if (!noSnapshot || display.remainingPercent !== null) return null
  if (provider.id === "parallel") {
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

export function formatUsageP95(latency: number | null): string {
  return latency === null ? "—" : latency + "ms"
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
