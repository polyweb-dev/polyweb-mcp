import { describe, expect, it } from "vitest"
import { quotaDisplay } from "./quotaDisplay"

/**
 * Native Tavily quota labels: Tavily CREDIT values read as `Credits` and
 * every other provider keeps the shared unit label.
 */

describe("quotaDisplay Tavily Credits", () => {
  it("labels Tavily CREDIT values as Credits", () => {
    const display = quotaDisplay({
      remaining: "999",
      limit: "1000",
      unitKind: "CREDIT",
      displayUnit: null,
      confidence: "observed",
      resetAt: null,
      providerId: "tavily",
    })
    expect(display.nativeLabel).toBe("Credits")
    expect(display.nativeValue).toBe("999/1000 Credits")
  })

  it("keeps the Credits label for Tavily CREDIT regardless of display text", () => {
    const display = quotaDisplay({
      remaining: "998",
      limit: "1000",
      unitKind: "CREDIT",
      displayUnit: "CREDIT",
      confidence: "observed",
      resetAt: null,
      providerId: "tavily",
    })
    expect(display.nativeLabel).toBe("Credits")
    expect(display.nativeValue).toBe("998/1000 Credits")
  })

  it("leaves other providers on the shared lowercase credits label", () => {
    const display = quotaDisplay({
      remaining: "4500",
      limit: "5000",
      unitKind: "CREDIT",
      displayUnit: null,
      confidence: "observed",
      resetAt: null,
      providerId: "brave",
    })
    expect(display.nativeLabel).toBe("credits")
    expect(display.nativeValue).toBe("4500/5000 credits")
  })

  it("leaves Tavily non-credit units on the shared label", () => {
    const display = quotaDisplay({
      remaining: "50",
      limit: "100",
      unitKind: "REQUEST",
      displayUnit: null,
      confidence: "observed",
      resetAt: null,
      providerId: "tavily",
    })
    expect(display.nativeLabel).toBe("requests")
  })
})
