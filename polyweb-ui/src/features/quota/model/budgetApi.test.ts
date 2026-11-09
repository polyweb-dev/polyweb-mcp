import { describe, expect, it, vi } from "vitest"
import { requestJson } from "@/shared/api/client"
import { saveBudget } from "./budgetApi"

vi.mock("@/shared/api/client", () => ({ requestJson: vi.fn().mockResolvedValue({}) }))

describe("quota budget API", () => {
  it("sends decimal USD fields through the USD budget endpoint", async () => {
    await saveBudget("tavily", { auth_mode: "keyed", version: 3, period: "month" as const, search_usd: "1.234567", fetch_usd: "0.0045" })
    const [path, init] = vi.mocked(requestJson).mock.calls[0] ?? []
    expect(path).toBe("/api/v1/providers/tavily/budgets/keyed")
    expect(JSON.parse(String(init?.body))).toEqual({ version: 3, period: "month" as const, search_usd: "1.234567", fetch_usd: "0.0045" })
  })
})
