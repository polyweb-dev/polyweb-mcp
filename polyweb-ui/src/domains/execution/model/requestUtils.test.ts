import { describe, expect, it } from "vitest"
import { clampLimit, withTimeout } from "./requestUtils"

describe("requestUtils", () => {
  it("aborts the linked signal when the owner aborts", () => {
    const owner = new AbortController()
    const signal = withTimeout(owner.signal, 10_000)
    expect(signal.aborted).toBe(false)
    owner.abort()
    expect(signal.aborted).toBe(true)
    expect((signal.reason as DOMException).name).toBe("AbortError")
  })

  it("aborts the linked signal when the timeout budget ends, leaving the owner live", async () => {
    const owner = new AbortController()
    const signal = withTimeout(owner.signal, 5)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(signal.aborted).toBe(true)
    expect((signal.reason as DOMException).name).toBe("TimeoutError")
    expect(owner.signal.aborted).toBe(false)
  })

  it("starts aborted for an owner that already aborted", () => {
    const owner = new AbortController()
    owner.abort()
    expect(withTimeout(owner.signal, 10_000).aborted).toBe(true)
  })

  it("clamps the result limit to 1..100", () => {
    expect(clampLimit(0)).toBe(1)
    expect(clampLimit(2.7)).toBe(2)
    expect(clampLimit(500)).toBe(100)
    expect(clampLimit(Number.NaN)).toBe(1)
  })
})
