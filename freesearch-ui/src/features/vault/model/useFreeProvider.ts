import { getProviderPrices, toBackendId } from "@/domains/providers"
import { useScopedResource } from "@/shared/lib/useScopedResource"

/** Use the same catalog prices as System Providers; unknown prices are not free. */
export function useFreeProvider(provider: string): boolean {
  const prices = useScopedResource({ scopeKey: "provider-prices", load: getProviderPrices })
  return prices.status === "ready" && (prices.data.find((entry) => entry.providerType === toBackendId(provider))?.free ?? false)
}
