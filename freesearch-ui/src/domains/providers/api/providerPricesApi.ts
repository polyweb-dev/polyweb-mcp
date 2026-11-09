import { requestJson } from "@/shared/api/client"
import { asRecord, decodeList, readFlag, readString } from "@/shared/api/decode"
import { decodeCallCosts } from "../model/providerPricing"
import type { ProviderPricing } from "../model/providerPricing"

export interface ProviderPrice extends ProviderPricing {
  providerType: string
  free: boolean
  keyless: boolean
}

function decodeProviderPrice(value: unknown): ProviderPrice | null {
  const row = asRecord(value)
  const providerType = row && readString(row, "provider_id")
  if (!row || !providerType) return null
  return {
    providerType, free: readFlag(row, "free"), keyless: readFlag(row, "keyless"),
    callCostUsd: decodeCallCosts(row.call_cost_usd),
    keylessCallCostUsd: decodeCallCosts(row.keyless_call_cost_usd),
  }
}

/** Price-only catalog for vault users and project provider readers. */
export async function getProviderPrices(signal?: AbortSignal): Promise<ProviderPrice[]> {
  return decodeList(await requestJson<unknown>("/api/v1/provider-prices", { signal }), decodeProviderPrice, "provider prices")
}
