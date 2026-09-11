import { getEligibleProviders } from "@/domains/routing"
import type { ProviderConfig } from "@/domains/providers"
import type { FallbackConfig, RoutingPreset } from "@/domains/routing"

export interface StatusSummary {
  eligibleProviders: ProviderConfig[]
  providerCount: string
  failoverStatus: string
  showFailover: boolean
}

export interface StatusSummaryInput {
  providers: ProviderConfig[]
  routingPreset: RoutingPreset
  fallbackConfig: FallbackConfig
  routingLoading: boolean
  routingError: string | null
}

/** Pure status-summary calculation for the bottom status bar. */
export function getStatusSummary({
  providers,
  routingPreset,
  fallbackConfig,
  routingLoading,
  routingError,
}: StatusSummaryInput): StatusSummary {
  const eligibleProviders = getEligibleProviders(providers, "search", routingPreset)
  const providerCount = `${eligibleProviders.length} of ${providers.length} providers`
  const failoverStatus = `Failover ${fallbackConfig.enabled ? "active" : "inactive"}`
  const showFailover = !routingLoading && !routingError
  return { eligibleProviders, providerCount, failoverStatus, showFailover }
}
