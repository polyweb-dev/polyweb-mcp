import { describe, expect, it } from "vitest"
import { deriveEnvelope } from "./traceTiming"
import type { SpanTiming } from "./traceTiming"

const BASE = Date.parse("2026-10-01T10:00:00Z")
const iso = (ms: number) => new Date(BASE + ms).toISOString()

function timing(startMs: number, endMs: number, overrides: Partial<SpanTiming> = {}): SpanTiming {
  return {
    record: {},
    spanId: "0".repeat(16),
    name: "span",
    startedAt: iso(startMs),
    startMs: BASE + startMs,
    endMs: BASE + endMs,
    inconsistent: endMs < startMs,
    ...overrides,
  }
}

describe("deriveEnvelope", () => {
  const summary = (startMs: number) => ({ startedAt: iso(startMs), startMs: BASE + startMs })

  it("spans the earliest consistent start to the latest end", () => {
    const envelope = deriveEnvelope([timing(10, 60), timing(20, 90)], summary(10))

    expect(envelope).toMatchObject({ startMs: BASE + 10, endMs: BASE + 90, totalMs: 80, spansTotalMs: 80 })
  })

  it("ignores the start of an inconsistent root but keeps its end", () => {
    // Root: started 2_000 ms, ended 460 ms (end before start); children are correct.
    const envelope = deriveEnvelope(
      [timing(2000, 460), timing(0, 34), timing(35, 429), timing(464, 464)],
      summary(2000)
    )

    expect(envelope?.startedAt).toBe(iso(0))
    expect(envelope?.totalMs).toBe(464)
    expect(envelope?.spansTotalMs).toBe(464)
  })

  it("lets an earlier summary start widen the axis but not the work length", () => {
    const envelope = deriveEnvelope([timing(100, 110)], summary(0))

    expect(envelope).toMatchObject({ totalMs: 110, spansTotalMs: 10 })
  })

  it("has no envelope without a consistent span or with unparsable starts", () => {
    expect(deriveEnvelope([], summary(0))).toBeNull()
    expect(deriveEnvelope([timing(500, 100)], summary(500))).toBeNull()
    expect(deriveEnvelope([timing(0, 10, { startMs: Number.NaN, endMs: Number.NaN })], summary(0))).toBeNull()
  })
})
