import { describe, expect, it } from "vitest"
import type { ProviderConfig } from "@/domains/providers"
import { catalogFree, catalogQuotaInfo } from "./catalogQuota"
import type { ProviderInfo } from "./providerInfo"

const provider = { id: "keenable", callCostUsd: { search: "0", fetch: "0" }, keylessCallCostUsd: { search: "0", fetch: "0" } } as ProviderConfig
const info: ProviderInfo = { facts: [{ label: "Search cost (USD)", value: "$0.004", note: null }, { label: "Fetch cost (USD)", value: "$0.004", note: null }], creditNote: "Monthly credits", creditMode: "free", statement: null, usageUrl: null }

describe("quota catalog prices", () => {
  it("replaces stale Keenable rail prices with the catalog prices", () => {
    expect(catalogQuotaInfo(info, provider, "keyless")).toMatchObject({ creditNote: "Free tier", facts: [
      { label: "Search cost (USD)", value: "Free" }, { label: "Fetch cost (USD)", value: "Free" },
    ] })
  })
  it("uses keyed and keyless prices from their respective catalog entries", () => {
    const paid = { ...provider, callCostUsd: { search: "0.008", fetch: "0.0016" } }
    expect(catalogFree(paid, "keyed")).toBe(false)
    expect(catalogFree(paid, "keyless")).toBe(true)
    expect(catalogQuotaInfo(info, paid, "keyed").facts[0]?.value).toBe("$0.0080")
  })
  it("does not infer that an unknown price is free", () => {
    expect(catalogFree(undefined, "keyed")).toBeNull()
    expect(catalogQuotaInfo(info, undefined, "keyed")).toBe(info)
  })
})
