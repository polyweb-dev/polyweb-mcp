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
      { provider: "tavily", operation: "search", totalUnits: 12.5, eventCount: 4, unitKind: "CREDIT" },
      { provider: "brave", operation: "search", totalUnits: 3, eventCount: 3, unitKind: null },
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
