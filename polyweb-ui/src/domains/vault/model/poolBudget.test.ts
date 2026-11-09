import { describe, expect, it } from "vitest"
import { formatPoolBudget } from "./poolBudget"

describe("formatPoolBudget", () => {
  it.each([
    ["day", "today"],
    ["week", "this week"],
    ["month", "this month"],
  ] as const)("formats the %s budget window", (period, suffix) => {
    expect(formatPoolBudget({ limit: 1234.5, period }, 1.236)).toBe(`$1.236 of $1,234.50 ${suffix}`)
  })
})
