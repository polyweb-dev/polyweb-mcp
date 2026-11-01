import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { renderHook, waitFor, act } from "@testing-library/react"
import { FreeSearchProvider } from "./FreeSearchContext"
import { useFreeSearch } from "./useFreeSearch"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
import { ADMIN_ACCOUNT_ID, AGENT_ACCOUNT_ID } from "@/test/authFixtures"
import {
  allProvidersFixture,
  routingConfigFixture,
  dashboardFixture,
  canonicalQuotasFixture,
  searchResponseFixture,
  fetchResponseFixture,
  providerTestFixture,
  secretStatusFixture,
  type WireProviderStatus,
} from "@/test/backendFixtures"

/**
 * RED rewrite: the context moves from invented local state
 * (DEFAULT_PROVIDERS, INITIAL_USAGE_EVENTS, INITIAL_CACHE_STATS, sync
 * toggles, mock executeSearch) to live-backend state:
 * - mount: parallel GET /api/v1/providers + GET /api/v1/routing/config +
 *   GET /dashboard?limit=50, per-route failure tolerance (never invented rows)
 * - pessimistic PATCH toggles/priority, POST breaker reset (closed) vs
 *   local-only trip (open, ZERO fetch), PUT/DELETE secrets, PUT routing config
 * - search and fetch execution moved to the project playground scope (U2)
 * - removeProvider + cacheStats are DELETED from the API
 */

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <FreeSearchProvider accountId={ADMIN_ACCOUNT_ID} canReadControls canEditControls>
    {children}
  </FreeSearchProvider>
)

interface FakeBackend {
  providers: WireProviderStatus[]
  routing: Record<string, unknown>
  dashboard: ReturnType<typeof dashboardFixture>
  searchResponse: Record<string, unknown>
  fetchResponse: Record<string, unknown>
  patchGate?: (req: { url: string }) => Promise<Response> | null
}

function createServer(): FakeBackend {
  return {
    providers: allProvidersFixture(),
    routing: routingConfigFixture(),
    dashboard: dashboardFixture(),
    searchResponse: searchResponseFixture(),
    fetchResponse: fetchResponseFixture(),
  }
}

function backendIdFromUrl(url: string): string {
  const match = url.match(/\/api\/v1\/providers\/([^/]+)/)
  return match ? match[1] : ""
}

function installBackend(server: FakeBackend): FetchStub {
  return installFetchStub((req) => {
    if (req.url === "/api/v1/providers" && req.method === "GET") {
      return ok(server.providers)
    }
    if (req.url === "/api/v1/routing/config" && req.method === "GET") {
      return ok(server.routing)
    }
    if (req.url.startsWith("/dashboard") && req.method === "GET") {
      return ok(server.dashboard)
    }
    if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
      const gated = server.patchGate?.(req)
      if (gated) return gated
      const id = backendIdFromUrl(req.url)
      const entry = server.providers.find((p) => p.provider_id === id)
      if (!entry) return err(404, { detail: `unknown provider '${id}'` })
      const patch = (req.body ?? {}) as {
        enable_mask?: unknown
        enabled?: unknown
        search_enabled?: unknown
        fetch_enabled?: unknown
        priority?: unknown
      }
      if (patch.enable_mask !== undefined && typeof patch.enable_mask === "number") {
        entry.enable_mask = patch.enable_mask
      } else {
        if (patch.enabled !== undefined && typeof patch.enabled === "boolean") {
          entry.enable_mask = patch.enabled ? entry.enable_mask | 1 : entry.enable_mask & ~1
        }
        if (patch.search_enabled !== undefined && typeof patch.search_enabled === "boolean") {
          entry.enable_mask = patch.search_enabled
            ? entry.enable_mask | 2
            : entry.enable_mask & ~2
        }
        if (patch.fetch_enabled !== undefined && typeof patch.fetch_enabled === "boolean") {
          entry.enable_mask = patch.fetch_enabled
            ? entry.enable_mask | 4
            : entry.enable_mask & ~4
        }
      }
      if (patch.priority !== undefined && typeof patch.priority === "number") {
        entry.priority = patch.priority
      }
      entry.enabled = (entry.enable_mask & 1) !== 0
      return ok(entry)
    }
    if (req.method === "POST" && req.url.endsWith("/test")) {
      return ok(providerTestFixture({ provider: backendIdFromUrl(req.url) }))
    }
    if (req.method === "POST" && req.url.endsWith("/circuit-breaker/reset")) {
      const id = backendIdFromUrl(req.url)
      const entry = server.providers.find((p) => p.provider_id === id)
      if (entry) {
        entry.circuit_breaker = { state: "closed", updated_at: "2026-09-06T10:06:00Z" }
      }
      return ok({ provider: id, state: "closed", updated_at: "2026-09-06T10:06:00Z" })
    }
    if (req.url.endsWith("/secret") && req.method === "PUT") {
      const id = backendIdFromUrl(req.url)
      return ok(
        secretStatusFixture({ provider: id, fingerprint: `FP_${id}_a1b2`, source: "encrypted_db" })
      )
    }
    if (req.url.endsWith("/secret") && req.method === "DELETE") {
      const id = backendIdFromUrl(req.url)
      return ok(
        secretStatusFixture({
          provider: id,
          presence: "missing",
          fingerprint: null,
          updated_at: "2026-09-06T10:05:00Z",
          source: "none",
        })
      )
    }
    if (req.method === "PUT" && req.url === "/api/v1/routing/config") {
      server.routing = { ...server.routing, ...((req.body as object) ?? {}) }
      return ok(server.routing)
    }
    if (req.url === "/search" && req.method === "POST") {
      return ok(server.searchResponse)
    }
    if (req.url === "/fetch" && req.method === "POST") {
      return ok(server.fetchResponse)
    }
    return err(404, { detail: `unhandled test route ${req.method} ${req.url}` })
  })
}

async function mountLoaded(server?: FakeBackend) {
  const backend = server ?? createServer()
  const stub = installBackend(backend)
  const utils = renderHook(() => useFreeSearch(), { wrapper })
  await waitFor(() => {
    expect(utils.result.current.providersLoading).toBe(false)
  })
  return { stub, backend, ...utils }
}

describe("FreeSearchContext (live backend)", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it("mounts the three routes in parallel and maps backend ids to UI ids", async () => {
    const { stub, result } = await mountLoaded()

    const urls = stub.requests.map((r) => `${r.method} ${r.url}`)
    expect(urls).toContain("GET /api/v1/providers")
    expect(urls).toContain("GET /api/v1/routing/config")
    expect(urls).toContain("GET /dashboard?limit=50")

    expect(result.current.providers).toHaveLength(8)
    expect(result.current.providers.map((p) => p.id)).toContain("youcom")
    expect(result.current.providers.map((p) => p.id)).not.toContain("you")
    expect(result.current.providersLoading).toBe(false)
    expect(result.current.providersError).toBeNull()
    expect(result.current.routingLoading).toBe(false)
    expect(result.current.routingError).toBeNull()
    expect(result.current.usageLoading).toBe(false)
    expect(result.current.usageError).toBeNull()
    expect(result.current.fallbackConfig).toMatchObject({ enabled: true, maxAttempts: 3 })
    expect(result.current.dashboardNotice).toBe(
      "Usage, quota, and health shown here are local-observed only."
    )
    // Dashboard-fed usage: 2 recent events, query targets never populated
    expect(result.current.usageEvents).toHaveLength(2)
    for (const event of result.current.usageEvents) {
      expect(event.queryOrUrl).toBe("")
    }
  })

  it("reports providersLoading while the mount is in flight", async () => {
    const gate = deferred<Response>()
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers") return gate.promise
      if (req.url === "/api/v1/routing/config") return ok(routingConfigFixture())
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled" })
    })
    const utils = renderHook(() => useFreeSearch(), { wrapper })

    // PersistGate opens first (async by design); the providers fetch starts
    // only after the inner providers mount, then stays pending behind the
    // deferred response.
    await waitFor(() => {
      expect(utils.result.current?.providersLoading).toBe(true)
    })

    await act(async () => {
      gate.resolve(ok(allProvidersFixture()))
    })
    await waitFor(() => {
      expect(utils.result.current.providersLoading).toBe(false)
    })
    expect(utils.result.current.providers).toHaveLength(8)
    expect(stub.requestsTo("/api/v1/providers")).toHaveLength(1)
  })

  it("tolerates providers-route failure: empty rows + error + toast, dashboard still loads", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers") return err(500, { detail: "db down" })
      if (req.url === "/api/v1/routing/config") return ok(routingConfigFixture())
      if (req.url.startsWith("/dashboard")) return ok(dashboardFixture())
      return err(404, { detail: "unhandled" })
    })
    const utils = renderHook(() => useFreeSearch(), { wrapper })

    await waitFor(() => {
      expect(utils.result.current.providersLoading).toBe(false)
    })
    // NEVER invented rows on failure
    expect(utils.result.current.providers).toEqual([])
    expect(utils.result.current.providersError).toContain("db down")
    expect(utils.result.current.toasts.some((t) => t.type === "error")).toBe(true)
    // Other routes still succeed independently
    expect(utils.result.current.usageEvents).toHaveLength(2)
  })

  it("tolerates dashboard-route failure: empty usage + usageError, providers still load", async () => {
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers") return ok(allProvidersFixture())
      if (req.url === "/api/v1/routing/config") return ok(routingConfigFixture())
      if (req.url.startsWith("/dashboard"))
        return err(503, { detail: "telemetry unavailable" })
      return err(404, { detail: "unhandled" })
    })
    const utils = renderHook(() => useFreeSearch(), { wrapper })

    await waitFor(() => {
      expect(utils.result.current.usageLoading).toBe(false)
    })
    expect(utils.result.current.usageEvents).toEqual([])
    expect(utils.result.current.usageError).toContain("telemetry unavailable")
    expect(utils.result.current.providers).toHaveLength(8)
  })

  it("deletes removeProvider and cacheStats from the context API", async () => {
    const { result } = await mountLoaded()

    expect("removeProvider" in result.current).toBe(false)
    expect("cacheStats" in result.current).toBe(false)
    // Execution is project-scoped (U2): the account context runs no search or fetch.
    for (const removed of ["runSearch", "runFetch", "activeSearch", "activeFetch", "clearActiveResults"]) {
      expect(removed in result.current).toBe(false)
    }
    expect(typeof result.current.refreshProviders).toBe("function")
    expect(typeof result.current.refreshDashboard).toBe("function")
    expect(typeof result.current.deleteProviderKey).toBe("function")
  })

  it("toggleProvider PATCHes exactly {enabled} and flips state only after 200", async () => {
    const server = createServer()
    const gate = deferred<Response>()
    server.patchGate = () => gate.promise
    const { stub, result } = await mountLoaded(server)

    let togglePromise!: Promise<void>
    act(() => {
      togglePromise = result.current.toggleProvider("brave", false)
    })
    // Pessimistic: no state change before the 200
    expect(
      result.current.providers.find((p) => p.id === "brave")?.globalEnabled
    ).toBe(true)

    const updated = { ...server.providers[0], enable_mask: 6, enabled: false }
    await act(async () => {
      gate.resolve(ok(updated))
      await togglePromise
    })

    const patches = stub.requestsTo(/\/api\/v1\/providers\/brave$/)
    expect(patches).toHaveLength(1)
    expect(patches[0].method).toBe("PATCH")
    expect(patches[0].body).toEqual({ enabled: false })
    await waitFor(() => {
      expect(
        result.current.providers.find((p) => p.id === "brave")?.globalEnabled
      ).toBe(false)
    })
  })

  it("persists per-operation toggles via durable PATCH and keeps composed context behavior", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.toggleProviderSearch("keenable", false)
    })
    expect(
      result.current.providers.find((p) => p.id === "keenable")?.searchEnabled,
    ).toBe(false)
    expect(
      result.current.providers.find((p) => p.id === "keenable")?.enableMask,
    ).toBe(5)
    expect(stub.requestsTo("/api/v1/providers/keenable").at(-1)?.body).toEqual({
      search_enabled: false,
    })

    await act(async () => {
      await result.current.toggleProviderFetch("keenable", false)
    })
    expect(
      result.current.providers.find((p) => p.id === "keenable")?.fetchEnabled,
    ).toBe(false)
    expect(stub.requestsTo("/api/v1/providers/keenable").at(-1)?.body).toEqual({
      fetch_enabled: false,
    })

    // Brave is search-only support (3): admin fetch ON still PATCHes and
    // updates the raw choice, while effective access stays OFF elsewhere.
    await act(async () => {
      await result.current.toggleProviderFetch("brave", true)
    })
    expect(
      result.current.providers.find((p) => p.id === "brave")?.fetchEnabled,
    ).toBe(true)
    expect(stub.requestsTo("/api/v1/providers/brave").at(-1)?.body).toEqual({
      fetch_enabled: true,
    })

    // Exa is fetch-capable: durable fetch toggle flips response state.
    await act(async () => {
      await result.current.toggleProviderFetch("exa", false)
    })
    expect(
      result.current.providers.find((p) => p.id === "exa")?.fetchEnabled,
    ).toBe(false)
    expect(stub.requestsTo("/api/v1/providers/exa").at(-1)?.body).toEqual({
      fetch_enabled: false,
    })
    await act(async () => {
      await result.current.toggleProviderFetch("exa", true)
    })
    expect(
      result.current.providers.find((p) => p.id === "exa")?.fetchEnabled,
    ).toBe(true)
    expect(stub.requestsTo("/api/v1/providers/exa").at(-1)?.body).toEqual({
      fetch_enabled: true,
    })
  })

  it("updateProviderPriority PATCHes {priority} and refreshes from the 200", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.updateProviderPriority("exa", 1)
    })

    const patches = stub.requestsTo("/api/v1/providers/exa")
    expect(patches).toHaveLength(1)
    expect(patches[0].method).toBe("PATCH")
    expect(patches[0].body).toEqual({ priority: 1 })
    await waitFor(() => {
      expect(result.current.providers.find((p) => p.id === "exa")?.priority).toBe(1)
    })
  })

  it("moveProviderPriority issues sequential PATCHes in order, then refreshes providers", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.moveProviderPriority("tavily", "up")
    })

    const patches = stub.requests.filter(
      (r) => r.method === "PATCH" && r.url.startsWith("/api/v1/providers/")
    )
    expect(patches.map((r) => r.url)).toEqual([
      "/api/v1/providers/tavily",
      "/api/v1/providers/keenable",
    ])
    expect(patches[0].body).toEqual({ priority: 2 })
    expect(patches[1].body).toEqual({ priority: 3 })
    // Final refresh re-reads the registry
    const lastGet = stub.requestsTo("/api/v1/providers").filter((r) => r.method === "GET")
    expect(lastGet.length).toBeGreaterThanOrEqual(2)
    await waitFor(() => {
      const ids = result.current.providers.map((p) => p.id)
      expect(ids.indexOf("tavily")).toBeLessThan(ids.indexOf("keenable"))
    })
  })

  it("setCircuitBreaker closed POSTs reset; open trips locally with ZERO fetch", async () => {
    const server = createServer()
    server.providers.find((p) => p.provider_id === "brave")!.circuit_breaker = {
      state: "open",
      updated_at: "2026-09-06T00:00:00Z",
    }
    const { stub, result } = await mountLoaded(server)

    expect(
      result.current.providers.find((p) => p.id === "brave")?.circuitBreaker
    ).toBe("open")

    await act(async () => {
      await result.current.setCircuitBreaker("brave", "closed")
    })
    const resets = stub.requestsTo("/api/v1/providers/brave/circuit-breaker/reset")
    expect(resets).toHaveLength(1)
    expect(resets[0].method).toBe("POST")
    await waitFor(() => {
      expect(
        result.current.providers.find((p) => p.id === "brave")?.circuitBreaker
      ).toBe("closed")
    })

    const callsBeforeTrip = stub.requests.length
    act(() => {
      result.current.setCircuitBreaker("brave", "open")
    })
    expect(
      result.current.providers.find((p) => p.id === "brave")?.circuitBreaker
    ).toBe("open")
    expect(stub.requests.length).toBe(callsBeforeTrip)
  })

  it("testProviderConnection POSTs the probe and returns the mapped result", async () => {
    const { stub, result } = await mountLoaded()

    let probe!: { success: boolean; latencyMs: number; message: string }
    await act(async () => {
      probe = await result.current.testProviderConnection("brave")
    })

    expect(stub.requestsTo("/api/v1/providers/brave/test")[0].method).toBe("POST")
    expect(probe.success).toBe(true)
    expect(probe.latencyMs).toBe(142)
    expect(typeof probe.message).toBe("string")
  })

  it("saveProviderKey PUTs exactly {key}; blank input is ignored with zero fetch", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.saveProviderKey("tavily", "tvly-live-key-123")
    })

    const puts = stub.requestsTo("/api/v1/providers/tavily/secret")
    expect(puts).toHaveLength(1)
    expect(puts[0].method).toBe("PUT")
    expect(puts[0].body).toEqual({ key: "tvly-live-key-123" })
    const row = result.current.providers.find((p) => p.id === "tavily")!
    expect(row.hasKey).toBe(true)
    expect(row.keyMasked).toBe("FP_tavily_a1b2")
    expect(row.keySource).toBe("encrypted_db")
    const successToast = result.current.toasts.find((t) => t.type === "success")
    expect(successToast?.message).toBe("Key stored in the encrypted vault.")

    const callsBefore = stub.requests.length
    await act(async () => {
      await result.current.saveProviderKey("tavily", "   ")
    })
    expect(stub.requests.length).toBe(callsBefore)
  })

  it("deleteProviderKey DELETEs the secret and marks the vault missing", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.deleteProviderKey("tavily")
    })

    const deletes = stub.requestsTo("/api/v1/providers/tavily/secret")
    expect(deletes).toHaveLength(1)
    expect(deletes[0].method).toBe("DELETE")
    const row = result.current.providers.find((p) => p.id === "tavily")!
    expect(row.hasKey).toBe(false)
    expect(row.keyVaultStatus).toBe("missing")
  })

  it("updateFallbackConfig PUTs the full routing body and keeps sub-flags local", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.updateFallbackConfig({
        enabled: false,
        maxAttempts: 5,
        fallbackOnTimeout: false,
      })
    })

    const puts = stub.requestsTo("/api/v1/routing/config")
    expect(puts[puts.length - 1].method).toBe("PUT")
    expect(puts[puts.length - 1].body).toEqual({
      fallback_policy: "first_only",
      cost_optimization_preset: "balanced",
      max_attempts: 5,
    })
    expect(result.current.fallbackConfig).toEqual({
      enabled: false,
      maxAttempts: 5,
      fallbackOnRateLimit: true,
      fallbackOnTimeout: false,
      fallbackOnServerError: true,
    })
  })



  // PG-S5: prefer is dead (deleted with the Depth→number contract) — no
  // prefer-fallback test remains.







  it("updateFallbackConfig failure re-reads the server config (no optimistic state)", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)

    // Server holds chained/3. The PUT fails: the context must issue a
    // follow-up GET and restore state from the server — never keep the
    // optimistic {enabled:false, maxAttempts:5}.
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/routing/config" && req.method === "PUT") {
        return err(500, { detail: "cannot persist routing config" })
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(server.dashboard)
      }
      return err(404, { detail: `unhandled test route ${req.method} ${req.url}` })
    })

    await act(async () => {
      await result.current.updateFallbackConfig({ enabled: false, maxAttempts: 5 })
    })

    const gets = stub
      .requestsTo("/api/v1/routing/config")
      .filter((r) => r.method === "GET")
    expect(gets.length).toBeGreaterThanOrEqual(1)
    expect(result.current.fallbackConfig).toMatchObject({
      enabled: true,
      maxAttempts: 3,
    })
  })

  it("moveProviderPriority failure issues a compensating PATCH then refreshes (no duplicate priorities)", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)

    // tavily(P3) up swaps with keenable(P2). The SECOND PATCH fails: the
    // context must restore tavily to its original priority (3) with a
    // compensating PATCH, then GET-refresh the registry.
    let patchCount = 0
    const stub = installFetchStub((req) => {
      if (req.method === "PATCH" && req.url.startsWith("/api/v1/providers/")) {
        patchCount += 1
        if (patchCount === 2) return err(500, { detail: "cannot persist priority" })
        const id = backendIdFromUrl(req.url)
        const entry = server.providers.find((p) => p.provider_id === id)
        if (!entry) return err(404, { detail: `unknown provider '${id}'` })
        Object.assign(entry, (req.body ?? {}) as object)
        return ok(entry)
      }
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(server.dashboard)
      }
      return err(404, { detail: `unhandled test route ${req.method} ${req.url}` })
    })

    await act(async () => {
      await result.current.moveProviderPriority("tavily", "up")
    })

    const patches = stub.requests.filter(
      (r) => r.method === "PATCH" && r.url.startsWith("/api/v1/providers/")
    )
    // First PATCH (tavily→2) + compensating PATCH restoring tavily→3.
    expect(patches.length).toBeGreaterThanOrEqual(3)
    expect(patches[patches.length - 1].url).toBe("/api/v1/providers/tavily")
    expect(patches[patches.length - 1].body).toEqual({ priority: 3 })
    const gets = stub
      .requestsTo("/api/v1/providers")
      .filter((r) => r.method === "GET")
    expect(gets.length).toBeGreaterThanOrEqual(1)
    const priorities = result.current.providers.map((p) => p.priority)
    expect(new Set(priorities).size).toBe(priorities.length)
  })

  it("updateCostPreset PUTs free_first preserving fallback policy and attempts", async () => {
    const { stub, result } = await mountLoaded()

    const api = result.current as unknown as {
      updateCostPreset: (preset: "balanced" | "free_first") => Promise<void>
    }
    await act(async () => {
      await api.updateCostPreset("free_first")
    })

    const puts = stub.requestsTo("/api/v1/routing/config")
    expect(puts.length).toBeGreaterThanOrEqual(1)
    const lastPut = puts[puts.length - 1]
    expect(lastPut.method).toBe("PUT")
    expect(lastPut.body).toEqual({
      fallback_policy: "chained",
      cost_optimization_preset: "free_first",
      max_attempts: 3,
    })
  })

  it("exposes costOptimizationPreset from the loaded routing config", async () => {
    const server = createServer()
    server.routing = routingConfigFixture({ cost_optimization_preset: "free_first" })
    const { result } = await mountLoaded(server)

    expect(
      (result.current as unknown as { costOptimizationPreset?: string })
        .costOptimizationPreset
    ).toBe("free_first")
  })


  it("RF1: dashboard overlay prefers snapshot values with exact limit strings verbatim", async () => {
    const server = createServer()
    server.dashboard = dashboardFixture({ latest_quota: canonicalQuotasFixture() })
    const { result } = await mountLoaded(server)

    await waitFor(() => {
      expect(result.current.dashboardQuotas).toHaveLength(4)
    })

    // Tavily AUTHORITATIVE: trailing-zero limit must survive verbatim.
    const tavily = result.current.providers.find((p) => p.id === "tavily")!
    expect(tavily.quota.confidence).toBe("authoritative")
    expect(tavily.quota.unitKind).toBe("CREDIT")
    expect(tavily.quota.displayUnit).toBe("credits")
    expect(tavily.quota.remaining).toBe("90000.05")
    const tavilyLimit: unknown = tavily.quota.limit
    expect(typeof tavilyLimit).toBe("string")
    expect(tavilyLimit).toBe("100000.10")
    expect(tavilyLimit).not.toBe("100000.1")

    // Brave OBSERVED: reset passthrough.
    const brave = result.current.providers.find((p) => p.id === "brave")!
    expect(brave.quota.confidence).toBe("observed")
    expect(brave.quota.unitKind).toBe("REQUEST")
    expect(brave.quota.nextReset).toBe("2026-10-01T00:00:00Z")

    // You.com ESTIMATED: limit stays null, never a fabricated cap.
    const youcom = result.current.providers.find((p) => p.id === "youcom")!
    expect(youcom.quota.confidence).toBe("estimated")
    expect(youcom.quota.unitKind).toBe("USD")
    expect(youcom.quota.limit).toBeNull()
    expect(youcom.quota.remaining).toBe("4.75")
  })

  it("RF1: tiny limit strings survive verbatim on the legacy row (never 1e-8)", async () => {
    const server = createServer()
    server.dashboard = dashboardFixture({ latest_quota: canonicalQuotasFixture() })
    const { result } = await mountLoaded(server)

    await waitFor(() => {
      expect(result.current.dashboardQuotas).toHaveLength(4)
    })

    const exa = result.current.providers.find((p) => p.id === "exa")!
    const exaLimit: unknown = exa.quota.limit
    expect(typeof exaLimit).toBe("string")
    expect(exaLimit).toBe("0.00000001")
    expect(String(exaLimit)).not.toContain("e-")
    expect(exa.quota.unitKind).toBeNull()
  })

  it("dashboard overlay leaves providers without snapshots on the honest null placeholder", async () => {
    const { result } = await mountLoaded()

    await waitFor(() => {
      expect(result.current.providersLoading).toBe(false)
    })
    expect(result.current.dashboardQuotas).toEqual([])
    expect(result.current.quotaAvailable).toBe(false)
    const brave = result.current.providers.find((p) => p.id === "brave")!
    expect(brave.quota.limit).toBeNull()
    expect(brave.quota.remaining).toBeNull()
  })


})


/**
 * Agent role without control reads: each control-read refresh returns before
 * its request (empty catalog, local routing defaults, empty telemetry, clear
 * busy flags), so startup makes no control request and the Agent receives no
 * HTTP 403. Search/fetch stay available.
 */
describe("FreeSearchContext Agent without control reads", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  const agentWrapper = ({ children }: { children: React.ReactNode }) => (
    <FreeSearchProvider
      accountId={AGENT_ACCOUNT_ID}
      canReadControls={false}
      canEditControls={false}
    >
      {children}
    </FreeSearchProvider>
  )

  function installAgentBackend(server: FakeBackend, statuses: number[]): FetchStub {
    const record = (response: Response): Response => {
      statuses.push(response.status)
      return response
    }
    return installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return record(ok(server.providers))
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return record(ok(server.routing))
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return record(ok(server.dashboard))
      }
      if (req.url === "/search" && req.method === "POST") {
        return record(ok(server.searchResponse))
      }
      if (req.url === "/fetch" && req.method === "POST") {
        return record(ok(server.fetchResponse))
      }
      return record(err(404, { detail: `unhandled test route ${req.method} ${req.url}` }))
    })
  }

  function controlReads(stub: FetchStub): number {
    return stub.requests.filter(
      (request) =>
        request.method === "GET" &&
        (request.url === "/api/v1/providers" ||
          request.url === "/api/v1/routing/config" ||
          request.url.startsWith("/dashboard"))
    ).length
  }

  async function mountAgent(server?: FakeBackend) {
    const backend = server ?? createServer()
    const statuses: number[] = []
    const stub = installAgentBackend(backend, statuses)
    const utils = renderHook(() => useFreeSearch(), { wrapper: agentWrapper })
    await waitFor(() => {
      expect(utils.result.current.providersLoading).toBe(false)
    })
    return { stub, statuses, backend, ...utils }
  }

  it("starts with no control request, an empty catalog, and clear busy flags", async () => {
    const { stub, statuses, result } = await mountAgent()

    expect(
      stub.requests.filter(
        (request) => request.method === "GET" && request.url === "/api/v1/providers"
      )
    ).toHaveLength(0)
    expect(
      stub.requests.filter(
        (request) => request.method === "GET" && request.url === "/api/v1/routing/config"
      )
    ).toHaveLength(0)
    expect(
      stub.requests.filter(
        (request) => request.method === "GET" && request.url.startsWith("/dashboard")
      )
    ).toHaveLength(0)
    expect(controlReads(stub)).toBe(0)
    expect(result.current.providers).toEqual([])
    expect(statuses.every((status) => status < 400)).toBe(true)
    expect(result.current.providersLoading).toBe(false)
    expect(result.current.routingLoading).toBe(false)
    expect(result.current.usageLoading).toBe(false)
    expect(result.current.providersError).toBeNull()
    expect(result.current.routingError).toBeNull()
    expect(result.current.usageError).toBeNull()
    expect(result.current.canReadControls).toBe(false)
  })


})
