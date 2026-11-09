import type { UsdOperation } from "@/domains/dashboard"
import { formatCallCost } from "@/domains/providers"

/** Prices are references researched in LIMITS.md on 2026-10-05. */
export const DOCUMENTED_PRICE_VERSION = "LIMITS.md (2026-10-05)"

export interface DocumentedProviderPrice {
  usdPerCall: string | null
  priceBasis: string
}

type ProviderPrices = Partial<Record<UsdOperation, DocumentedProviderPrice>>

const price = (
  usdPerCall: string | null,
  priceBasis: string,
): DocumentedProviderPrice => ({
  usdPerCall: usdPerCall === null ? null : formatCallCost(usdPerCall),
  priceBasis,
})

const DOCUMENTED_PRICES: Readonly<Record<string, ProviderPrices>> = {
  brave: {
    search: price("0.005", "per search request"),
  },
  keenable: {
    search: price("0.004", "per request (Agent Builder list rate)"),
    fetch: price("0.004", "per request (Agent Builder list rate)"),
  },
  tinyfish: {
    search: price(null, "Free at every Wallet balance"),
    fetch: price(null, "Free at every Wallet balance"),
  },
  exa: {
    search: price("0.007", "per Fast or Auto search request (up to 10 results)"),
    fetch: price("0.001", "per page, per content type"),
  },
  firecrawl: {
    search: price("0.0076", "per search request (up to 10 results, Hobby reference)"),
    fetch: price("0.0038", "per page fetched (Hobby reference)"),
  },
  tavily: {
    search: price("0.008", "per basic search request (PAYGO reference)"),
    fetch: price("0.0016", "per successful URL (basic extract, PAYGO reference)"),
  },
  parallel: {
    search: price("0.001", "per Turbo or Fast search request (up to 10 results)"),
    fetch: price("0.001", "per extracted URL"),
  },
  youcom: {
    search: price("0.005", "per search request; the first 100 daily calls are a separate free quota"),
    fetch: price("0.001", "per live page"),
  },
}

const KEYLESS_FREE_OPERATIONS: Readonly<Record<string, readonly UsdOperation[]>> = {
  keenable: ["search", "fetch"],
  tavily: ["search", "fetch"],
  firecrawl: ["search", "fetch"],
  parallel: ["search", "fetch"],
  youcom: ["search"],
}

/** Return a documented reference price for a known provider operation. */
export function documentedProviderPrice(
  provider: string,
  operation: UsdOperation,
): DocumentedProviderPrice | null {
  return DOCUMENTED_PRICES[provider]?.[operation] ?? null
}

/** Whether this operation is free on the documented, currently selected rail. */
export function isDocumentedFreeOperation(
  provider: string,
  operation: UsdOperation,
  authMode: string,
): boolean {
  if (provider === "tinyfish") return true
  if (authMode !== "keyless") return false
  return KEYLESS_FREE_OPERATIONS[provider]?.includes(operation) ?? false
}
