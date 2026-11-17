import { afterEach, describe, expect, it, vi } from "vitest"
import { decodeProjectUsage, getProjectDashboard, getProjectUsage } from "./usageApi"
import { installFetchStub, ok } from "@/test/fetchMock"
import { PROJECT_ALPHA_ID } from "@/test/accessFixtures"

const PAYLOAD = {
  project_id: PROJECT_ALPHA_ID,
  totals: [
    { provider: "tavily", operation: "search", total_units: "12.5", event_count: 4, unit_kind: "CREDIT" },
    { provider: "brave", operation: "search", total_units: 3, event_count: 3 },
  ],
  recent_usage: [
    {
      provider: "you",
      operation: "fetch",
      units: "1",
      observed_at: "2026-10-30T10:00:00Z",
      latency_ms: 210,
      status: "failure",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
    { provider: "", operation: "search", units: "1", observed_at: "2026-10-30T10:00:00Z" },
  ],
  generated_at: "2026-10-30T10:00:01Z",
}

describe("usageApi", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("decodes decimal strings and numbers, unit kinds, and drops unusable rows", () => {
    const usage = decodeProjectUsage(PAYLOAD)

    expect(usage.projectId).toBe(PROJECT_ALPHA_ID)
    expect(usage.totals).toEqual([
      {
        provider: "tavily", operation: "search", totalUnits: 12.5, eventCount: 4, unitKind: "CREDIT",
        costUsd: null, costEstimated: false, unpricedCount: 4,
      },
      {
        provider: "brave", operation: "search", totalUnits: 3, eventCount: 3, unitKind: null,
        costUsd: null, costEstimated: false, unpricedCount: 3,
      },
    ])
    expect(usage.recent).toEqual([
      {
        provider: "you",
        operation: "fetch",
        units: 1,
        observedAt: "2026-10-30T10:00:00Z",
        latencyMs: 210,
        status: "failure",
        unitKind: "REQUEST",
        displayUnit: "requests",
      },
    ])
  })

  it("decodes reported and estimated costs with the unpriced event count", () => {
    const totals = decodeProjectUsage({
      totals: [
        {
          provider: "brave", operation: "search", total_units: "1", event_count: 1, unit_kind: "REQUEST",
          cost_usd: "0.005", cost_estimated: true, unpriced_event_count: 0,
        },
        {
          provider: "exa", operation: "search", total_units: "0.007", event_count: 1, unit_kind: "USD",
          cost_usd: 0.007, cost_estimated: false, unpriced_event_count: 0,
        },
        {
          provider: "tavily", operation: "search", total_units: "6", event_count: 3, unit_kind: "CREDIT",
          cost_usd: null, cost_estimated: false, unpriced_event_count: 3,
        },
      ],
    }).totals

    expect(totals.map(({ costUsd, costEstimated, unpricedCount }) => ({ costUsd, costEstimated, unpricedCount }))).toEqual([
      { costUsd: 0.005, costEstimated: true, unpricedCount: 0 },
      { costUsd: 0.007, costEstimated: false, unpricedCount: 0 },
      { costUsd: null, costEstimated: false, unpricedCount: 3 },
    ])
  })

  it("keeps a legacy USD row's dollars and counts no unpriced events for USD or free rows", () => {
    const totals = decodeProjectUsage({
      totals: [
        { provider: "exa", operation: "search", total_units: "0.035", event_count: 6, unit_kind: "USD" },
        { provider: "exa", operation: "fetch", total_units: "0.01", event_count: 1, unit_kind: "USD", cost_usd: null },
        { provider: "keenable", operation: "search", total_units: "0", event_count: 2, unit_kind: "FREE" },
      ],
    }).totals

    expect(totals.map(({ costUsd, costEstimated, unpricedCount }) => ({ costUsd, costEstimated, unpricedCount }))).toEqual([
      { costUsd: 0.035, costEstimated: false, unpricedCount: 0 },
      { costUsd: 0.01, costEstimated: false, unpricedCount: 0 },
      { costUsd: null, costEstimated: false, unpricedCount: 0 },
    ])
  })

  it("treats malformed cost fields like absent ones", () => {
    const [total] = decodeProjectUsage({
      totals: [
        {
          provider: "brave", operation: "search", total_units: "2", event_count: 2, unit_kind: "REQUEST",
          cost_usd: "abc", cost_estimated: "yes", unpriced_event_count: -1,
        },
      ],
    }).totals

    expect(total).toMatchObject({ costUsd: null, costEstimated: false, unpricedCount: 2 })
    expect(decodeProjectUsage({
      totals: [{ provider: "brave", operation: "search", event_count: 2, cost_usd: "-0.01", unpriced_event_count: 1.5 }],
    }).totals[0]).toMatchObject({ costUsd: null, unpricedCount: 2 })
  })

  it("rejects a body that is not an object", () => {
    expect(() => decodeProjectUsage(null)).toThrow()
    expect(decodeProjectUsage({}).totals).toEqual([])
  })

  it("reads the project usage and dashboard routes with the signal", async () => {
    const stub = installFetchStub(() => ok(PAYLOAD))
    const controller = new AbortController()

    await getProjectUsage(PROJECT_ALPHA_ID, controller.signal)
    await getProjectDashboard(PROJECT_ALPHA_ID)

    expect(stub.requests.map((req) => req.url)).toEqual([
      `/api/v1/projects/${PROJECT_ALPHA_ID}/usage`,
      `/api/v1/projects/${PROJECT_ALPHA_ID}/dashboard`,
    ])
    expect(stub.requests[0]?.signal).toBe(controller.signal)
  })
})
