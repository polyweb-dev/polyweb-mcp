import { afterEach, describe, expect, it, vi } from "vitest"
import { installFetchStub, ok } from "@/test/fetchMock"
import { getProviderPrices } from "./providerPricesApi"

afterEach(() => vi.unstubAllGlobals())

describe("getProviderPrices", () => {
  it("reads only price facts through the vault-safe endpoint", async () => {
    const stub = installFetchStub(() => ok([
      { provider_id: "tavily", call_cost_usd: { search: "0.008", fetch: "0.0016" }, keyless_call_cost_usd: { search: "0", fetch: "0" }, free: false, keyless: true, health: "private" },
      { provider_id: "keenable", call_cost_usd: { search: "0", fetch: "0" }, keyless_call_cost_usd: { search: "0", fetch: "0" }, free: true, keyless: true },
    ]))
    const signal = new AbortController().signal
    const prices = await getProviderPrices(signal)
    expect(stub.requests[0]?.url).toBe("/api/v1/provider-prices")
    expect(prices[0]).toEqual({ providerType: "tavily", callCostUsd: { search: "0.008", fetch: "0.0016" }, keylessCallCostUsd: { search: "0", fetch: "0" }, free: false, keyless: true })
    expect(prices[1]?.free).toBe(true)
    expect(stub.requests[0]?.signal).toBe(signal)
  })
})
