import { describe, expect, it } from "vitest"
import { constraintText, explainAllocation, formatWindow } from "./capacity"

const BASE = { baseRate: 10, windowSeconds: 60, borrowEnabled: false, effectiveMaxRate: 10, weight: 1, bestEffort: false }

describe("formatWindow", () => {
  it("names the common windows and counts the rest", () => {
    expect(formatWindow(1)).toBe("second")
    expect(formatWindow(60)).toBe("minute")
    expect(formatWindow(3600)).toBe("hour")
    expect(formatWindow(86400)).toBe("day")
    expect(formatWindow(30)).toBe("30 seconds")
  })
})

describe("constraintText", () => {
  it("reads one constraint", () => {
    expect(constraintText({ algorithm: "token_bucket", windowSeconds: 1, limit: 10 })).toBe("10 per second (token bucket)")
    expect(constraintText({ algorithm: "fixed_window", windowSeconds: 120, limit: 5 })).toBe("5 per 120 seconds (fixed window)")
  })
})

describe("explainAllocation", () => {
  it("explains a strict cap", () => {
    expect(explainAllocation(BASE)).toEqual({
      badge: "Strict cap",
      text: "Up to 10 per minute. Unused capacity of other projects is not lent.",
    })
  })

  it("explains loans with weight and effective max", () => {
    expect(explainAllocation({ ...BASE, borrowEnabled: true, effectiveMaxRate: 40, weight: 3 })).toEqual({
      badge: "Loans enabled",
      text:
        "Guaranteed 10 per minute under contention (weight 3). Can borrow up to 40 per minute " +
        "when the pool is idle. The pool limit always applies.",
    })
  })

  it("explains best effort for a zero base", () => {
    expect(explainAllocation({ ...BASE, baseRate: 0, bestEffort: true, borrowEnabled: true })).toEqual({
      badge: "Best effort",
      text: "No guaranteed share. Runs only when the pool has idle capacity.",
    })
  })

  it("keeps strict wording for best effort with a non-zero base", () => {
    expect(explainAllocation({ ...BASE, bestEffort: true }).badge).toBe("Strict cap")
  })
})
