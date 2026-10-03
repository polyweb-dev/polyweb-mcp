import type { Page, Route } from "@playwright/test"
import {
  dashboardFixture as canonicalDashboardFixture,
  fetchResponseFixture as canonicalFetchFixture,
  searchResponseFixture as canonicalSearchFixture,
} from "../../src/test/backendFixtures"

/**
 * Deterministic in-memory backend stub for state-neutral E2E.
 *
 * `installBackendStub(page)` intercepts the app's backend traffic (which
 * otherwise flows through the Vite proxy to the LIVE backend at
 * 127.0.0.1:8001) and serves fixed fixtures instead. Writes (routing PUT,
 * provider PATCH, secret PUT/DELETE) mutate only per-scenario in-memory
 * variables, so toggle/save/delete interactions behave realistically inside
 * the scenario while the real backend is never touched.
 *
 * Fixture values mirror the live FastAPI wire contract (snake_case,
 * Decimal-as-string, ISO-8601 datetimes) and the canonical unit-test
 * fixtures in `src/test/backendFixtures.ts`:
 * - 7 canonical providers (brave, keenable, tavily, exa, firecrawl, you,
 *   parallel) with stable priorities 1..7, fixed p95 latencies, and
 *   catalog-faithful secret presence (you/parallel start "missing" so the
 *   key-vault save flow starts from an empty vault).
 * - Routing starts chained/balanced/3 (master failover switch ON), so the
 *   K2 keyboard-toggle sequence is deterministic.
 */

const FIXED_AT = "2026-09-06T10:05:00Z"

type SecretPresence = "configured" | "missing" | "keyless_public"

interface StubProvider {
  provider_id: string
  enabled: boolean
  priority: number
  health: "healthy"
  circuit_breaker: { state: "closed"; updated_at: string }
  latency_p95_ms: number
  secret_presence: SecretPresence
  free_tier_estimates: Record<string, string>
  reset_schedule: null
}

interface StubRouting {
  fallback_policy: "chained" | "first_only"
  cost_optimization_preset: "balanced" | "free_first"
  max_attempts: number
}

/**
 * In-memory manual billing entries for manual-quota scenarios. Mutated (never
 * reassigned) so route closures registered by installBackendStub always see
 * the current per-scenario state; writes via PUT persist for the scenario.
 */
const stubbedManualQuotas: Record<string, Record<string, unknown>> = {}

export function setStubbedManualQuota(
  provider: string,
  entry: Record<string, unknown> | null
): void {
  if (entry === null) delete stubbedManualQuotas[provider]
  else stubbedManualQuotas[provider] = entry
}

// ---------------------------------------------------------------------------
// Parallel OAuth device-flow stub (adversarial test-only, Phase 1).
//
// Per-scenario in-memory flow state for POST/GET/DELETE
// /api/v1/providers/{id}/oauth[/device-code|/status]. Unpaired by default
// (GET status 404s, mirroring the frozen getOAuthStatus 404->unpaired
// mapping); steps mutate the flow so polling picks up transitions without
// sleeps. Cleared per scenario at the top of installBackendStub.
// ---------------------------------------------------------------------------

export type StubbedOAuthStatus = "pending" | "ready" | "expired" | "denied"

interface StubbedOAuthFlow {
  hasFlow: boolean
  status: StubbedOAuthStatus
  beginFails: boolean
}

const stubbedOAuthFlows: Record<string, StubbedOAuthFlow> = {}

function oauthFlowOf(provider: string): StubbedOAuthFlow {
  return stubbedOAuthFlows[provider] ?? { hasFlow: false, status: "pending", beginFails: false }
}

function clearStubbedOAuthFlows(): void {
  for (const key of Object.keys(stubbedOAuthFlows)) delete stubbedOAuthFlows[key]
}

export function setStubbedOAuthFlow(
  provider: string,
  status: "unpaired" | StubbedOAuthStatus
): void {
  if (status === "unpaired") {
    delete stubbedOAuthFlows[provider]
    return
  }
  const current = oauthFlowOf(provider)
  stubbedOAuthFlows[provider] = { ...current, hasFlow: true, status }
}

export function failStubbedOAuthBegin(provider: string): void {
  stubbedOAuthFlows[provider] = { ...oauthFlowOf(provider), beginFails: true }
}

/**
 * Mutable dashboard latest_quota override. overrideDashboardLatestQuota
 * installs a dashboard route that reads this per request (instead of
 * closing over fixed rows), so OAuth steps can flip pairing state and the
 * SUT's post-transition dashboard refresh deterministically sees it.
 */
let dashboardQuotaOverride: unknown[] | null = null

export function setDashboardQuotaOverride(latestQuota: unknown[]): void {
  dashboardQuotaOverride = [...latestQuota]
}

const SECRET_PRESENCE: Record<string, SecretPresence> = {
  brave: "configured",
  keenable: "keyless_public",
  tavily: "configured",
  exa: "configured",
  firecrawl: "configured",
  you: "missing",
  parallel: "missing",
  tinyfish: "configured",
}

const PROVIDER_ORDER = [
  "brave",
  "keenable",
  "tavily",
  "exa",
  "firecrawl",
  "you",
  "parallel",
  "tinyfish",
]

function initialProviders(): StubProvider[] {
  return PROVIDER_ORDER.map((id, index) => ({
    provider_id: id,
    enabled: true,
    priority: index + 1,
    health: "healthy",
    circuit_breaker: { state: "closed", updated_at: FIXED_AT },
    latency_p95_ms: 110 + index * 10,
    secret_presence: SECRET_PRESENCE[id] ?? "missing",
    free_tier_estimates: { search: "0", fetch: "0", cost_estimate: "0" },
    reset_schedule: null,
  }))
}

function dashboardFixture(): Record<string, unknown> {
  return {
    notice: "Usage, quota, and health shown here are local-observed only.",
    usage_totals: [{ provider: "brave", operation: "search", total_units: "14", event_count: 14 }],
    recent_usage: [
      {
        provider: "brave",
        operation: "search",
        units: "1",
        observed_at: "2026-09-06T10:00:00Z",
        latency_ms: 230,
        status: "success",
      },
      {
        provider: "keenable",
        operation: "fetch",
        units: "0.001",
        observed_at: "2026-09-06T09:55:00Z",
        latency_ms: null,
        status: "failure",
      },
    ],
    latest_quota: [],
    latest_health: [{ provider: "brave", status: "healthy", checked_at: FIXED_AT }],
    generated_at: FIXED_AT,
  }
}

function secretFixture(provider: string, presence: SecretPresence): Record<string, unknown> {
  return {
    provider,
    presence,
    fingerprint:
      presence === "configured" ? `${provider.slice(0, 3).toUpperCase()}_••••••••a1b2` : null,
    updated_at: FIXED_AT,
    source: presence === "configured" ? "keyring" : "none",
  }
}

function json(route: Route, body: unknown, status = 200): Promise<void> {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  })
}

function readJsonBody(route: Route): Record<string, unknown> {
  try {
    return JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>
  } catch {
    return {}
  }
}

/**
 * Register deterministic stub routes on `page`. Call from a `Before` hook
 * (before navigation) so every backend fetch in the scenario is served from
 * the fixed fixtures. State is per-call, hence per-scenario isolation.
 */
export async function installBackendStub(page: Page): Promise<void> {
  clearStubbedOAuthFlows()
  // Hygiene: manual overlays are module-level and must not leak across
  // scenarios (e.g. Brave overlay into later quota rows).
  for (const key of Object.keys(stubbedManualQuotas)) delete stubbedManualQuotas[key]
  dashboardQuotaOverride = null
  let providers = initialProviders()
  let routing: StubRouting = {
    fallback_policy: "chained",
    cost_optimization_preset: "balanced",
    max_attempts: 3,
  }

  // Secret vault writes must land before the generic provider route (the
  // `/secret` suffix also matches `providers/*`).
  await page.route("**/api/v1/providers/*/secret", (route) => {
    const method = route.request().method()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 2] ?? ""
    if (method === "PUT") {
      providers = providers.map((row) =>
        row.provider_id === backendId ? { ...row, secret_presence: "configured" } : row
      )
      return json(route, secretFixture(backendId, "configured"))
    }
    if (method === "DELETE") {
      providers = providers.map((row) =>
        row.provider_id === backendId ? { ...row, secret_presence: "missing" } : row
      )
      return json(route, secretFixture(backendId, "missing"))
    }
    return route.fallback()
  })

  // Manual billing entries: GET 404s while unconfigured, PUT stores the window,
  // DELETE clears it again. Writes persist per scenario via stubbedManualQuotas.
  await page.route("**/api/v1/providers/*/manual-quota", (route) => {
    const method = route.request().method()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 2] || ""
    if (method === "GET") {
      const entry = stubbedManualQuotas[backendId]
      if (!entry) return json(route, { detail: "no manual quota for " + backendId }, 404)
      return json(route, entry)
    }
    if (method === "PUT") {
      const body = readJsonBody(route)
      const stored: Record<string, unknown> = { provider: backendId }
      for (const key of Object.keys(body)) stored[key] = body[key]
      stubbedManualQuotas[backendId] = stored
      return json(route, stored)
    }
    if (method === "DELETE") {
      delete stubbedManualQuotas[backendId]
      return json(route, { provider: backendId, deleted: true })
    }
    return route.fallback()
  })

  // OAuth device flow (see the stub-state block above). A POST begins (or
  // restarts) the flow as pending with a 1s poll interval; GET serves the
  // mutable flow state (404 while unpaired); DELETE revokes to unpaired and
  // flips the next dashboard refresh back to the unbudgeted row.
  await page.route("**/api/v1/providers/*/oauth/device-code", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 3] || ""
    const flow = oauthFlowOf(backendId)
    if (flow.beginFails) {
      return json(route, { detail: backendId + " oauth unavailable" }, 503)
    }
    stubbedOAuthFlows[backendId] = { hasFlow: true, status: "pending", beginFails: false }
    return json(route, {
      provider: backendId,
      user_code: "ABCD-EFGH",
      verification_uri: "https://parallel.ai/activate",
      verification_uri_complete: "https://parallel.ai/activate?code=ABCD-EFGH",
      expires_in: 300,
      interval: 1,
    })
  })

  await page.route("**/api/v1/providers/*/oauth/status", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    const parts = new URL(route.request().url()).pathname.split("/")
    const backendId = parts[parts.length - 3] || ""
    const flow = stubbedOAuthFlows[backendId]
    if (!flow || !flow.hasFlow) {
      return json(route, { detail: "no oauth pairing for '" + backendId + "'" }, 404)
    }
    return json(route, {
      provider: backendId,
      status: flow.status,
      expires_in: flow.status === "pending" ? 299 : null,
    })
  })

  await page.route("**/api/v1/providers/*/oauth", (route) => {
    if (route.request().method() !== "DELETE") return route.fallback()
    const deleteParts = new URL(route.request().url()).pathname.split("/")
    const backendId = deleteParts[deleteParts.length - 2] ?? ""
    delete stubbedOAuthFlows[backendId]
    dashboardQuotaOverride = parallelUnseededQuota()
    return json(route, { provider: backendId, deleted: true })
  })
  await page.route("**/api/v1/providers/*/test", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 2] ?? "brave"
    return json(route, {
      provider: backendId,
      ok: true,
      status: "healthy",
      latency_ms: 142,
      checked_at: FIXED_AT,
      detail: null,
    })
  })

  await page.route("**/api/v1/providers/*/circuit-breaker/reset", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const segments = new URL(route.request().url()).pathname.split("/")
    const backendId = segments[segments.length - 3] ?? "brave"
    return json(route, { provider: backendId, state: "closed", updated_at: FIXED_AT })
  })

  // Provider PATCH (global enable / priority moves): in-memory update only.
  await page.route("**/api/v1/providers/*", (route) => {
    if (route.request().method() !== "PATCH") return route.fallback()
    const backendId = new URL(route.request().url()).pathname.split("/").pop() ?? ""
    const patch = readJsonBody(route)
    const current = providers.find((row) => row.provider_id === backendId)
    if (!current) return json(route, { detail: "Unknown provider" }, 404)
    const next = {
      ...current,
      enabled: typeof patch.enabled === "boolean" ? patch.enabled : current.enabled,
      priority: typeof patch.priority === "number" ? patch.priority : current.priority,
    }
    providers = providers.map((row) => (row.provider_id === backendId ? next : row))
    return json(route, next)
  })

  await page.route("**/api/v1/providers", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(route, providers)
  })

  // Routing config: PUT updates the in-memory variable; later GETs see it.
  await page.route("**/api/v1/routing/config", (route) => {
    const method = route.request().method()
    if (method === "GET") return json(route, routing)
    if (method === "PUT") {
      const patch = readJsonBody(route)
      routing = {
        fallback_policy: patch.fallback_policy === "first_only" ? "first_only" : "chained",
        cost_optimization_preset:
          patch.cost_optimization_preset === "free_first" ? "free_first" : "balanced",
        max_attempts: typeof patch.max_attempts === "number" ? patch.max_attempts : 3,
      }
      return json(route, routing)
    }
    return route.fallback()
  })

  // Pathname-exact dashboard matcher: the legacy "**/dashboard*" glob also
  // matched the Vite module URL /src/app/selectors/dashboardOverlay.ts (new
  // in Slice 6), fulfilling a JS import with JSON and blanking the app.
  await page.route((url) => url.pathname === "/dashboard", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(route, dashboardFixture())
  })

  // Deterministic search: echoes the pinned provider from routing.providers
  // and serves a fixed two-result payload (with scores so "% match" renders).
  await page.route("**/search", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = readJsonBody(route)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "brave"
    const query = typeof body.query === "string" ? (body.query as string) : "stubbed query"
    if (query === "doomed query") {
      return json(route, { detail: "stubbed provider unavailable" }, 503)
    }
    return json(
      route,
      canonicalSearchFixture({ query, provider: pinned })
    )
  })

  // Deterministic fetch: echoes the pinned provider and target URL with
  // non-empty markdown content.
  await page.route("**/fetch", (route) => {
    if (route.request().method() !== "POST") return route.fallback()
    const body = readJsonBody(route)
    const routing = (body.routing ?? {}) as { providers?: unknown }
    const providers = Array.isArray(routing.providers) ? routing.providers : []
    const pinned = typeof providers[0] === "string" ? (providers[0] as string) : "keenable"
    const url = typeof body.url === "string" ? (body.url as string) : "https://example.com"
    const base = canonicalFetchFixture() as {
      provider: string
      document: Record<string, unknown>
      usage: Record<string, unknown>
    }
    return json(route, {
      ...base,
      provider: pinned,
      document: { ...base.document, url },
      usage: { ...(base.usage as Record<string, unknown>), provider: pinned },
    })
  })
}

/**
 * Override the stubbed dashboard latest_quota for quota-display scenarios.
 *
 * The base stub serves an empty latest_quota; quota scenarios replace it
 * with per-provider deterministic rows from src/test/backendFixtures. The
 * previous dashboard handler is removed first so the override wins.
 */
export async function overrideDashboardLatestQuota(
  page: Page,
  latestQuota: unknown[]
): Promise<void> {
  // Mutable per-request read (not a fixed close-over): later
  // setDashboardQuotaOverride calls — e.g. the OAuth ready/revoke
  // transitions — are visible to the SUT's post-transition refresh.
  dashboardQuotaOverride = [...latestQuota]
  // Pathname-exact dashboard matcher: the legacy "**/dashboard*" glob also
  // matched the Vite module URL /src/app/selectors/dashboardOverlay.ts,
  // fulfilling a JS import with JSON and blanking the app.
  await page.unroute((url) => url.pathname === "/dashboard")
  await page.route((url) => url.pathname === "/dashboard", (route) => {
    if (route.request().method() !== "GET") return route.fallback()
    return json(
      route,
      canonicalDashboardFixture({ latest_quota: (dashboardQuotaOverride ?? []) as never })
    )
  })
}

/** Brave OBSERVED 950/1000 requests fixture for the quota-display suite. */
export function braveObservedQuota(): unknown[] {
  return [
    {
      provider: "brave",
      source: "observed",
      observed_at: FIXED_AT,
      remaining: "950",
      limit: "1000",
      reset_at: "2026-10-01T00:00:00Z",
      unit_kind: "REQUEST",
      display_unit: "requests",
    },
  ]
}

/** Parallel seeded USD 5.00 budget fixture (3.75 remaining). */
export function parallelSeededQuota(): unknown[] {
  return [
    {
      provider: "parallel",
      source: "estimated",
      observed_at: FIXED_AT,
      remaining: "3.75",
      limit: "5.00",
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

/** Parallel paired fixture: AUTHORITATIVE remaining-only USD (frozen contract). */
export function parallelPairedQuota(): unknown[] {
  return [
    {
      provider: "parallel",
      source: "authoritative",
      observed_at: FIXED_AT,
      remaining: "3.75",
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

/** Parallel unseeded spend-ledger fixture (no balance to show). */
export function parallelUnseededQuota(): unknown[] {
  return [
    {
      provider: "parallel",
      source: "estimated",
      observed_at: FIXED_AT,
      remaining: null,
      limit: null,
      reset_at: null,
      unit_kind: "USD",
      display_unit: "USD",
    },
  ]
}

/** Keenable keyless rolling-hour request headroom fixture. */
export function keenableKeylessQuota(): unknown[] {
  return [
    {
      provider: "keenable",
      source: "observed",
      observed_at: FIXED_AT,
      remaining: "999",
      remaining_percent: "99.9",
      limit: "1000",
      reset_at: null,
      unit_kind: "REQUEST",
      display_unit: "requests",
      window: "hourly",
    },
  ]
}
