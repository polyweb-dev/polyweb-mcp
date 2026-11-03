import { afterEach, describe, expect, it, vi } from "vitest"
import { installFetchStub, ok } from "@/test/fetchMock"
import {
  createPool,
  deleteAllocation,
  deletePoolLink,
  listPoolLinks,
  listPools,
  listProjectAllocations,
  putAllocation,
  putPoolLink,
  updatePool,
} from "./capacityApi"
import type { AllocationInput, PoolInput } from "../model/capacity"

const POOL = { id: "pool", provider_type: "tavily", upstream_scope: "account", pool_key: "k", label: "L", constraints: [], max_concurrency: null, max_queued_requests: null, status: "active", version: 1 }
const LINK = { credential_id: "c", pool_id: "pool", operation_scope: "search", provider_type: "tavily", version: 1 }
const ALLOCATION = { project_id: "proj", pool_id: "pool", operation_scope: "search", base_rate: 5, rate_window_seconds: 60, borrow_enabled: false, max_rate: null, effective_max_rate: 5, weight: 1, best_effort: false, version: 1 }

const POOL_INPUT: PoolInput = {
  providerType: "tavily",
  upstreamScope: "account",
  poolKey: "k",
  label: "L",
  constraints: [{ algorithm: "token_bucket", windowSeconds: 1, limit: 10 }],
  maxConcurrency: 2,
  maxQueuedRequests: null,
  status: "disabled",
}

const STRICT: AllocationInput = {
  baseRate: 5,
  windowSeconds: 60,
  borrowEnabled: false,
  maxRate: 99,
  weight: 1,
  bestEffort: false,
  maxConcurrency: null,
  maxQueuedRequests: null,
  maxQueuedBytes: null,
  maxQueueWaitMs: null,
}

function answer(req: { method: string; url: string }): Response {
  if (req.method === "DELETE") return new Response(null, { status: 204 })
  if (req.url.includes("/allocations")) return ok(req.method === "GET" ? [ALLOCATION] : ALLOCATION)
  if (req.url.includes("/links")) return ok(req.method === "GET" ? [LINK] : LINK)
  return ok(req.method === "GET" ? [POOL] : POOL)
}

describe("capacityApi", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("creates a pool with the provider and updates it with the status", async () => {
    const stub = installFetchStub(answer)
    expect(await listPools()).toHaveLength(1)
    await createPool(POOL_INPUT)
    await updatePool("pool", POOL_INPUT)
    expect(stub.requests[1]?.body).toEqual({
      provider_type: "tavily",
      upstream_scope: "account",
      pool_key: "k",
      label: "L",
      constraints: [{ algorithm: "token_bucket", window_seconds: 1, limit: 10 }],
      max_concurrency: 2,
      max_queued_requests: null,
    })
    expect(stub.requests[2]?.method).toBe("PATCH")
    expect(stub.requests[2]?.body).toMatchObject({ status: "disabled" })
    expect(stub.requests[2]?.body).not.toHaveProperty("provider_type")
  })

  it("links with the operation in the query", async () => {
    const stub = installFetchStub(answer)
    expect(await listPoolLinks("pool")).toHaveLength(1)
    await putPoolLink("pool", "c", "fetch")
    await deletePoolLink("pool", "c", "fetch")
    expect(stub.requests[1]?.url).toBe("/api/v1/system/pools/pool/links/c?operation_scope=fetch")
    expect(stub.requests[1]?.method).toBe("PUT")
    expect(stub.requests[2]?.method).toBe("DELETE")
  })

  it("writes a strict allocation with max_rate null", async () => {
    const stub = installFetchStub(answer)
    expect(await listProjectAllocations("proj")).toHaveLength(1)
    await putAllocation({ projectId: "proj", poolId: "pool", operation: "search" }, STRICT)
    await deleteAllocation("proj", "pool", "search")
    expect(stub.requests[1]?.url).toBe("/api/v1/system/projects/proj/allocations/pool?operation_scope=search")
    expect(stub.requests[1]?.body).toMatchObject({ base_rate: 5, rate_window_seconds: 60, borrow_enabled: false, max_rate: null, weight: 1 })
    expect(stub.requests[2]?.method).toBe("DELETE")
  })

  it("keeps max_rate with loans", async () => {
    const stub = installFetchStub(answer)
    await putAllocation({ projectId: "proj", poolId: "pool", operation: "search" }, { ...STRICT, borrowEnabled: true, maxRate: 20 })
    expect(stub.requests[0]?.body).toMatchObject({ borrow_enabled: true, max_rate: 20 })
  })
})
