import { getProviderPrices, toUiId, type ProviderConfig } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"

type QuotaPrice = Awaited<ReturnType<typeof getProviderPrices>>[number]

export function useQuotaPrices(): QuotaPrice[] {
  const resource = useScopedResource({ scopeKey: "quota-provider-prices", load: getProviderPrices })
  return resource.status === "ready" ? resource.data : []
}

/** Price-only catalog results override the cached provider catalog snapshot. */
export function quotaPricedProvider(provider: ProviderConfig, prices: QuotaPrice[]): ProviderConfig {
  const price = prices.find((row) => toUiId(row.providerType) === provider.id)
  return price ? { ...provider, ...price } : provider
}
