import { beforeEach, describe, expect, it, vi } from "vitest"
import { getProjectOrder, putProjectOrder } from "./projectOrderApi"

const request = vi.hoisted(() => vi.fn())
vi.mock("@/shared/api/client", () => ({ requestJson: request }))

const operation = {
  strategy: "lowest_cost", providers: [{ provider: "tavily", name: "Tavily", call_cost_usd: "0.0076" }],
  has_saved_custom: false, not_allowed: ["brave"],
}

beforeEach(() => { request.mockReset() })

describe("project order API", () => {
  it("decodes both operations and decimal prices", async () => {
    request.mockResolvedValue({ revision: 3, search: operation, fetch: { ...operation, providers: [] } })
    const result = await getProjectOrder("project/1")
    expect(request).toHaveBeenCalledWith("/api/v1/projects/project%2F1/routing/order", { signal: undefined })
    expect(result.search.providers[0]).toEqual({ provider: "tavily", name: "Tavily", callCostUsd: "0.0076", keyless: false })
    expect(result.search.notAllowed).toEqual(["brave"])
    expect(result.fetch.providers).toEqual([])
  })

  it("sends a full custom order", async () => {
    request.mockResolvedValue({ revision: 4, search: operation, fetch: operation })
    await putProjectOrder("p", "search", { strategy: "custom", order: ["tavily", "brave"] })
    expect(request).toHaveBeenCalledWith("/api/v1/projects/p/routing/order/search", {
      method: "PUT", body: JSON.stringify({ strategy: "custom", order: ["tavily", "brave"] }),
    })
  })

  it("decodes keyless flags and defaults absent flags to false", async () => {
    request.mockResolvedValue({ revision: 1, search: {
      ...operation, providers: [
        { provider: "keenable", name: "Keenable", call_cost_usd: 0, keyless: true },
        { provider: "tavily", name: "Tavily", call_cost_usd: 0, keyless: false },
        { provider: "exa", name: "Exa", call_cost_usd: null },
      ],
    }, fetch: operation })
    const result = await getProjectOrder("p")
    expect(result.search.providers.map((provider) => provider.keyless)).toEqual([true, false, false])
  })

  it("rejects malformed responses", async () => {
    request.mockResolvedValue({ revision: 1, search: { ...operation, has_saved_custom: "yes" }, fetch: operation })
    await expect(getProjectOrder("p")).rejects.toThrow("Invalid provider order response.")
  })
})
