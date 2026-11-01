import {
  activityTraceFixtureDetail,
  activityTraceFixtures,
  errorTraceDetailFixtureForStub,
  stubbedProviderRows,
  successTraceDetailFixtureForStub,
} from "./backendStub"

/**
 * Project-scoped read data for the project stub (TASK-000047 U2): trace lists
 * and details, usage and dashboard, and the project provider view. Pure data,
 * no routes: projectStub.ts checks membership and permission, then calls
 * these builders. Everything is fake and deterministic.
 *
 * Isolation: each project owns its own trace set and usage ledger. Alpha owns
 * the Activity fixture traces Activity has always rendered; Beta owns one
 * trace and one usage row that must never appear under Alpha. A trace id of
 * another project answers 404, exactly like an unknown id.
 */

export const ALPHA_PROJECT_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
export const BETA_PROJECT_ID = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"

/** Beta's own trace; a request for it under Alpha must 404. */
export const BETA_TRACE_ID = "b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0b0"

/** Seeded Alpha traces of the detail-copy scenarios (latency marks the row). */
export const METADATA_ONLY_TRACE_ID = "a0000000000000000000000000000717"
export const RESULTS_NOT_STORED_TRACE_ID = "a0000000000000000000000000000818"
export const GONE_TRACE_ID = "a0000000000000000000000000000919"
export const METADATA_ONLY_LATENCY_MS = 717
export const RESULTS_NOT_STORED_LATENCY_MS = 818
export const GONE_LATENCY_MS = 919

/** Query recorded on the results-not-stored trace. */
export const RESULTS_NOT_STORED_QUERY = "results not stored probe"

const DEFAULT_LIMIT = 50
const MAX_LIMIT = 100
const GENERATED_AT = "2026-10-01T12:00:00.000Z"

type Json = Record<string, unknown>

interface ProjectTraceState {
  /** Seeded traces newer than the base list, newest first. */
  newer: Json[]
  /** Seeded traces older than the base list, newest first. */
  older: Json[]
  /** Seeded details by trace id; null means listed but no longer readable. */
  details: Map<string, Json | null>
}

const traceState = new Map<string, ProjectTraceState>()

function stateOf(projectId: string): ProjectTraceState {
  let state = traceState.get(projectId)
  if (state === undefined) {
    state = { newer: [], older: [], details: new Map() }
    traceState.set(projectId, state)
  }
  return state
}

/** Clear every seeded trace (called by resetProjectStub). */
export function resetProjectActivityStub(): void {
  traceState.clear()
}

/** Shift every recorded instant of a trace so it starts at `startedAt`. */
function shiftTrace(trace: Json, startedAt: string): Json {
  const origin = Date.parse(String(trace.started_at))
  const delta = Date.parse(startedAt) - origin
  const shift = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(shift)
    if (value === null || typeof value !== "object") return value
    const out: Json = {}
    for (const [key, inner] of Object.entries(value as Json)) {
      if (
        (key === "started_at" || key === "ended_at" || key === "timestamp") &&
        typeof inner === "string" &&
        !Number.isNaN(Date.parse(inner))
      ) {
        out[key] = new Date(Date.parse(inner) + delta).toISOString()
      } else {
        out[key] = shift(inner)
      }
    }
    return out
  }
  return shift(trace) as Json
}

const SUMMARY_KEYS = [
  "trace_id",
  "user_id",
  "operation",
  "started_at",
  "duration_ms",
  "provider",
  "outcome",
  "result_count",
  "error",
] as const

function summaryOf(trace: Json): Json {
  const summary: Json = {}
  for (const key of SUMMARY_KEYS) summary[key] = key in trace ? trace[key] : null
  return summary
}

function betaTraceDetail(): Json {
  return {
    ...shiftTrace(successTraceDetailFixtureForStub(), "2026-09-28T08:00:00.000Z"),
    trace_id: BETA_TRACE_ID,
    user_id: null,
    provider: "exa",
    duration_ms: 333,
    input: "beta-only isolation query",
    output: {
      kind: "search_results",
      query: "beta-only isolation query",
      results: [
        {
          title: "Beta-only recorded result",
          url: "https://beta.example.com/recorded",
          snippet: "Recorded under Beta only.",
          source: "exa",
          score: 0.5,
        },
      ],
    },
  }
}

function baseTraces(projectId: string): Json[] {
  if (projectId === ALPHA_PROJECT_ID) return activityTraceFixtures().map((t) => ({ user_id: null, ...t }))
  if (projectId === BETA_PROJECT_ID) return [summaryOf(betaTraceDetail())]
  return []
}

function baseDetail(projectId: string, traceId: string): Json | null {
  if (projectId === ALPHA_PROJECT_ID) {
    const detail = activityTraceFixtureDetail(traceId)
    return detail === null ? null : { user_id: null, ...detail }
  }
  if (projectId === BETA_PROJECT_ID && traceId === BETA_TRACE_ID) return betaTraceDetail()
  return null
}

/** Every trace of one project in list order (newest first), unfiltered. */
function projectTraces(projectId: string): Json[] {
  const state = stateOf(projectId)
  return [...state.newer, ...baseTraces(projectId), ...state.older]
}

/**
 * Seed the three detail-copy traces in a project, newest first:
 * - metadata only: input and output null (trace policy "metadata only");
 * - results not stored: a success with its input but a null output;
 * - gone: listed, but its detail answers 404 (pruned after listing).
 */
export function seedDetailCopyTraces(projectId: string): void {
  const state = stateOf(projectId)
  const base = successTraceDetailFixtureForStub()
  const metadataOnly: Json = {
    ...shiftTrace(base, "2026-10-01T10:03:00.000Z"),
    trace_id: METADATA_ONLY_TRACE_ID,
    user_id: null,
    provider: "brave",
    duration_ms: METADATA_ONLY_LATENCY_MS,
    result_count: 2,
    input: null,
    output: null,
  }
  const resultsNotStored: Json = {
    ...shiftTrace(base, "2026-10-01T10:02:00.000Z"),
    trace_id: RESULTS_NOT_STORED_TRACE_ID,
    user_id: null,
    duration_ms: RESULTS_NOT_STORED_LATENCY_MS,
    result_count: 2,
    input: RESULTS_NOT_STORED_QUERY,
    output: null,
  }
  const gone: Json = {
    ...summaryOf(shiftTrace(base, "2026-10-01T10:01:00.000Z")),
    trace_id: GONE_TRACE_ID,
    duration_ms: GONE_LATENCY_MS,
  }
  state.newer.unshift(summaryOf(metadataOnly), summaryOf(resultsNotStored), gone)
  state.details.set(METADATA_ONLY_TRACE_ID, metadataOnly)
  state.details.set(RESULTS_NOT_STORED_TRACE_ID, resultsNotStored)
  state.details.set(GONE_TRACE_ID, null)
}

/** Id of the n-th (0-based) seeded older error trace. */
export function olderErrorTraceId(index: number): string {
  return `eeeeeeee${String(index).padStart(24, "0")}`
}

/**
 * Seed `count` failed fetch traces older than every base trace, newest
 * first, so one project holds more than one page under the Error filter.
 */
export function seedOlderErrorTraces(projectId: string, count: number): void {
  const state = stateOf(projectId)
  const start = Date.parse("2026-09-01T00:00:00.000Z")
  for (let index = 0; index < count; index += 1) {
    const startedAt = new Date(start - index * 60_000).toISOString()
    const detail: Json = {
      ...shiftTrace(errorTraceDetailFixtureForStub(), startedAt),
      trace_id: olderErrorTraceId(index),
      user_id: null,
      duration_ms: 100 + index,
      error: { type: "http_error", message: "HTTP 503" },
    }
    state.older.push(summaryOf(detail))
    state.details.set(olderErrorTraceId(index), detail)
  }
}

export type TraceListAnswer = { status: 200; body: Json } | { status: 400 | 422; body: Json }

interface CursorPayload {
  p: string
  o: number
  op: string | null
  oc: string | null
}

function encodeCursor(payload: CursorPayload): string {
  return Buffer.from(JSON.stringify(payload), "utf8").toString("base64url")
}

function decodeCursor(raw: string): CursorPayload | null {
  try {
    const parsed = JSON.parse(Buffer.from(raw, "base64url").toString("utf8")) as unknown
    if (parsed === null || typeof parsed !== "object") return null
    const cursor = parsed as Partial<CursorPayload>
    if (typeof cursor.p !== "string" || typeof cursor.o !== "number") return null
    return { p: cursor.p, o: cursor.o, op: cursor.op ?? null, oc: cursor.oc ?? null }
  } catch {
    return null
  }
}

/**
 * Answer GET /api/v1/projects/{id}/traces like the backend: newest first,
 * `limit` 1..100 (default 50), `operation` search|fetch, `outcome`
 * success|partial|error, and an opaque cursor bound to the project and the
 * filters; `next_cursor` is null on the last page.
 */
export function projectTraceList(projectId: string, params: URLSearchParams): TraceListAnswer {
  const rawLimit = params.get("limit")
  const limit = rawLimit === null ? DEFAULT_LIMIT : Number(rawLimit)
  if (!Number.isInteger(limit) || limit < 1 || limit > MAX_LIMIT) {
    return { status: 422, body: { detail: "limit must be between 1 and 100" } }
  }
  const operation = params.get("operation")
  if (operation !== null && operation !== "search" && operation !== "fetch") {
    return { status: 422, body: { detail: "operation must be search or fetch" } }
  }
  const outcome = params.get("outcome")
  if (outcome !== null && outcome !== "success" && outcome !== "partial" && outcome !== "error") {
    return { status: 422, body: { detail: "outcome must be success, partial or error" } }
  }
  let offset = 0
  const rawCursor = params.get("cursor")
  if (rawCursor !== null) {
    const cursor = decodeCursor(rawCursor)
    if (cursor === null || cursor.p !== projectId || cursor.op !== operation || cursor.oc !== outcome) {
      return { status: 400, body: { detail: { code: "INVALID_CURSOR" } } }
    }
    offset = cursor.o
  }
  const matching = projectTraces(projectId).filter(
    (trace) =>
      (operation === null || trace.operation === operation) &&
      (outcome === null || trace.outcome === outcome)
  )
  const items = matching.slice(offset, offset + limit)
  const nextOffset = offset + items.length
  return {
    status: 200,
    body: {
      items,
      generated_at: GENERATED_AT,
      next_cursor:
        nextOffset < matching.length
          ? encodeCursor({ p: projectId, o: nextOffset, op: operation, oc: outcome })
          : null,
    },
  }
}

/** Detail of one trace of one project, or null (unknown, foreign or gone). */
export function projectTraceDetail(projectId: string, traceId: string): Json | null {
  const state = stateOf(projectId)
  if (state.details.has(traceId)) return state.details.get(traceId) ?? null
  return baseDetail(projectId, traceId)
}

// --- Usage and dashboard -----------------------------------------------------

/** Beta's usage marker: these units and counts must never render under Alpha. */
export const BETA_USAGE_UNITS = "777"
export const BETA_USAGE_EVENTS = 77

const USAGE_BY_PROJECT: Record<string, { totals: Json[]; recent: Json[] }> = {
  [ALPHA_PROJECT_ID]: {
    totals: [
      {
        provider: "brave",
        operation: "search",
        total_units: "14",
        event_count: 14,
        unit_kind: "REQUEST",
        display_unit: "requests",
      },
      { provider: "keenable", operation: "fetch", total_units: "0.5", event_count: 5 },
    ],
    recent: [
      {
        provider: "brave",
        operation: "search",
        units: "1",
        observed_at: "2026-10-01T10:00:00Z",
        latency_ms: 230,
        status: "success",
        unit_kind: "REQUEST",
        display_unit: "requests",
      },
      {
        provider: "keenable",
        operation: "fetch",
        units: 0.1,
        observed_at: "2026-10-01T09:55:00Z",
        latency_ms: null,
        status: "failure",
      },
    ],
  },
  [BETA_PROJECT_ID]: {
    totals: [
      {
        provider: "exa",
        operation: "search",
        total_units: BETA_USAGE_UNITS,
        event_count: BETA_USAGE_EVENTS,
      },
    ],
    recent: [
      {
        provider: "exa",
        operation: "search",
        units: BETA_USAGE_UNITS,
        observed_at: "2026-10-01T08:00:00Z",
        latency_ms: 345,
        status: "success",
      },
    ],
  },
}

/** GET /api/v1/projects/{id}/usage and /dashboard (`ProjectUsageResponse`). */
export function projectUsage(projectId: string, params: URLSearchParams): Json {
  const usage = USAGE_BY_PROJECT[projectId] ?? { totals: [], recent: [] }
  const rawLimit = Number(params.get("limit") ?? "50")
  const limit = Number.isInteger(rawLimit) && rawLimit > 0 ? rawLimit : 50
  return {
    project_id: projectId,
    totals: usage.totals.map((row) => ({ ...row })),
    recent_usage: usage.recent.slice(0, limit).map((row) => ({ ...row })),
    generated_at: GENERATED_AT,
  }
}

// --- Project provider view ----------------------------------------------------

const SEARCH_BIT = 2
const FETCH_BIT = 4

function operationsOf(mask: number): string[] {
  const operations: string[] = []
  if ((mask & SEARCH_BIT) !== 0) operations.push("search")
  if ((mask & FETCH_BIT) !== 0) operations.push("fetch")
  return operations
}

/**
 * GET /api/v1/projects/{id}/providers (`ProjectProvidersRead`). Derived from
 * the live in-memory global registry: capability is the support mask, the
 * system kill switch is the global bit, a provider without a stored secret
 * (and not keyless) is unavailable, and effective_operations is capability
 * AND system enablement AND availability, bound through one fake binding.
 */
export function projectProviders(projectId: string): Json {
  const providers = stubbedProviderRows().map((row, index) => {
    const capability = operationsOf(row.support_mask)
    const killSwitch = (row.enable_mask & row.support_mask & 1) === 0
    const systemEnabled = killSwitch ? [] : operationsOf(row.enable_mask & row.support_mask)
    const available = row.secret_presence !== "missing"
    const credentialId = `c0000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`
    const effective = available ? systemEnabled : []
    return {
      provider_type: row.provider_id,
      capability,
      kill_switch: killSwitch,
      system_enabled_operations: systemEnabled,
      available,
      enabled: available && effective.length > 0,
      credentials: available
        ? [
            {
              id: credentialId,
              label: `${row.provider_id} shared credential`,
              owner_scope: "system",
              auth_mode: row.secret_presence === "keyless_public" ? "keyless" : "api_key",
              status: "active",
              health_status: "healthy",
              health_checked_at: "2026-10-01T09:00:00Z",
              granted_operations: capability,
              supported_operations: capability,
              pools: [],
            },
          ]
        : [],
      bindings: available
        ? [
            {
              id: `b1000000-0000-4000-8000-${String(index + 1).padStart(12, "0")}`,
              credential_id: credentialId,
              route_label: row.provider_id,
              priority: row.priority,
              enabled_operations: capability,
              effective_operations: effective,
            },
          ]
        : [],
      effective_operations: effective,
    }
  })
  return { project_id: projectId, providers, allocations: [] }
}
