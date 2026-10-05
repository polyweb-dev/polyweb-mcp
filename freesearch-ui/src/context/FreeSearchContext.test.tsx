import React from "react"
import { describe, it, expect, afterEach, vi } from "vitest"
import { renderHook, waitFor, act } from "@testing-library/react"
import { FreeSearchProvider } from "./FreeSearchContext"
import { useFreeSearch } from "./useFreeSearch"
import { installFetchStub, ok, err, deferred, type FetchStub } from "@/test/fetchMock"
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
 * - runSearch/runFetch build exact Backend* wire bodies and map responses
 * - removeProvider + cacheStats are DELETED from the API
 */

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <FreeSearchProvider>{children}</FreeSearchProvider>
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

  // PG-S5: SearchRequest drops mode; pinned providers route require,
  // otherwise auto (prefer is dead).
  it.each([[["tavily"], "require"], [undefined, "auto"], [[], "auto"]] as const)(
    "runSearch maps providerIds %j to routing mode %j",
    async (providerIds, routingMode) => {
      const { stub, result } = await mountLoaded()

      let response!: unknown
      await act(async () => {
        response = await result.current.runSearch({
          query: "  live backend query  ",
          providerIds: providerIds as unknown as string[] | undefined,
          maxResults: 6,
          timeoutMs: 5000,
        })
      })

      const searches = stub.requestsTo("/search")
      expect(searches).toHaveLength(1)
      expect(searches[0].method).toBe("POST")
      expect(searches[0].body).toEqual({
        query: "live backend query",
        limit: 6,
        language: null,
        country_code: null,
        domains: [],
        routing: {
          mode: routingMode,
          providers: providerIds ?? [],
          allow_fallback: true,
        },
      })
      expect(searches[0].signal).toBeInstanceOf(AbortSignal)
      expect((response as { query: string }).query).toBe("live backend query")
      expect(result.current.activeSearch?.results[0].title).toBe(
        "Live backend result one"
      )
      expect(result.current.activeSearch?.waterfall).toHaveLength(1)
      expect(result.current.searchError).toBeNull()
    }
  )

  it("runSearch honors require: UI youcom maps to backend you and stays selected", async () => {
    const server = createServer()
    // Contract-valid: the backend honors the require filter and echoes
    // provider "you" (the only conforming success value for require:["you"]).
    server.searchResponse = searchResponseFixture({
      provider: "you",
      usage: {
        provider: "you",
        operation: "search",
        units: "1",
        observed_at: "2026-09-06T10:02:00Z",
        request_id: "req-123",
        metadata: {},
        latency_ms: 187,
        status: "success",
      },
    })
    const { stub, result } = await mountLoaded(server)

    await act(async () => {
      await result.current.runSearch({
        query: "q",
        providerIds: ["youcom"],
        maxResults: 500,
        timeoutMs: 5000,
      })
    })

    expect(stub.requestsTo("/search")[0].body).toMatchObject({
      limit: 100,
      routing: { mode: "require", providers: ["you"], allow_fallback: true },
    })
    expect(result.current.activeSearch?.selectedProviderId).toBe("youcom")
  })

  // PG-S5: prefer is dead (deleted with the Depth→number contract) — no
  // prefer-fallback test remains.

  it("runSearch failure keeps the last-good response and surfaces searchError", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)

    await act(async () => {
      await result.current.runSearch({
        query: "first",
        maxResults: 6,
        timeoutMs: 5000,
      })
    })
    expect(result.current.activeSearch?.query).toBe("live backend query")

    // Point the global fetch at a failing /search while keeping the other
    // routes healthy (the context calls globalThis.fetch per request):
    const failing = installFetchStub((req) => {
      if (req.url === "/search") return err(503, { detail: "no provider is configured" })
      if (req.url === "/api/v1/providers") return ok(server.providers)
      if (req.url === "/api/v1/routing/config") return ok(server.routing)
      if (req.url.startsWith("/dashboard")) return ok(server.dashboard)
      return err(404, { detail: "unhandled" })
    })

    await act(async () => {
      const response = await result.current.runSearch({
        query: "second",
        maxResults: 6,
        timeoutMs: 5000,
      })
      expect(response).toBeNull()
    })

    expect(result.current.activeSearch?.query).toBe("live backend query")
    expect(result.current.searchError).toContain("no provider is configured")
    // Fallback engaged once (primary + next-best), then surfaced: never the
    // same provider twice.
    const searches = failing.requestsTo("/search")
    expect(searches).toHaveLength(2)
    expect(searches[0].body).toMatchObject({ routing: { mode: "auto", providers: [] } })
    expect(searches[1].body).toMatchObject({ routing: { mode: "require" } })
    const tried = searches.map((r) => JSON.stringify((r.body as { routing: { providers: string[] } }).routing.providers))
    expect(new Set(tried).size).toBe(2)
  })

  it("runSearch falls back to the next-best provider when the pinned primary aborts", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)
    let searchCalls = 0
    const retried = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(server.dashboard)
      }
      if (req.url === "/search" && req.method === "POST") {
        searchCalls += 1
        if (searchCalls === 1) {
          // Hung pinned primary: the client timeout aborts it, exactly like
          // the slow first searches in production.
          return new Promise<Response>((_resolve, reject) => {
            req.signal?.addEventListener("abort", () => {
              reject(new DOMException("The operation was aborted due to timeout", "TimeoutError"))
            })
          })
        }
        return ok(
          searchResponseFixture({
            provider: "keenable",
            usage: {
              provider: "keenable",
              operation: "search",
              units: "1",
              observed_at: "2026-09-06T10:02:00Z",
              request_id: "req-fallback",
              metadata: {},
              latency_ms: 210,
              status: "success",
            },
          })
        )
      }
      return err(404, { detail: "unhandled test route" })
    })

    let response: unknown = "unset"
    await act(async () => {
      response = await result.current.runSearch({
        query: "pinned abort",
        providerIds: ["brave"],
        maxResults: 6,
        timeoutMs: 100,
      })
    })

    // Fallback served results with honest attribution and no error surface.
    expect(response).not.toBeNull()
    expect(result.current.searchError).toBeNull()
    expect(result.current.activeSearch?.selectedProviderId).toBe("keenable")
    expect(result.current.activeSearch?.fallbackChain).toEqual(["keenable"])
    const searches = retried.requestsTo("/search")
    expect(searches).toHaveLength(2)
    expect(searches[0].body).toMatchObject({
      routing: { mode: "require", providers: ["brave"] },
    })
    expect(searches[1].body).toMatchObject({
      routing: { mode: "require", providers: ["keenable"] },
    })
  })

  it("runSearch falls back in auto mode when the arbitrated pick fails", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)
    let searchCalls = 0
    const retried = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(server.dashboard)
      }
      if (req.url === "/search" && req.method === "POST") {
        searchCalls += 1
        if (searchCalls === 1) return err(503, { detail: "brave overloaded" })
        return ok(
          searchResponseFixture({
            provider: "keenable",
            usage: {
              provider: "keenable",
              operation: "search",
              units: "1",
              observed_at: "2026-09-06T10:02:00Z",
              request_id: "req-auto-fallback",
              metadata: {},
              latency_ms: 212,
              status: "success",
            },
          })
        )
      }
      return err(404, { detail: "unhandled test route" })
    })

    let response: unknown = "unset"
    await act(async () => {
      response = await result.current.runSearch({
        query: "auto failover",
        maxResults: 6,
        timeoutMs: 5000,
      })
    })

    expect(response).not.toBeNull()
    expect(result.current.searchError).toBeNull()
    expect(result.current.activeSearch?.selectedProviderId).toBe("keenable")
    const searches = retried.requestsTo("/search")
    expect(searches).toHaveLength(2)
    expect(searches[0].body).toMatchObject({
      routing: { mode: "auto", providers: [] },
    })
    // Auto fallback walks past the inferred arbitrated head (brave) to the
    // next-best provider without ever retrying the failed pick.
    expect(searches[1].body).toMatchObject({
      routing: { mode: "require", providers: ["keenable"] },
    })
  })

  it("runSearch does not fall back to a single provider when fanout search fails", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)
    let searchCalls = 0
    const retried = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(server.dashboard)
      }
      if (req.url === "/search" && req.method === "POST") {
        searchCalls += 1
        return err(500, { detail: "all search providers failed" })
      }
      return err(404, { detail: "unhandled test route" })
    })

    let response: unknown = "unset"
    await act(async () => {
      response = await result.current.runSearch({
        query: "failing fanout",
        providerIds: ["brave", "tavily", "exa"],
        fanout: true,
        maxResults: 6,
        timeoutMs: 15000,
      })
    })

    expect(response).toBeNull()
    expect(result.current.searchError).toContain("all search providers failed")
    const searches = retried.requestsTo("/search")
    // Fanout failures do NOT retry with a single provider fallback
    expect(searches).toHaveLength(1)
    expect(searchCalls).toBe(1)
  })

  it("runFetch uses routing require when a providerId is set", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.runFetch({
        url: "https://example.com/doc",
        providerId: "firecrawl",
        format: "markdown",
        timeoutMs: 4000,
      })
    })

    const fetches = stub.requestsTo("/fetch")
    expect(fetches).toHaveLength(1)
    expect(fetches[0].body).toEqual({
      url: "https://example.com/doc",
      max_chars: null,
      routing: { mode: "require", providers: ["firecrawl"], allow_fallback: true },
    })
    expect(result.current.activeFetch?.document.title).toBe("Live document title")
    expect(result.current.fetchError).toBeNull()
  })

  it("runFetch uses auto with empty providers when no providerId is set", async () => {
    const { stub, result } = await mountLoaded()

    await act(async () => {
      await result.current.runFetch({
        url: "https://example.com/doc",
        format: "markdown",
        timeoutMs: 4000,
      })
    })

    const fetches = stub.requestsTo("/fetch")
    expect(fetches).toHaveLength(1)
    expect(fetches[0].body).toEqual({
      url: "https://example.com/doc",
      max_chars: null,
      routing: { mode: "auto", providers: [], allow_fallback: true },
    })
    expect(result.current.fetchError).toBeNull()
  })

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

  it("runSearch times out a hung backend with a friendly timeout error", async () => {
    const { result } = await mountLoaded()

    // Real fetch rejects a hung request when the timeout signal aborts; the
    // stub reproduces that abort rejection (jsdom supports AbortSignal.timeout).
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(allProvidersFixture())
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(routingConfigFixture())
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(dashboardFixture())
      }
      if (req.url === "/search" && req.method === "POST") {
        return new Promise<Response>((_resolve, reject) => {
          req.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted due to timeout", "TimeoutError"))
          })
        })
      }
      return err(404, { detail: `unhandled test route ${req.method} ${req.url}` })
    })

    let response: unknown = "unset"
    await act(async () => {
      response = await result.current.runSearch({
        query: "hung query",
        maxResults: 6,
        timeoutMs: 100,
      })
    })

    expect(response).toBeNull()
    expect(result.current.isSearching).toBe(false)
    expect(result.current.searchError).toMatch(/timed out|timeout/i)
    expect(result.current.searchError).not.toMatch(/was aborted|AbortError|DOMException/i)
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

  it("RF5: runSearch prepends an optimistic local event (id ends -local, null kind, no unit claim)", async () => {
    // Hold the post-search dashboard refresh so the optimistic event stays
    // observable: the refresh GET hangs on a deferred gate.
    const server = createServer()
    const gate = deferred<Response>()
    let dashboardCalls = 0
    const stub = installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        dashboardCalls += 1
        // Initial mount resolves; the refresh triggered by runSearch hangs.
        if (dashboardCalls === 1) return ok(server.dashboard)
        return gate.promise
      }
      if (req.url === "/search" && req.method === "POST") {
        return ok(server.searchResponse)
      }
      return err(404, { detail: "unhandled test route" })
    })
    const utils = renderHook(() => useFreeSearch(), { wrapper })
    await waitFor(() => {
      expect(utils.result.current.providersLoading).toBe(false)
    })
    const before = utils.result.current.usageEvents.length

    await act(async () => {
      await utils.result.current.runSearch({
        query: "optimistic units",
        maxResults: 6,
        timeoutMs: 5000,
      })
    })

    const events = utils.result.current.usageEvents
    expect(events.length).toBe(before + 1)
    const optimistic = events[0]
    expect(optimistic.id.endsWith("-local")).toBe(true)
    expect(optimistic.unitKind).toBeNull()
    expect(optimistic.displayUnit).toBeNull()
    expect(optimistic.providerId).toBe("tavily")
    expect(optimistic.queryOrUrl).toBe("")
    expect(stub.requestsTo("/search")).toHaveLength(1)
    gate.resolve(ok(server.dashboard))
  })

  it("RF5: runFetch prepends an optimistic local event (id ends -local, null kind)", async () => {
    const server = createServer()
    const gate = deferred<Response>()
    let dashboardCalls = 0
    installFetchStub((req) => {
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        dashboardCalls += 1
        if (dashboardCalls === 1) return ok(server.dashboard)
        return gate.promise
      }
      if (req.url === "/fetch" && req.method === "POST") {
        return ok(server.fetchResponse)
      }
      return err(404, { detail: "unhandled test route" })
    })
    const utils = renderHook(() => useFreeSearch(), { wrapper })
    await waitFor(() => {
      expect(utils.result.current.providersLoading).toBe(false)
    })
    const before = utils.result.current.usageEvents.length

    await act(async () => {
      await utils.result.current.runFetch({
        url: "https://example.com/doc",
        providerId: "firecrawl",
        format: "markdown",
        timeoutMs: 4000,
      })
    })

    const events = utils.result.current.usageEvents
    expect(events.length).toBe(before + 1)
    expect(events[0].id.endsWith("-local")).toBe(true)
    expect(events[0].unitKind).toBeNull()
    expect(events[0].displayUnit).toBeNull()
    expect(events[0].operation).toBe("fetch")
    gate.resolve(ok(server.dashboard))
  })
})

/**
 * PLAN §4.1.5: the search/fetch runners publish their lifecycle state through
 * Redux. These tests pin the loading -> succeeded/failed transitions and the
 * explicit clear — the pre-existing API mapping/fallback matrix above stays
 * the regression coverage for request shapes.
 */
describe("FreeSearchContext Redux-backed runner lifecycle", () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function hangRoute(server: FakeBackend, url: string, gate: { promise: Promise<Response> }) {
    return installFetchStub((req) => {
      if (req.url === url && req.method === "POST") return gate.promise
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(server.dashboard)
      }
      if (req.url === "/search" && req.method === "POST") return ok(server.searchResponse)
      if (req.url === "/fetch" && req.method === "POST") return ok(server.fetchResponse)
      return err(404, { detail: "unhandled" })
    })
  }

  function failRoute(server: FakeBackend, url: string, detail: string) {
    return installFetchStub((req) => {
      if (req.url === url && req.method === "POST") return err(503, { detail })
      if (req.url === "/api/v1/providers" && req.method === "GET") {
        return ok(server.providers)
      }
      if (req.url === "/api/v1/routing/config" && req.method === "GET") {
        return ok(server.routing)
      }
      if (req.url.startsWith("/dashboard") && req.method === "GET") {
        return ok(server.dashboard)
      }
      if (req.url === "/search" && req.method === "POST") return ok(server.searchResponse)
      if (req.url === "/fetch" && req.method === "POST") return ok(server.fetchResponse)
      return err(404, { detail: "unhandled" })
    })
  }

  it("publishes search loading, then success, through Redux", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)
    const gate = deferred<Response>()
    hangRoute(server, "/search", gate)

    let pending!: Promise<unknown>
    act(() => {
      pending = result.current.runSearch({ query: "deferred", maxResults: 6, timeoutMs: 5000 })
    })
    expect(result.current.isSearching).toBe(true)
    expect(result.current.activeSearch).toBeNull()
    expect(result.current.searchError).toBeNull()

    await act(async () => {
      gate.resolve(ok(server.searchResponse))
      await pending
    })
    expect(result.current.isSearching).toBe(false)
    expect(result.current.activeSearch?.results[0].title).toBe("Live backend result one")
    expect(result.current.searchError).toBeNull()
  })

  it("publishes search failure through Redux and settles loading", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)
    failRoute(server, "/search", "search exploded")

    let response!: unknown
    await act(async () => {
      response = await result.current.runSearch({
        query: "doomed",
        maxResults: 6,
        timeoutMs: 5000,
      })
    })
    expect(response).toBeNull()
    expect(result.current.isSearching).toBe(false)
    expect(result.current.activeSearch).toBeNull()
    expect(result.current.searchError).toContain("search exploded")
  })

  it("publishes fetch loading, then success, through Redux", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)
    const gate = deferred<Response>()
    hangRoute(server, "/fetch", gate)

    let pending!: Promise<unknown>
    act(() => {
      pending = result.current.runFetch({
        url: "https://example.com/doc",
        format: "markdown",
        timeoutMs: 4000,
      })
    })
    expect(result.current.isFetching).toBe(true)
    expect(result.current.activeFetch).toBeNull()
    expect(result.current.fetchError).toBeNull()

    await act(async () => {
      gate.resolve(ok(server.fetchResponse))
      await pending
    })
    expect(result.current.isFetching).toBe(false)
    expect(result.current.activeFetch?.document.title).toBe("Live document title")
    expect(result.current.fetchError).toBeNull()
  })

  it("publishes fetch failure through Redux and settles loading", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)
    failRoute(server, "/fetch", "fetch exploded")

    let response!: unknown
    await act(async () => {
      response = await result.current.runFetch({
        url: "https://example.com/doc",
        format: "markdown",
        timeoutMs: 4000,
      })
    })
    expect(response).toBeNull()
    expect(result.current.isFetching).toBe(false)
    expect(result.current.activeFetch).toBeNull()
    expect(result.current.fetchError).toContain("fetch exploded")
  })

  it("clearActiveResults clears both Redux results and errors", async () => {
    const server = createServer()
    const { result } = await mountLoaded(server)

    await act(async () => {
      await result.current.runSearch({ query: "q", maxResults: 6, timeoutMs: 5000 })
      await result.current.runFetch({
        url: "https://example.com/doc",
        format: "markdown",
        timeoutMs: 4000,
      })
    })
    expect(result.current.activeSearch).not.toBeNull()
    expect(result.current.activeFetch).not.toBeNull()

    act(() => {
      result.current.clearActiveResults()
    })
    expect(result.current.activeSearch).toBeNull()
    expect(result.current.activeFetch).toBeNull()
    expect(result.current.searchError).toBeNull()
    expect(result.current.fetchError).toBeNull()
    expect(result.current.isSearching).toBe(false)
    expect(result.current.isFetching).toBe(false)
  })
})
