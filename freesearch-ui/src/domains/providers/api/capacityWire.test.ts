import { describe, expect, it } from "vitest"
import { decodeAllocation, decodePool, decodePoolLink } from "./capacityWire"

describe("decodePool", () => {
  it("keeps the pool shape and drops anything else", () => {
    const decoded = decodePool({
      id: "pool-1",
      provider_type: "tavily",
      upstream_scope: "account",
      pool_key: "acct-1",
      label: "Tavily account",
      constraints: [
        { algorithm: "token_bucket", window_seconds: 1, limit: 10 },
        { algorithm: "made_up", window_seconds: 1, limit: 10 },
      ],
      max_concurrency: 4,
      max_queued_requests: null,
      status: "active",
      version: 2,
      balance: 1234,
    })
    expect(decoded).toEqual({
      id: "pool-1",
      providerType: "tavily",
      upstreamScope: "account",
      poolKey: "acct-1",
      label: "Tavily account",
      constraints: [{ algorithm: "token_bucket", windowSeconds: 1, limit: 10 }],
      maxConcurrency: 4,
      maxQueuedRequests: null,
      status: "active",
      version: 2,
    })
  })

  it("drops a pool with an unknown scope", () => {
    expect(decodePool({ id: "p", provider_type: "x", upstream_scope: "planet" })).toBeNull()
  })
})

describe("decodePoolLink", () => {
  it("decodes one link", () => {
    expect(
      decodePoolLink({ credential_id: "c", pool_id: "p", operation_scope: "fetch", provider_type: "tavily", version: 1 })
    ).toEqual({ credentialId: "c", poolId: "p", operation: "fetch", providerType: "tavily", version: 1 })
  })
})

describe("decodeAllocation", () => {
  it("decodes one allocation", () => {
    expect(
      decodeAllocation({
        project_id: "proj",
        pool_id: "pool",
        operation_scope: "search",
        base_rate: 5,
        rate_window_seconds: 60,
        borrow_enabled: true,
        max_rate: 20,
        effective_max_rate: 20,
        weight: 2,
        best_effort: false,
        max_concurrency: null,
        max_queued_requests: 3,
        max_queued_bytes: null,
        max_queue_wait_ms: 500,
        version: 4,
        other_project_usage: 9,
      })
    ).toEqual({
      projectId: "proj",
      poolId: "pool",
      operation: "search",
      baseRate: 5,
      windowSeconds: 60,
      borrowEnabled: true,
      maxRate: 20,
      effectiveMaxRate: 20,
      weight: 2,
      bestEffort: false,
      maxConcurrency: null,
      maxQueuedRequests: 3,
      maxQueuedBytes: null,
      maxQueueWaitMs: 500,
      version: 4,
    })
  })

  it("drops an allocation without a base rate", () => {
    expect(decodeAllocation({ project_id: "p", pool_id: "x", operation_scope: "search", rate_window_seconds: 1 })).toBeNull()
  })
})
