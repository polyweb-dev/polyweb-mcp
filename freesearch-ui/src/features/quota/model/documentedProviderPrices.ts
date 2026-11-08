import type { CRDOperation } from "@/domains/dashboard"
import { formatCRDAmount } from "./crdDisplay"

/** Prices are references researched in LIMITS.md on 2026-10-05. */
export const DOCUMENTED_PRICE_VERSION = "LIMITS.md (2026-10-05)"

export interface DocumentedProviderPrice {
  usdPerCall: string | null
  crdPerCall: string | null
  priceBasis: string
}

type ProviderPrices = Partial<Record<CRDOperation, DocumentedProviderPrice>>

const price = (
  usdPerCall: string | null,
  crdPerCall: string | null,
  priceBasis: string,
): DocumentedProviderPrice => ({
  usdPerCall,
  crdPerCall: crdPerCall === null ? null : formatCRDAmount(crdPerCall),
  priceBasis,
})

const DOCUMENTED_PRICES: Readonly<Record<string, ProviderPrices>> = {
  brave: {
    search: price("0.005", "5", "per search request"),
  },
  keenable: {
    search: price("0.004", "4", "per request (Agent Builder list rate)"),
    fetch: price("0.004", "4", "per request (Agent Builder list rate)"),
  },
  tinyfish: {
    search: price(null, null, "Free at every Wallet balance"),
    fetch: price(null, null, "Free at every Wallet balance"),
  },
  exa: {
    search: price("0.007", "7", "per Fast or Auto search request (up to 10 results)"),
    fetch: price("0.001", "1", "per page, per content type"),
  },
  firecrawl: {
    search: price("0.0076", "7.6", "per search request (up to 10 results, Hobby reference)"),
    fetch: price("0.0038", "3.8", "per page fetched (Hobby reference)"),
  },
  tavily: {
    search: price("0.008", "8", "per basic search request (PAYGO reference)"),
    fetch: price("0.0016", "1.6", "per successful URL (basic extract, PAYGO reference)"),
  },
  parallel: {
    search: price("0.001", "1", "per Turbo or Fast search request (up to 10 results)"),
    fetch: price("0.001", "1", "per extracted URL"),
  },
  youcom: {
    search: price("0.005", "5", "per search request; the first 100 daily calls are a separate free quota"),
    fetch: price("0.001", "1", "per live page"),
  },
}

const KEYLESS_FREE_OPERATIONS: Readonly<Record<string, readonly CRDOperation[]>> = {
  keenable: ["search", "fetch"],
  tavily: ["search", "fetch"],
  firecrawl: ["search", "fetch"],
  parallel: ["search", "fetch"],
  youcom: ["search"],
}

/** Return a documented reference price for a known provider operation. */
export function documentedProviderPrice(
  provider: string,
  operation: CRDOperation,
): DocumentedProviderPrice | null {
  return DOCUMENTED_PRICES[provider]?.[operation] ?? null
}

/** Whether this operation is free on the documented, currently selected rail. */
export function isDocumentedFreeOperation(
  provider: string,
  operation: CRDOperation,
  authMode: string,
): boolean {
  if (provider === "tinyfish") return true
  if (authMode !== "keyless") return false
  return KEYLESS_FREE_OPERATIONS[provider]?.includes(operation) ?? false
}
