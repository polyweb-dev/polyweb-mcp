import { afterEach, describe, expect, it, vi } from "vitest"
import { installFetchStub, ok } from "@/test/fetchMock"
import {
  decodeProjectProviderView,
  getProjectProviderView,
} from "./providerViewApi"

describe("providerViewApi", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("decodes providers without retaining legacy allocations", () => {
    const view = decodeProjectProviderView({
      project_id: "proj",
      providers: [{ provider_type: "tavily", capability: ["search"] }, { nope: true }],
      allocations: [{ project_id: "proj", pool_id: "pool", operation_scope: "search", base_rate: 1, rate_window_seconds: 1 }],
    })
    expect(view.providers).toHaveLength(1)
    expect(view).not.toHaveProperty("allocations")
  })

  it("rejects a payload without providers", () => {
    expect(() => decodeProjectProviderView({})).toThrow()
  })

  it("decodes provider-level project health independently of credential health", () => {
    const view = decodeProjectProviderView({ providers: [{
      provider_type: "tavily", health_status: "degraded", health_checked_at: "2026-11-08T09:00:00Z",
      credentials: [{ id: "key", health_status: "healthy" }],
    }] })
    expect(view.providers[0]).toMatchObject({ healthStatus: "degraded", healthCheckedAt: "2026-11-08T09:00:00Z" })
  })

  it("reads the view with the signal", async () => {
    const stub = installFetchStub(() => ok({ project_id: "proj", providers: [], allocations: [] }))
    const controller = new AbortController()
    await getProjectProviderView("proj", controller.signal)
    expect(stub.requests[0]?.url).toBe("/api/v1/projects/proj/providers")
    expect(stub.requests[0]?.signal).toBe(controller.signal)
  })

})
