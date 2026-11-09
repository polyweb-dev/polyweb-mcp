import { describe, expect, it } from "vitest"
import {
  deriveTraceLatencySummary,
  selectUserTraceStages,
} from "./tracePresentation"
import type { TraceProviderAttempt, TraceStage } from "./types"

let sequence = 0

function stage(overrides: Partial<TraceStage> = {}): TraceStage {
  sequence += 1
  return {
    spanId: `span-${sequence}`,
    parentSpanId: null,
    name: "polyweb.backend",
    label: "Backend handling",
    providerId: null,
    kind: "internal",
    startedAt: "2026-09-29T09:15:00.000000Z",
    durationMs: 10,
    offsetMs: 0,
    outcome: "success",
    error: null,
    events: [],
    ...overrides,
  }
}

function attempt(overrides: Partial<TraceProviderAttempt> = {}): TraceProviderAttempt {
  sequence += 1
  return {
    spanId: `attempt-${sequence}`,
    providerId: "tavily",
    providerLabel: "Tavily",
    offsetMs: 0,
    durationMs: 100,
    outcome: "success",
    error: null,
    resultCount: 2,
    results: [],
    ...overrides,
  }
}

/**
 * tracePresentation (PLAN §4 R2): the visible trajectory rows — total, route
 * selection, backend handling, provider attempts, results assembly, response
 * to caller — plus the two-hop latency summary over the union (never the sum)
 * of the recorded provider intervals.
 */
describe("selectUserTraceStages", () => {
  it("drops http, parse, and unknown spans without touching the decoded data", () => {
    const total = stage({ name: "POST /search", label: "Search request" })
    const http = stage({ name: "polyweb.provider.http", label: "Provider HTTP call" })
    const parse = stage({ name: "polyweb.provider.parse", label: "Provider response parse" })
    const unknown = stage({ name: "custom.unknown", label: "Custom span" })
    const input = [total, http, parse, unknown]

    expect(selectUserTraceStages(input).map((row) => row.name)).toEqual([
      "POST /search",
    ])
    expect(input).toHaveLength(4)
  })

  it("orders rows total, route, backend, providers, assembly, response", () => {
    const input = [
      stage({ name: "polyweb.response", label: "Response to caller", offsetMs: 240 }),
      stage({ name: "polyweb.provider", label: "Tavily request", offsetMs: 30 }),
      stage({ name: "polyweb.backend", label: "Backend handling", offsetMs: 5 }),
      stage({ name: "polyweb.route", label: "Route selection", offsetMs: 1 }),
      stage({ name: "polyweb.results", label: "Results assembly", offsetMs: 230 }),
      stage({ name: "POST /search", label: "Search request", offsetMs: 0 }),
    ]

    expect(selectUserTraceStages(input).map((row) => row.name)).toEqual([
      "POST /search",
      "polyweb.route",
      "polyweb.backend",
      "polyweb.provider",
      "polyweb.results",
      "polyweb.response",
    ])
  })

  it("orders repeated provider attempts by offset", () => {
    const late = stage({ name: "polyweb.provider", label: "Late request", offsetMs: 100 })
    const early = stage({ name: "polyweb.provider", label: "Early request", offsetMs: 20 })

    expect(
      selectUserTraceStages([late, early]).map((row) => row.label)
    ).toEqual(["Early request", "Late request"])
  })

  it("keeps wire order for provider attempts with equal offsets", () => {
    const first = stage({ name: "polyweb.provider", label: "First request", offsetMs: 50 })
    const second = stage({ name: "polyweb.provider", label: "Second request", offsetMs: 50 })
    const earliest = stage({ name: "polyweb.provider", label: "Earliest request", offsetMs: 20 })

    expect(
      selectUserTraceStages([first, second, earliest]).map((row) => row.label)
    ).toEqual(["Earliest request", "First request", "Second request"])
  })

  it("preserves POST /fetch as the fetch-total row", () => {
    const input = [
      stage({ name: "polyweb.provider", label: "Keenable request", offsetMs: 6 }),
      stage({ name: "POST /fetch", label: "Fetch request", offsetMs: 0 }),
    ]

    expect(selectUserTraceStages(input).map((row) => row.name)).toEqual([
      "POST /fetch",
      "polyweb.provider",
    ])
  })
})

describe("deriveTraceLatencySummary", () => {
  it("counts overlapping provider time once instead of summing durations", () => {
    const summary = deriveTraceLatencySummary(
      [attempt({ offsetMs: 0, durationMs: 100 }), attempt({ offsetMs: 50, durationMs: 100 })],
      1000
    )

    expect(summary.providerActiveMs).toBe(150)
    expect(summary.outsideProvidersMs).toBe(850)
    expect(summary.beforeProvidersMs).toBe(0)
    expect(summary.afterProvidersMs).toBe(850)
    expect(summary.betweenProvidersMs).toBe(0)
  })

  it("reports disjoint gaps as between-providers time", () => {
    const summary = deriveTraceLatencySummary(
      [attempt({ offsetMs: 0, durationMs: 100 }), attempt({ offsetMs: 200, durationMs: 100 })],
      1000
    )

    expect(summary.providerActiveMs).toBe(200)
    expect(summary.outsideProvidersMs).toBe(800)
    expect(summary.beforeProvidersMs).toBe(0)
    expect(summary.betweenProvidersMs).toBe(100)
    expect(summary.afterProvidersMs).toBe(700)
  })

  it("reports the time before the first provider call", () => {
    const summary = deriveTraceLatencySummary(
      [attempt({ offsetMs: 100, durationMs: 100 })],
      1000
    )

    expect(summary.providerActiveMs).toBe(100)
    expect(summary.outsideProvidersMs).toBe(900)
    expect(summary.beforeProvidersMs).toBe(100)
    expect(summary.betweenProvidersMs).toBe(0)
    expect(summary.afterProvidersMs).toBe(800)
  })

  it("clamps provider intervals that run past the trace end", () => {
    const summary = deriveTraceLatencySummary(
      [attempt({ offsetMs: 900, durationMs: 500 })],
      1000
    )

    expect(summary.providerActiveMs).toBe(100)
    expect(summary.outsideProvidersMs).toBe(900)
    expect(summary.afterProvidersMs).toBe(0)
    expect(summary.beforeProvidersMs).toBe(900)
    expect(summary.betweenProvidersMs).toBe(0)
  })

  it("clamps provider intervals that start before the trace start", () => {
    const summary = deriveTraceLatencySummary(
      [attempt({ offsetMs: -50, durationMs: 200 })],
      1000
    )

    expect(summary.providerActiveMs).toBe(150)
    expect(summary.outsideProvidersMs).toBe(850)
  })

  it("treats zero-duration attempts as no provider time", () => {
    const summary = deriveTraceLatencySummary(
      [attempt({ offsetMs: 100, durationMs: 0 })],
      1000
    )

    expect(summary.providerActiveMs).toBe(0)
    expect(summary.beforeProvidersMs).toBe(0)
    expect(summary.betweenProvidersMs).toBe(0)
    expect(summary.afterProvidersMs).toBe(0)
    expect(summary.outsideProvidersMs).toBe(1000)
  })

  it("shows total time outside provider calls when no providers ran", () => {
    const summary = deriveTraceLatencySummary([], 500)

    expect(summary).toEqual({
      beforeProvidersMs: 0,
      providerActiveMs: 0,
      betweenProvidersMs: 0,
      afterProvidersMs: 0,
      outsideProvidersMs: 500,
    })
  })
})
