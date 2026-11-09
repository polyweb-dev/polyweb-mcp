import { providerCallCost, type ProviderConfig } from "@/domains/providers"
import type { ProviderInfo } from "./providerInfo"

type QuotaCatalogProvider = ProviderConfig & { free?: boolean; keyless?: boolean }

export function catalogFree(provider: QuotaCatalogProvider | undefined, authMode: string): boolean | null {
  if (authMode !== "keyless" && provider?.free !== undefined) return provider.free
  const costs = authMode === "keyless" ? provider?.keylessCallCostUsd : provider?.callCostUsd
  const values = Object.values(costs ?? {}).filter((value) => value != null)
  return values.length > 0 ? values.every((value) => Number(value) === 0) : null
}

/** The same catalog price source as the System Providers cost column. */
export function catalogQuotaInfo(info: ProviderInfo, provider: ProviderConfig | undefined, authMode: string): ProviderInfo {
  if (!provider || (provider.callCostUsd === undefined && provider.keylessCallCostUsd === undefined)) return info
  const keyless = authMode === "keyless"
  const facts = info.facts.filter((fact) => !/^(Search|Fetch|Extract) cost(?: \(USD\))?$/.test(fact.label))
  for (const operation of ["fetch", "search"] as const) {
    const price = providerCallCost(provider, operation, keyless)
    if (price === "—") continue
    const name = operation === "fetch" && provider.id === "tavily" ? "Extract" : operation === "fetch" ? "Fetch" : "Search"
    const value = price === "Free without a key" ? "Free" : price
    facts.unshift({ label: name + (value === "Free" ? " cost" : " cost (USD)"), value, note: null })
  }
  return { ...info, facts, creditNote: catalogFree(provider, authMode) ? "Free tier" : info.creditNote }
}
