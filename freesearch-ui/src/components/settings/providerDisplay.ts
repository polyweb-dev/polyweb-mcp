import type { ProviderConfig } from "@/domains/providers"
import { providerQuotaDisplay } from "@/domains/dashboard"

export const stripProtocol = (url: string) => url.replace(/^https?:\/\//, "")
export const formatLatency = (latency: number | null) => latency === null ? "—" : `${latency}ms`
export const formatQuota = (provider: ProviderConfig) => {
  const display = providerQuotaDisplay(provider)
  return `${display.headline} · ${display.periodLabel} · ${display.nativeValue} · ${display.confidenceLabel}`
}
