import { describe, expect, it } from "vitest"
import { mapTraceDetail } from "./mappers"
import {
  buildTraceStageTree,
  deriveLatencyBreakdown,
  deriveProviderAttempts,
} from "./traceDerivations"
import type { TraceStage } from "./types"
import {
  aggregatedTraceDetailFixture,
  traceDetailFixture,
} from "@/test/fixtures/activity"

/**
 * Pure provider/latency/tree derivations (PLAN §3.1): one attempt per
 * `freesearch.provider` span, evidence-only naming, union-complement
 * processing math, and a cycle-safe stage tree. No guessing, no invented
 * ranks — missing signals stay missing.
 */
function stage(
  overrides: { spanId: string } & Partial<Omit<TraceStage, "spanId" | "providerId">> & {
    providerId?: string | null
  },
): TraceStage {
  return {
    parentSpanId: null,
    name: "freesearch.provider",
    label: "Provider request",
    kind: "client",
    providerId: null,
    startedAt: "2026-09-29T09:15:00.000000Z",
    durationMs: 100,
    offsetMs: 0,
    outcome: "success",
    error: null,
    events: [],
    ...overrides,
  }
}

describe("deriveProviderAttempts", () => {
  it("derives one attempt per provider span in wire order", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const attempts = deriveProviderAttempts(detail.stages, detail.provider)

    expect(attempts.map((attempt) => attempt.spanId)).toEqual([
      "a100000000000003",
      "a100000000000006",
      "b100000000000001",
      "c100000000000001",
      "d100000000000001",
      "e100000000000001",
      "f100000000000001",
    ])
  })

  it("never promotes HTTP or parse children to provider rows", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const attempts = deriveProviderAttempts(detail.stages, detail.provider)

    expect(attempts).toHaveLength(7)
    for (const attempt of attempts) {
      const source = detail.stages.find((stage) => stage.spanId === attempt.spanId)!
      expect(source.name).toBe("freesearch.provider")
    }
  })

  it("names attempts from consistent result sources", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const attempts = deriveProviderAttempts(detail.stages, detail.provider)

    expect(attempts[0]).toMatchObject({ providerId: "keenable", providerLabel: "Keenable" })
    expect(attempts[1]).toMatchObject({ providerId: "tavily", providerLabel: "Tavily" })
  })

  it("preserves the original per-provider result order", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const [keenable] = deriveProviderAttempts(detail.stages, detail.provider)

    expect(keenable?.results.map((result) => result.score)).toEqual([0.92, 0.78, 0.65])
    expect(keenable?.resultCount).toBe(3)
  })

  it("falls back to the summary provider for a single-provider trace", () => {
    const detail = mapTraceDetail(traceDetailFixture())
    // The single-provider fixture records a result_count without a results
    // array, so the count is kept while the summary provider names the row.
    const attempts = deriveProviderAttempts(detail.stages, detail.provider)

    expect(attempts).toHaveLength(1)
    expect(attempts[0]).toMatchObject({ providerId: "keenable", providerLabel: "Keenable" })
    expect(attempts[0]?.results).toEqual([])
    expect(attempts[0]?.resultCount).toBe(2)
  })

  it("marks unnamed fanout attempts instead of guessing from span order", () => {
    const stages = [
      stage({ spanId: "aabbccddeeff0011", offsetMs: 0, durationMs: 100 }),
      stage({ spanId: "aabbccddeeff0022", offsetMs: 10, durationMs: 100 }),
    ]
    const attempts = deriveProviderAttempts(stages, "aggregated")

    expect(attempts[0]).toMatchObject({
      providerId: null,
      providerLabel: "Provider attempt 1",
    })
    expect(attempts[1]).toMatchObject({
      providerId: null,
      providerLabel: "Provider attempt 2",
    })
  })

  it("treats mixed result sources as no evidence and uses the summary fallback", () => {
    const mixed = stage({
      spanId: "aabbccddeeff0011",
      offsetMs: 0,
      durationMs: 100,
      events: [
        {
          name: "freesearch.provider.response",
          timestamp: "2026-09-29T09:15:00.001000Z",
          attributes: {
            result_count: 2,
            results: [
              { title: "A", url: "https://example.com/a", source: "keenable", score: 1 },
              { title: "B", url: "https://example.com/b", source: "tavily", score: 0.5 },
            ],
          },
        },
      ],
    })
    const [attempt] = deriveProviderAttempts([mixed], "keenable")

    expect(attempt?.providerId).toBe("keenable")
  })

  it("returns no attempts when no provider span was recorded", () => {
    expect(deriveProviderAttempts([], "keenable")).toEqual([])
  })
})

describe("deriveLatencyBreakdown", () => {
  it("computes FreeSearch processing as the complement of merged overlapping calls", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const attempts = deriveProviderAttempts(detail.stages, detail.provider)
    const breakdown = deriveLatencyBreakdown(attempts, detail.totalMs)

    // Keenable [20,2045] + Tavily [46,3269] merge to [20,3269]; the complement
    // in [0,3381] is a 20ms preface plus a 112ms tail.
    expect(breakdown.processingSegments).toEqual([
      { offsetMs: 0, durationMs: 20 },
      { offsetMs: 3269, durationMs: 112 },
    ])
    expect(breakdown.processingMs).toBe(132)
    expect(breakdown.providerAttempts).toHaveLength(7)
  })

  it("keeps separate pre, between, and post processing segments", () => {
    const attempts = [
      { offsetMs: 10, durationMs: 10 },
      { offsetMs: 30, durationMs: 10 },
    ].map((timing, index) =>
      stage({ spanId: `aabbccddeeff000${index + 1}`, ...timing })
    )
    const derived = attempts.map((item) => ({
      spanId: item.spanId,
      providerId: "keenable",
      providerLabel: "Keenable",
      offsetMs: item.offsetMs,
      durationMs: item.durationMs,
      outcome: "success" as const,
      error: null,
      resultCount: null,
      results: [],
    }))
    const breakdown = deriveLatencyBreakdown(derived, 50)

    expect(breakdown.processingSegments).toEqual([
      { offsetMs: 0, durationMs: 10 },
      { offsetMs: 20, durationMs: 10 },
      { offsetMs: 40, durationMs: 10 },
    ])
    expect(breakdown.processingMs).toBe(30)
  })

  it("clips provider intervals to the trace window", () => {
    const derived = [
      {
        spanId: "aabbccddeeff0011",
        providerId: "keenable",
        providerLabel: "Keenable",
        offsetMs: -50,
        durationMs: 500,
        outcome: "success" as const,
        error: null,
        resultCount: null,
        results: [],
      },
    ]
    const breakdown = deriveLatencyBreakdown(derived, 100)

    expect(breakdown.processingSegments).toEqual([])
    expect(breakdown.processingMs).toBe(0)
  })

  it("treats an empty attempt list as all-processing", () => {
    const breakdown = deriveLatencyBreakdown([], 248)

    expect(breakdown.processingSegments).toEqual([{ offsetMs: 0, durationMs: 248 }])
    expect(breakdown.processingMs).toBe(248)
  })

  it("ignores zero-length attempt intervals", () => {
    const derived = [
      {
        spanId: "aabbccddeeff0011",
        providerId: "keenable",
        providerLabel: "Keenable",
        offsetMs: 10,
        durationMs: 0,
        outcome: "success" as const,
        error: null,
        resultCount: null,
        results: [],
      },
    ]
    const breakdown = deriveLatencyBreakdown(derived, 100)

    expect(breakdown.processingSegments).toEqual([{ offsetMs: 0, durationMs: 100 }])
  })
})

describe("buildTraceStageTree", () => {
  it("nests children under their parents in wire order", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const roots = buildTraceStageTree(detail.stages)

    expect(roots).toHaveLength(1)
    const root = roots[0]
    expect(root).toBeDefined()
    expect(root?.stage.name).toBe("POST /search")
    const backend = root?.children.find(
      (child) => child.stage.name === "freesearch.backend"
    )
    expect(backend).toBeDefined()
    expect(
      (backend?.children ?? []).filter((child) => child.stage.name === "freesearch.provider")
    ).toHaveLength(7)
  })

  it("keeps orphaned stages as top-level nodes in stable order", () => {
    const stages = [
      stage({ spanId: "aabbccddeeff0011", parentSpanId: null }),
      stage({ spanId: "aabbccddeeff0022", parentSpanId: "ffffffffff000000" }),
      stage({ spanId: "aabbccddeeff0033", parentSpanId: "aabbccddeeff0011" }),
    ]
    const roots = buildTraceStageTree(stages)

    expect(roots.map((root) => root.stage.spanId)).toEqual([
      "aabbccddeeff0011",
      "aabbccddeeff0022",
    ])
  })

  it("breaks parent cycles by promoting the loop members to roots", () => {
    const stages = [
      stage({ spanId: "aabbccddeeff0011", parentSpanId: "aabbccddeeff0022" }),
      stage({ spanId: "aabbccddeeff0022", parentSpanId: "aabbccddeeff0011" }),
    ]
    const roots = buildTraceStageTree(stages)

    expect(roots).toHaveLength(2)
  })

  it("returns an empty tree for empty stages", () => {
    expect(buildTraceStageTree([])).toEqual([])
  })
})

/**
 * `stage.providerId` (decoded from `span.provider`) always wins over legacy
 * result-source/summary inference (PLAN §6.3 item 3): direct → consistent
 * source → non-aggregated summary → null.
 */
describe("deriveProviderAttempts direct-field precedence", () => {
  function directStage(
    spanId: string,
    providerId: string | null,
    extras: Partial<TraceStage> = {}
  ): TraceStage {
    return {
      parentSpanId: null,
      name: "freesearch.provider",
      label: "Provider request",
      kind: "client",
      startedAt: "2026-09-29T09:15:00.000000Z",
      durationMs: 100,
      offsetMs: 0,
      outcome: "success",
      error: null,
      events: [],
      ...extras,
      spanId,
      providerId,
    }
  }

  function responseStage(spanId: string, providerId: string | null, source: string): TraceStage {
    return directStage(spanId, providerId, {
      events: [
        {
          name: "freesearch.provider.response",
          timestamp: "2026-09-29T09:15:00.001000Z",
          attributes: {
            result_count: 1,
            results: [{ title: "A", url: "https://example.com/a", source, score: 1 }],
          },
        },
      ],
    })
  }

  it("prefers the direct span field over a conflicting result source", () => {
    const stages = [responseStage("aabbccddeeff0011", "exa", "brave")]

    const [attempt] = deriveProviderAttempts(stages, "tavily")

    expect(attempt).toMatchObject({ providerId: "exa", providerLabel: "Exa" })
  })

  it("prefers the direct span field over a conflicting summary provider", () => {
    const stages = [directStage("aabbccddeeff0011", "firecrawl")]

    const [attempt] = deriveProviderAttempts(stages, "keenable")

    expect(attempt).toMatchObject({ providerId: "firecrawl", providerLabel: "Firecrawl" })
  })

  it("names the failed/empty direct attempt without result evidence", () => {
    const stages = [
      directStage("aabbccddeeff0011", "parallel", {
        outcome: "error",
        error: { type: "http_error", message: "HTTP 502" },
      }),
    ]

    const [attempt] = deriveProviderAttempts(stages, "aggregated")

    expect(attempt).toMatchObject({ providerId: "parallel", providerLabel: "Parallel" })
  })

  it("resolves all seven deterministic fanout identities from the direct field", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const attempts = deriveProviderAttempts(detail.stages, detail.provider)

    expect(attempts).toHaveLength(7)
    expect(attempts.map((attempt) => attempt.providerId)).toEqual([
      "keenable",
      "tavily",
      "brave",
      "exa",
      "firecrawl",
      "youcom",
      "parallel",
    ])
  })

  it("keeps legacy consistent-source fallback when no direct field is present", () => {
    const detail = mapTraceDetail(aggregatedTraceDetailFixture())
    const stripped = detail.stages.map((item) => {
      const copy = { ...item } as unknown as Record<string, unknown>
      delete copy.providerId
      return copy as unknown as TraceStage
    })
    const keenable = stripped.find((item) => item.spanId === "a100000000000003")!
    const attempts = deriveProviderAttempts([keenable], "aggregated")

    expect(attempts[0]).toMatchObject({ providerId: "keenable" })
  })

  it("keeps legacy summary fallback for a single-provider trace without a direct field", () => {
    const legacy = stage({
      spanId: "aabbccddeeff0011",
      offsetMs: 0,
      durationMs: 100,
      events: [],
    })
    const [attempt] = deriveProviderAttempts([legacy], "keenable")

    expect(attempt?.providerId).toBe("keenable")
  })
})
