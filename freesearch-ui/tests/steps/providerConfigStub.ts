import type { Page, Route } from "@playwright/test"
import { ALPHA_PROJECT_ID, BETA_PROJECT_ID } from "./projectActivityStub"

/**
 * In-memory provider configuration backend for the U3 scenarios
 * (TASK-000048): credential instances, project bindings and provider views,
 * project settings with copy, system credentials with grants, pools with
 * links and per-project allocations, plus the credential-scoped OAuth device
 * flow. Wire shapes follow `.tmp/u3/api-schemas.txt`; 409 bodies are
 * `{"detail": {"code", "message"}}`, 400/403/404 answer with no body.
 *
 * Secrets: create and rotate bodies are recorded in `configTraffic` so a
 * scenario can prove the POST carried the fake secret; the stub never stores
 * a secret in its credential state and never echoes one in a response.
 *
 * The routes are installed by `installProjectStub` (projectStub.ts) for every
 * project scenario. The project provider view switches from the U2 fixture to
 * this stateful view only after `activateProviderConfigStub()`, so U2
 * scenarios keep their registry-driven view.
 */

export type Operation = "search" | "fetch"

/** Access to the projects stub without a circular import. */
export interface ProjectAccessBridge {
  /** Project id and the caller's project permissions; null for a non-member or unknown project. */
  access(projectId: string): { id: string; name: string; permissions: string[] } | null
  /** System permissions of the signed-in account. */
  systemPermissions(): string[]
}

interface StubCredential {
  id: string
  provider_type: string
  owner_scope: "system" | "project"
  owner_project_id: string | null
  label: string
  auth_mode: "api_key" | "oauth" | "keyless"
  generation: number
  status: string
  health_status: string | null
}

interface StubGrant {
  credential_id: string
  project_id: string
  permitted_operations: Operation[]
  version: number
}

interface StubBinding {
  id: string
  project_id: string
  credential_id: string
  route_label: string
  enabled_operations: Operation[]
  priority: number
  version: number
}

interface StubProviderType {
  provider_type: string
  capability: Operation[]
  kill_switch: boolean
  system_enabled_operations: Operation[]
}

interface StubOAuth {
  status: "pending" | "connected" | "refresh_failed" | "disconnected"
  approved: boolean
  denied: boolean
  polls: number
  last_error_code: string | null
  connected_at: string | null
}

interface StubPool {
  id: string
  provider_type: string
  upstream_scope: "account" | "credential" | "ip" | "installation"
  pool_key: string
  label: string
  constraints: Array<{ algorithm: string; window_seconds: number; limit: number }>
  max_concurrency: number | null
  max_queued_requests: number | null
  status: "active" | "disabled"
  version: number
}

interface StubLink {
  credential_id: string
  pool_id: string
  operation_scope: Operation
  provider_type: string
  version: number
}

interface StubAllocation {
  project_id: string
  pool_id: string
  operation_scope: Operation
  base_rate: number
  rate_window_seconds: number
  borrow_enabled: boolean
  max_rate: number | null
  weight: number
  best_effort: boolean
  max_concurrency: number | null
  max_queued_requests: number | null
  max_queued_bytes: number | null
  max_queue_wait_ms: number | null
  version: number
}

type Sections = { routing: Record<string, unknown>; execution: Record<string, unknown>; trace: Record<string, unknown> }

interface StubProjectSettings {
  revision: number
  overrides: Sections
}

interface FieldSpec {
  section: "routing" | "execution" | "trace"
  attribute: string
  /** System limit rule: an order (looser later) or a safety-limit attribute. */
  order?: string[]
  limit?: string
}

/** Project-visible settings catalog (backend models/settings.py, safety rows excluded). */
const FIELD_CATALOG: Record<string, FieldSpec> = {
  "routing.fallback_policy": { section: "routing", attribute: "fallback_policy" },
  "routing.cost_optimization_preset": { section: "routing", attribute: "cost_optimization_preset" },
  "routing.max_attempts": { section: "routing", attribute: "max_attempts" },
  "routing.preferred_providers": { section: "routing", attribute: "preferred_providers" },
  "execution.cache_enabled": { section: "execution", attribute: "cache_enabled" },
  "execution.default_timeout_seconds": {
    section: "execution",
    attribute: "default_timeout_seconds",
    limit: "max_timeout_seconds",
  },
  "execution.max_fanout_concurrency": {
    section: "execution",
    attribute: "max_fanout_concurrency",
    limit: "max_fanout_concurrency",
  },
  "execution.cache_ttl_seconds": { section: "execution", attribute: "cache_ttl_seconds" },
  "trace.detail": { section: "trace", attribute: "detail", order: ["metadata", "full"] },
  "trace.retention_days": {
    section: "trace",
    attribute: "retention_days",
    limit: "max_trace_retention_days",
  },
}

/** System-only safety rows, resolved with override_allowed false. */
const SAFETY_FIELDS: Record<string, string> = {
  "system.max_timeout_seconds": "max_timeout_seconds",
  "system.max_fanout_concurrency": "max_fanout_concurrency",
  "system.max_trace_retention_days": "max_trace_retention_days",
}

/** Fixed ids of the seeded fixtures, exported for step assertions. */
export const SEED = {
  sharedTavily: "5c000000-0000-4000-8000-000000000001",
  sharedBrave: "5c000000-0000-4000-8000-000000000002",
  alphaTavilyKey: "9c000000-0000-4000-8000-000000000001",
  betaPrivateKey: "9c000000-0000-4000-8000-000000000002",
  alphaBraveBinding: "b3000000-0000-4000-8000-000000000001",
  betaBraveBinding: "b3000000-0000-4000-8000-000000000002",
  betaPrivateBinding: "b3000000-0000-4000-8000-000000000003",
  tavilyPool: "90010000-0000-4000-8000-000000000001",
  bravePool: "90010000-0000-4000-8000-000000000002",
} as const

/** Fake OAuth device values; the user code is the only code the UI may show. */
export const OAUTH_USER_CODE = "WXYZ-1234"
export const OAUTH_VERIFICATION_URI = "https://parallel.example/device"

interface ConfigState {
  active: boolean
  seq: number
  providerTypes: StubProviderType[]
  credentials: StubCredential[]
  grants: StubGrant[]
  bindings: StubBinding[]
  oauth: Record<string, StubOAuth>
  systemSettings: {
    revision: number
    routing: Record<string, unknown>
    execution: Record<string, unknown>
    trace: Record<string, unknown>
    safety_limits: Record<string, unknown>
  }
  projectSettings: Record<string, StubProjectSettings>
  pools: StubPool[]
  links: StubLink[]
  allocations: StubAllocation[]
}

const state: ConfigState = {
  active: false,
  seq: 100,
  providerTypes: [],
  credentials: [],
  grants: [],
  bindings: [],
  oauth: {},
  systemSettings: { revision: 0, routing: {}, execution: {}, trace: {}, safety_limits: {} },
  projectSettings: {},
  pools: [],
  links: [],
  allocations: [],
}

/** One recorded request to a provider configuration route. */
export interface ConfigRequest {
  method: string
  path: string
  search: string
  body: Record<string, unknown> | null
}

/** Every provider configuration request of the scenario, oldest first. */
export const configTraffic: ConfigRequest[] = []

/** Requests matching a method and a path pattern. */
export function configRequests(method: string, path: RegExp): ConfigRequest[] {
  return configTraffic.filter((r) => r.method === method && path.test(r.path))
}

/** Serve the stateful provider view instead of the U2 registry fixture. */
export function activateProviderConfigStub(): void {
  state.active = true
}

function cred(
  id: string,
  provider: string,
  label: string,
  owner: "system" | "project",
  ownerProject: string | null,
  generation = 1,
  authMode: "api_key" | "oauth" | "keyless" = "api_key"
): StubCredential {
  return {
    id,
    provider_type: provider,
    owner_scope: owner,
    owner_project_id: ownerProject,
    label,
    auth_mode: authMode,
    generation,
    status: "active",
    health_status: "healthy",
  }
}

/** Reset every U3 fixture to the seeded scenario state. */
export function resetProviderConfigStub(): void {
  state.active = false
  state.seq = 100
  configTraffic.length = 0
  state.providerTypes = [
    { provider_type: "keenable", capability: ["search", "fetch"], kill_switch: false, system_enabled_operations: ["search", "fetch"] },
    { provider_type: "brave", capability: ["search"], kill_switch: false, system_enabled_operations: ["search"] },
    {
      provider_type: "tavily",
      capability: ["search", "fetch"],
      kill_switch: false,
      system_enabled_operations: ["search", "fetch"],
    },
    {
      provider_type: "parallel",
      capability: ["search", "fetch"],
      kill_switch: false,
      system_enabled_operations: ["search", "fetch"],
    },
    { provider_type: "exa", capability: ["search", "fetch"], kill_switch: true, system_enabled_operations: [] },
  ]
  state.credentials = [
    cred(SEED.sharedTavily, "tavily", "Shared Tavily", "system", null, 1),
    cred(SEED.sharedBrave, "brave", "Shared Brave", "system", null, 2),
    cred(SEED.alphaTavilyKey, "tavily", "Alpha Tavily key", "project", ALPHA_PROJECT_ID, 1),
    cred(SEED.betaPrivateKey, "brave", "Beta private Brave", "project", BETA_PROJECT_ID, 1),
    cred("9c000000-0000-4000-8000-000000000003", "keenable", "Keenable keyless", "project", ALPHA_PROJECT_ID, 1, "keyless"),
  ]
  state.grants = [
    { credential_id: SEED.sharedTavily, project_id: ALPHA_PROJECT_ID, permitted_operations: ["search", "fetch"], version: 1 },
    { credential_id: SEED.sharedBrave, project_id: ALPHA_PROJECT_ID, permitted_operations: ["search"], version: 1 },
    { credential_id: SEED.sharedBrave, project_id: BETA_PROJECT_ID, permitted_operations: ["search"], version: 1 },
  ]
  state.bindings = [
    {
      id: "b3000000-0000-4000-8000-000000000004",
      project_id: ALPHA_PROJECT_ID,
      credential_id: "9c000000-0000-4000-8000-000000000003",
      route_label: "keenable-keyless",
      enabled_operations: ["search", "fetch"],
      priority: 200,
      version: 1,
    },
    {
      id: SEED.alphaBraveBinding,
      project_id: ALPHA_PROJECT_ID,
      credential_id: SEED.sharedBrave,
      route_label: "brave-primary",
      enabled_operations: ["search"],
      priority: 100,
      version: 1,
    },
    {
      id: SEED.betaBraveBinding,
      project_id: BETA_PROJECT_ID,
      credential_id: SEED.sharedBrave,
      route_label: "beta-brave",
      enabled_operations: ["search"],
      priority: 50,
      version: 3,
    },
    {
      id: SEED.betaPrivateBinding,
      project_id: BETA_PROJECT_ID,
      credential_id: SEED.betaPrivateKey,
      route_label: "beta-private",
      enabled_operations: ["search"],
      priority: 60,
      version: 1,
    },
  ]
  state.oauth = {}
  state.systemSettings = {
    revision: 4,
    routing: { fallback_policy: "chained", cost_optimization_preset: "balanced", max_attempts: 3, preferred_providers: [] },
    execution: { cache_enabled: true, default_timeout_seconds: 30, max_fanout_concurrency: 5, cache_ttl_seconds: 300 },
    trace: { detail: "full" },
    safety_limits: { max_timeout_seconds: 300, max_fanout_concurrency: 20, max_trace_retention_days: 90 },
  }
  state.projectSettings = {
    [ALPHA_PROJECT_ID]: {
      revision: 2,
      overrides: { routing: { max_attempts: 5 }, execution: {}, trace: { retention_days: 120 } },
    },
    [BETA_PROJECT_ID]: {
      revision: 3,
      overrides: { routing: { fallback_policy: "first_only" }, execution: { cache_ttl_seconds: 600 }, trace: {} },
    },
  }
  state.pools = [
    {
      id: SEED.tavilyPool,
      provider_type: "tavily",
      upstream_scope: "account",
      pool_key: "tavily-main",
      label: "Tavily shared pool",
      constraints: [{ algorithm: "token_bucket", window_seconds: 1, limit: 10 }],
      max_concurrency: 8,
      max_queued_requests: 50,
      status: "active",
      version: 1,
    },
    {
      id: SEED.bravePool,
      provider_type: "brave",
      upstream_scope: "credential",
      pool_key: "brave-main",
      label: "Brave shared pool",
      constraints: [{ algorithm: "fixed_window", window_seconds: 60, limit: 120 }],
      max_concurrency: null,
      max_queued_requests: null,
      status: "active",
      version: 1,
    },
  ]
  state.links = [
    { credential_id: SEED.sharedTavily, pool_id: SEED.tavilyPool, operation_scope: "search", provider_type: "tavily", version: 1 },
  ]
  state.allocations = [
    allocation(ALPHA_PROJECT_ID, SEED.tavilyPool, "search", {
      base_rate: 5,
      rate_window_seconds: 1,
      borrow_enabled: true,
      max_rate: 10,
      weight: 2,
    }),
    allocation(ALPHA_PROJECT_ID, SEED.bravePool, "search", { base_rate: 60, rate_window_seconds: 60 }),
    allocation(BETA_PROJECT_ID, SEED.tavilyPool, "search", {
      base_rate: 0,
      rate_window_seconds: 1,
      best_effort: true,
    }),
  ]
}

function allocation(
  projectId: string,
  poolId: string,
  op: Operation,
  values: Partial<StubAllocation>
): StubAllocation {
  return {
    project_id: projectId,
    pool_id: poolId,
    operation_scope: op,
    base_rate: 0,
    rate_window_seconds: 1,
    borrow_enabled: false,
    max_rate: null,
    weight: 1,
    best_effort: false,
    max_concurrency: null,
    max_queued_requests: null,
    max_queued_bytes: null,
    max_queue_wait_ms: null,
    version: 1,
    ...values,
  }
}

resetProviderConfigStub()

// ---------------------------------------------------------------------------
// Scenario controls
// ---------------------------------------------------------------------------

function credentialByLabel(label: string): StubCredential {
  const found = state.credentials.find((c) => c.label === label)
  if (found === undefined) throw new Error(`unknown stub credential ${label}`)
  return found
}

/** Id of one credential by label. */
export function credentialIdOf(label: string): string {
  return credentialByLabel(label).id
}

/** Simulate a rotation by someone else: the next rotate with the old generation conflicts. */
export function rotateCredentialElsewhere(label: string): void {
  credentialByLabel(label).generation += 1
}

/** Seed a private Parallel OAuth credential, not yet connected. */
export function seedPrivateOAuthCredential(projectId: string, label: string): void {
  state.credentials.push(cred(nextId("9c000000"), "parallel", label, "project", projectId, 1, "oauth"))
}

/** Seed a system Parallel OAuth credential, not yet connected. */
export function seedSystemOAuthCredential(label: string): void {
  state.credentials.push(cred(nextId("5c000000"), "parallel", label, "system", null, 1, "oauth"))
}

/** Let the next poll of this credential's pending device flow report connected. */
export function approveOAuthDevice(label: string): void {
  const id = credentialByLabel(label).id
  const flow = state.oauth[id]
  if (flow !== undefined) flow.approved = true
}

/** Let the next poll of this credential's pending device flow report a denial. */
export function denyOAuthDevice(label: string): void {
  const id = credentialByLabel(label).id
  const flow = state.oauth[id]
  if (flow !== undefined) flow.denied = true
}

/** OAuth state of one credential by label. */
export function oauthStatusOf(label: string): StubOAuth["status"] {
  return state.oauth[credentialByLabel(label).id]?.status ?? "disconnected"
}

/** Number of poll requests one credential's device flow received. */
export function oauthPollCount(label: string): number {
  return state.oauth[credentialByLabel(label).id]?.polls ?? 0
}

/** Bump one project's settings revision as if another tab saved. */
export function changeProjectSettingsElsewhere(projectId: string): void {
  const doc = state.projectSettings[projectId]
  if (doc !== undefined) doc.revision += 1
}

/** Current settings revision of one project. */
export function projectSettingsRevision(projectId: string): number {
  return state.projectSettings[projectId]?.revision ?? 0
}

/** Override map of one project, keyed by field id. */
export function projectOverrides(projectId: string): Record<string, unknown> {
  const doc = state.projectSettings[projectId]
  const out: Record<string, unknown> = {}
  if (doc === undefined) return out
  for (const section of ["routing", "execution", "trace"] as const) {
    for (const [attr, value] of Object.entries(doc.overrides[section])) out[`${section}.${attr}`] = value
  }
  return out
}

/** Change the system detail ceiling for the scenario. */
export function setSystemTraceDefault(attribute: "detail", value: string): void {
  state.systemSettings.trace[attribute] = value
}

/** Bindings of one project, current state. */
export function projectBindings(projectId: string): StubBinding[] {
  return state.bindings.filter((b) => b.project_id === projectId)
}

/** Grants of one system credential by label. */
export function grantsOf(label: string): StubGrant[] {
  const id = credentialByLabel(label).id
  return state.grants.filter((g) => g.credential_id === id)
}

/** All pools, current state. */
export function stubPools(): StubPool[] {
  return state.pools
}

/** All pool links, current state. */
export function stubLinks(): StubLink[] {
  return state.links
}

/** Whether a credential with this label exists (deleted ones are gone). */
export function credentialExists(label: string): boolean {
  return state.credentials.some((c) => c.label === label)
}

// ---------------------------------------------------------------------------
// Wire projections
// ---------------------------------------------------------------------------

function nextId(prefix: string): string {
  state.seq += 1
  return `${prefix}-0000-4000-8000-${String(state.seq).padStart(12, "0")}`
}

function capabilityOf(provider: string): Operation[] {
  return state.providerTypes.find((t) => t.provider_type === provider)?.capability ?? ["search"]
}

function credentialRead(c: StubCredential): Record<string, unknown> {
  return {
    id: c.id,
    provider_type: c.provider_type,
    owner_scope: c.owner_scope,
    owner_project_id: c.owner_project_id,
    label: c.label,
    auth_mode: c.auth_mode,
    generation: c.generation,
    status: c.status,
  }
}

/** Credentials one project may see: its own private ones and granted system ones. */
function visibleCredentials(projectId: string): Array<{ c: StubCredential; ops: Operation[] }> {
  const out: Array<{ c: StubCredential; ops: Operation[] }> = []
  for (const c of state.credentials) {
    if (c.status !== "active") continue
    if (c.owner_scope === "project" && c.owner_project_id === projectId) {
      out.push({ c, ops: capabilityOf(c.provider_type) })
      continue
    }
    if (c.owner_scope === "system") {
      const grant = state.grants.find((g) => g.credential_id === c.id && g.project_id === projectId)
      if (grant !== undefined) out.push({ c, ops: [...grant.permitted_operations] })
    }
  }
  return out
}

function projectCredentialRead(
  c: StubCredential,
  ops: Operation[],
  permissions: string[]
): Record<string, unknown> {
  const isPrivate = c.owner_scope === "project"
  return {
    id: c.id,
    provider_type: c.provider_type,
    owner_scope: c.owner_scope,
    label: c.label,
    auth_mode: c.auth_mode,
    status: c.status,
    permitted_operations: ops,
    can_manage: isPrivate && permissions.includes("credentials.manage_private"),
    generation: isPrivate ? c.generation : null,
  }
}

function bindingRead(b: StubBinding): Record<string, unknown> {
  return {
    id: b.id,
    project_id: b.project_id,
    credential_id: b.credential_id,
    route_label: b.route_label,
    enabled_operations: [...b.enabled_operations],
    priority: b.priority,
    overrides: {},
    version: b.version,
  }
}

function effectiveOf(type: StubProviderType, granted: Operation[], enabled: Operation[]): Operation[] {
  if (type.kill_switch) return []
  return type.capability.filter(
    (op) => type.system_enabled_operations.includes(op) && granted.includes(op) && enabled.includes(op)
  )
}

function allocationRead(a: StubAllocation): Record<string, unknown> {
  return {
    ...a,
    effective_max_rate: a.borrow_enabled && a.max_rate !== null ? a.max_rate : a.base_rate,
  }
}

function providersView(projectId: string): Record<string, unknown> {
  const visible = visibleCredentials(projectId)
  const providers = state.providerTypes.map((type) => {
    const creds = visible.filter((v) => v.c.provider_type === type.provider_type)
    const bindings = state.bindings
      .filter((b) => b.project_id === projectId && creds.some((v) => v.c.id === b.credential_id))
      .sort((a, b) => a.priority - b.priority)
      .map((b) => {
        const granted = creds.find((v) => v.c.id === b.credential_id)?.ops ?? []
        return {
          id: b.id,
          credential_id: b.credential_id,
          route_label: b.route_label,
          priority: b.priority,
          enabled_operations: [...b.enabled_operations],
          effective_operations: effectiveOf(type, granted, b.enabled_operations),
        }
      })
    const effective = type.capability.filter((op) => bindings.some((b) => b.effective_operations.includes(op)))
    return {
      provider_type: type.provider_type,
      keyless: type.provider_type === "keenable",
      capability: [...type.capability],
      kill_switch: type.kill_switch,
      system_enabled_operations: [...type.system_enabled_operations],
      available: creds.length > 0,
      enabled: effective.length > 0,
      credentials: creds.map(({ c, ops }) => ({
        id: c.id,
        label: c.label,
        owner_scope: c.owner_scope,
        auth_mode: c.auth_mode,
        status: c.status,
        health_status: c.health_status,
        health_checked_at: "2026-10-01T09:00:00Z",
        granted_operations: ops,
        supported_operations: capabilityOf(c.provider_type),
        pools: state.links
          .filter((l) => l.credential_id === c.id)
          .map((l) => {
            const pool = state.pools.find((p) => p.id === l.pool_id)
            return {
              operation_scope: l.operation_scope,
              pool_id: l.pool_id,
              label: pool?.label ?? "",
              upstream_scope: pool?.upstream_scope ?? "account",
              status: pool?.status ?? "active",
              owner_scope: "system",
            }
          }),
      })),
      bindings,
      effective_operations: effective,
    }
  })
  return {
    project_id: projectId,
    providers,
    allocations: state.allocations.filter((a) => a.project_id === projectId).map(allocationRead),
  }
}

function sectionValue(doc: Record<string, unknown>, attribute: string): unknown {
  return doc[attribute]
}

function resolveSettings(projectId: string): Record<string, unknown> {
  const project = state.projectSettings[projectId] ?? {
    revision: 0,
    overrides: { routing: {}, execution: {}, trace: {} },
  }
  const sys = state.systemSettings
  const fields: Record<string, unknown> = {}
  const effective: Record<string, unknown> = {}
  const provenance: Record<string, string> = {}
  const overrides: Record<string, unknown> = {}
  for (const [fieldId, spec] of Object.entries(FIELD_CATALOG)) {
    const systemValue = sectionValue(sys[spec.section], spec.attribute) ?? null
    const override = project.overrides[spec.section][spec.attribute]
    const hasOverride = override !== undefined && override !== null
    if (hasOverride) overrides[fieldId] = override
    let value: unknown = hasOverride ? override : systemValue
    let prov = hasOverride ? "project_override" : "system_default"
    let limit: unknown = null
    let constrained = false
    if (spec.order !== undefined) {
      limit = systemValue
      if (spec.order.indexOf(String(value)) > spec.order.indexOf(String(systemValue))) {
        value = systemValue
        prov = "system_constrained"
        constrained = true
      }
    } else if (spec.limit !== undefined) {
      limit = sys.safety_limits[spec.limit]
      if (typeof value === "number" && typeof limit === "number" && value > limit) {
        value = limit
        prov = "system_constrained"
        constrained = true
      }
    }
    fields[fieldId] = {
      field_name: fieldId,
      section: spec.section,
      effective_value: value,
      provenance: prov,
      is_null: value === null,
      system_default: systemValue,
      project_override: hasOverride ? override : null,
      source_scope: prov === "project_override" ? "project" : "system",
      override_allowed: true,
      system_safety_limit: limit,
      constraint_applied: constrained,
    }
    effective[fieldId] = value
    provenance[fieldId] = prov
  }
  for (const [fieldId, attribute] of Object.entries(SAFETY_FIELDS)) {
    const value = sys.safety_limits[attribute]
    fields[fieldId] = {
      field_name: fieldId,
      section: "safety_limits",
      effective_value: value,
      provenance: "system_default",
      is_null: false,
      system_default: value,
      project_override: null,
      source_scope: "system",
      override_allowed: false,
      system_safety_limit: null,
      constraint_applied: false,
    }
    effective[fieldId] = value
    provenance[fieldId] = "system_default"
  }
  return {
    namespace: "freesearch.settings",
    fields,
    effective_settings: effective,
    provenance_by_field: provenance,
    system_revision: sys.revision,
    project_revision: project.revision,
    project_id: projectId,
    schema_version: 2,
    overrides,
  }
}

// ---------------------------------------------------------------------------
// HTTP helpers
// ---------------------------------------------------------------------------

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}

async function empty(route: Route, status: number): Promise<void> {
  await route.fulfill({ status, body: "" })
}

async function conflict(route: Route, code: string, message: string): Promise<void> {
  await json(route, { detail: { code, message } }, 409)
}

async function invalid(route: Route, msg: string): Promise<void> {
  await json(route, { detail: [{ loc: ["body"], msg, type: "value_error" }] }, 422)
}

function record(route: Route): ConfigRequest {
  const request = route.request()
  const url = new URL(request.url())
  let body: Record<string, unknown> | null = null
  const raw = request.postData()
  if (raw !== null && raw !== "") {
    try {
      const parsed: unknown = JSON.parse(raw)
      if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
        body = parsed as Record<string, unknown>
      }
    } catch {
      body = null
    }
  }
  const entry = { method: request.method(), path: url.pathname, search: url.search, body }
  configTraffic.push(entry)
  return entry
}

function isOps(value: unknown): value is Operation[] {
  return Array.isArray(value) && value.every((v) => v === "search" || v === "fetch")
}

const UUID = "[0-9a-f-]{36}"

// ---------------------------------------------------------------------------
// Route handlers
// ---------------------------------------------------------------------------

async function handleProjectCredentials(
  route: Route,
  req: ConfigRequest,
  projectId: string,
  permissions: string[]
): Promise<void> {
  const match = new RegExp(`/credentials(?:/(${UUID}))?(/rotate|/oauth(?:/device|/poll)?)?$`).exec(req.path)
  const credentialId = match?.[1]
  const tail = match?.[2]
  if (!permissions.includes("providers.read")) return empty(route, 403)
  if (credentialId === undefined) {
    if (req.method === "GET") {
      return json(
        route,
        visibleCredentials(projectId).map(({ c, ops }) => projectCredentialRead(c, ops, permissions))
      )
    }
    if (req.method !== "POST") return empty(route, 405)
    if (!permissions.includes("credentials.manage_private")) return empty(route, 403)
    return createCredential(route, req.body, "project", projectId, permissions)
  }
  const visible = visibleCredentials(projectId).find((v) => v.c.id === credentialId)
  if (visible === undefined) return empty(route, 404)
  const isPrivate = visible.c.owner_scope === "project"
  if (tail === undefined) {
    if (req.method === "GET") return json(route, projectCredentialRead(visible.c, visible.ops, permissions))
    if (req.method !== "DELETE") return empty(route, 405)
    if (!isPrivate || !permissions.includes("credentials.manage_private")) return empty(route, 403)
    deleteCredential(visible.c.id)
    return empty(route, 204)
  }
  if (tail === "/rotate") {
    if (!isPrivate || !permissions.includes("credentials.manage_private")) return empty(route, 403)
    return rotateCredential(route, req.body, visible.c, (c) =>
      projectCredentialRead(c, visible.ops, permissions)
    )
  }
  if (req.method !== "GET" && (!isPrivate || !permissions.includes("credentials.manage_private"))) {
    return empty(route, 403)
  }
  return handleOAuth(route, req, visible.c, tail)
}

async function createCredential(
  route: Route,
  body: Record<string, unknown> | null,
  owner: "system" | "project",
  projectId: string | null,
  permissions: string[]
): Promise<void> {
  if (body === null) return invalid(route, "invalid body")
  const provider = typeof body.provider_type === "string" ? body.provider_type : ""
  const label = typeof body.label === "string" ? body.label : ""
  const authMode = body.auth_mode === undefined ? "api_key" : body.auth_mode
  if (!state.providerTypes.some((t) => t.provider_type === provider)) return invalid(route, "unknown provider")
  if (label.length < 1 || label.length > 100) return invalid(route, "invalid label")
  if (authMode !== "api_key" && authMode !== "oauth") return invalid(route, "invalid auth_mode")
  if (authMode === "api_key" && (typeof body.secret !== "string" || body.secret === "")) {
    return invalid(route, "secret is required for api_key credentials")
  }
  if (authMode === "oauth" && body.secret !== undefined && body.secret !== null) {
    return invalid(route, "secret is forbidden for oauth credentials")
  }
  if (authMode === "oauth" && provider !== "parallel") return invalid(route, "oauth is Parallel only")
  if (state.credentials.some((c) => c.owner_scope === owner && c.owner_project_id === projectId && c.label === label)) {
    return conflict(route, "CREDENTIAL_LABEL_TAKEN", "A credential with this label already exists.")
  }
  const created = cred(
    nextId(owner === "system" ? "5c000000" : "9c000000"),
    provider,
    label,
    owner,
    projectId,
    1,
    authMode
  )
  state.credentials.push(created)
  if (owner === "system") return json(route, credentialRead(created), 201)
  return json(route, projectCredentialRead(created, capabilityOf(provider), permissions), 201)
}

async function rotateCredential(
  route: Route,
  body: Record<string, unknown> | null,
  c: StubCredential,
  read: (c: StubCredential) => Record<string, unknown>
): Promise<void> {
  if (body === null) return invalid(route, "invalid body")
  if (typeof body.expected_generation !== "number" || typeof body.secret !== "string" || body.secret === "") {
    return invalid(route, "expected_generation and secret are required")
  }
  if (c.auth_mode !== "api_key") return conflict(route, "CREDENTIAL_NOT_ROTATABLE", "OAuth credentials do not rotate.")
  if (body.expected_generation !== c.generation) {
    return conflict(route, "CREDENTIAL_GENERATION_CONFLICT", "The credential generation changed.")
  }
  c.generation += 1
  return json(route, read(c))
}

function deleteCredential(id: string): void {
  state.credentials = state.credentials.filter((c) => c.id !== id)
  state.grants = state.grants.filter((g) => g.credential_id !== id)
  state.bindings = state.bindings.filter((b) => b.credential_id !== id)
  state.links = state.links.filter((l) => l.credential_id !== id)
  delete state.oauth[id]
}

async function handleOAuth(route: Route, req: ConfigRequest, c: StubCredential, tail: string): Promise<void> {
  if (c.auth_mode !== "oauth") return empty(route, 404)
  const flow = (state.oauth[c.id] ??= {
    status: "disconnected",
    approved: false,
    denied: false,
    polls: 0,
    connected_at: null,
    last_error_code: null,
  })
  const status = (interval: number | null) => ({
    credential_id: c.id,
    status: flow.status,
    scopes: flow.status === "connected" ? "balance:read" : null,
    access_expires_at: null,
    connected_at: flow.connected_at,
    refreshed_at: null,
    disconnected_at: null,
    last_error_code: flow.last_error_code,
    interval,
  })
  if (tail === "/oauth/device") {
    if (req.method !== "POST") return empty(route, 405)
    flow.status = "pending"
    flow.approved = false
    flow.denied = false
    flow.polls = 0
    flow.last_error_code = null
    return json(
      route,
      { user_code: OAUTH_USER_CODE, verification_uri: OAUTH_VERIFICATION_URI, interval: 1, expires_in: 600 },
      201
    )
  }
  if (tail === "/oauth/poll") {
    if (req.method !== "POST") return empty(route, 405)
    flow.polls += 1
    if (flow.status === "pending" && flow.denied) {
      // The backend ends a denied flow: the grant is disconnected.
      flow.status = "disconnected"
      flow.last_error_code = "access_denied"
    } else if (flow.status === "pending" && flow.approved) {
      flow.status = "connected"
      flow.connected_at = "2026-11-02T10:00:00Z"
    }
    return json(route, status(flow.status === "pending" ? 1 : null))
  }
  if (req.method === "GET") return json(route, status(null))
  if (req.method === "DELETE") {
    flow.status = "disconnected"
    flow.connected_at = null
    return empty(route, 204)
  }
  return empty(route, 405)
}

async function handleBindings(
  route: Route,
  req: ConfigRequest,
  projectId: string,
  permissions: string[]
): Promise<void> {
  if (!permissions.includes("providers.read")) return empty(route, 403)
  const bindingId = new RegExp(`/bindings/(${UUID})$`).exec(req.path)?.[1]
  if (bindingId === undefined) {
    if (req.method === "GET") return json(route, projectBindings(projectId).map(bindingRead))
    if (req.method !== "POST") return empty(route, 405)
    if (!permissions.includes("providers.configure")) return empty(route, 403)
    const body = req.body
    if (body === null) return invalid(route, "invalid body")
    if ("enabled_operations" in body) return invalid(route, "enabled_operations is not accepted on create")
    const credentialId = typeof body.credential_id === "string" ? body.credential_id : ""
    const routeLabel = typeof body.route_label === "string" ? body.route_label : ""
    const priority = body.priority === undefined ? 100 : body.priority
    if (routeLabel.length < 1 || routeLabel.length > 100) return invalid(route, "invalid route_label")
    if (typeof priority !== "number" || priority < 0) return invalid(route, "invalid priority")
    if (!visibleCredentials(projectId).some((v) => v.c.id === credentialId)) return empty(route, 404)
    const created: StubBinding = {
      id: nextId("b3000000"),
      project_id: projectId,
      credential_id: credentialId,
      route_label: routeLabel,
      enabled_operations: [],
      priority,
      version: 1,
    }
    state.bindings.push(created)
    return json(route, bindingRead(created), 201)
  }
  const binding = state.bindings.find((b) => b.id === bindingId && b.project_id === projectId)
  if (binding === undefined) return empty(route, 404)
  if (!permissions.includes("providers.configure")) return empty(route, 403)
  if (req.method === "DELETE") {
    state.bindings = state.bindings.filter((b) => b.id !== bindingId)
    return empty(route, 204)
  }
  if (req.method !== "PATCH") return empty(route, 405)
  const body = req.body ?? {}
  if (body.enabled_operations !== undefined && body.enabled_operations !== null) {
    if (!isOps(body.enabled_operations)) return invalid(route, "invalid enabled_operations")
    const granted = visibleCredentials(projectId).find((v) => v.c.id === binding.credential_id)?.ops ?? []
    if (body.enabled_operations.some((op) => !granted.includes(op))) {
      return conflict(route, "OPERATION_NOT_GRANTED", "The credential does not permit this operation.")
    }
    binding.enabled_operations = [...new Set(body.enabled_operations)]
  }
  if (typeof body.priority === "number") binding.priority = body.priority
  if (typeof body.route_label === "string") binding.route_label = body.route_label
  binding.version += 1
  return json(route, bindingRead(binding))
}

async function handleSettings(
  route: Route,
  req: ConfigRequest,
  projectId: string,
  permissions: string[]
): Promise<void> {
  if (!permissions.includes("settings.read")) return empty(route, 403)
  if (req.method === "GET") return json(route, resolveSettings(projectId))
  if (req.method !== "PUT") return empty(route, 405)
  if (!permissions.includes("settings.write")) return empty(route, 403)
  const body = req.body
  if (body === null || typeof body.expected_revision !== "number") return invalid(route, "expected_revision required")
  const doc = (state.projectSettings[projectId] ??= {
    revision: 0,
    overrides: { routing: {}, execution: {}, trace: {} },
  })
  if (body.expected_revision !== doc.revision) {
    return conflict(route, "SETTINGS_REVISION_CONFLICT", "Project settings changed since they were read.")
  }
  for (const section of ["routing", "execution", "trace"] as const) {
    if (!(section in body)) continue
    const value = body[section]
    if (value === null) {
      doc.overrides[section] = {}
      continue
    }
    if (typeof value !== "object" || Array.isArray(value)) return invalid(route, `invalid ${section}`)
    for (const [attr, v] of Object.entries(value as Record<string, unknown>)) {
      if (FIELD_CATALOG[`${section}.${attr}`] === undefined) return invalid(route, `unknown field ${section}.${attr}`)
      if (v === null) delete doc.overrides[section][attr]
      else doc.overrides[section][attr] = v
    }
  }
  doc.revision += 1
  return json(route, resolveSettings(projectId))
}

function copyPlan(
  sourceId: string,
  targetId: string,
  mode: string,
  selectedVersions: Record<string, number> | null
): Record<string, unknown> {
  const source = resolveSettings(sourceId)
  const target = resolveSettings(targetId)
  const sourceFields = source.fields as Record<string, { effective_value: unknown; provenance: string; constraint_applied: boolean; project_override: unknown }>
  const targetFields = target.fields as Record<string, { effective_value: unknown }>
  const fields: Record<string, unknown>[] = []
  const overrides: Record<string, unknown> = {}
  for (const [fieldId, spec] of Object.entries(FIELD_CATALOG)) {
    const field = sourceFields[fieldId]
    if (field === undefined) continue
    if (mode === "overrides_only" && field.provenance === "system_default") continue
    const value = mode === "overrides_only" ? field.project_override ?? field.effective_value : field.effective_value
    overrides[fieldId] = value
    fields.push({
      field_id: fieldId,
      section: spec.section,
      attribute: spec.attribute,
      provenance: field.provenance,
      value,
      changed: JSON.stringify(targetFields[fieldId]?.effective_value) !== JSON.stringify(value),
      constraint_applied: field.constraint_applied,
    })
  }
  const visibleToTarget = visibleCredentials(targetId)
  const rejected: Record<string, unknown>[] = []
  const bindings = projectBindings(sourceId).map((b) => {
    const eligible = visibleToTarget.some((v) => v.c.id === b.credential_id)
    const rejection = eligible ? null : "The credential is not available to the target project."
    if (!eligible) rejected.push({ field_id: `binding:${b.id}`, reason: rejection })
    return {
      binding_id: b.id,
      credential_id: b.credential_id,
      route_label: b.route_label,
      version: b.version,
      selected: eligible && (selectedVersions === null || b.id in selectedVersions),
      eligible,
      rejection,
    }
  })
  return {
    source_project_id: sourceId,
    target_project_id: targetId,
    mode,
    source_revision: state.projectSettings[sourceId]?.revision ?? 0,
    target_revision: state.projectSettings[targetId]?.revision ?? 0,
    system_revision: state.systemSettings.revision,
    overrides,
    effective_snapshot: source.effective_settings,
    fields,
    rejected,
    bindings,
    target,
  }
}

async function handleCopy(
  route: Route,
  req: ConfigRequest,
  targetId: string,
  permissions: string[],
  bridge: ProjectAccessBridge
): Promise<void> {
  if (req.method !== "POST") return empty(route, 405)
  if (!permissions.includes("settings.copy") || !permissions.includes("settings.write")) return empty(route, 403)
  const body = req.body
  if (body === null || typeof body.source_project_id !== "string") return invalid(route, "source_project_id required")
  const source = bridge.access(body.source_project_id)
  if (source === null) return empty(route, 404)
  if (!source.permissions.includes("settings.read")) return empty(route, 403)
  const mode = body.mode === undefined ? "overrides_only" : body.mode
  if (mode !== "overrides_only" && mode !== "effective_snapshot") return invalid(route, "invalid mode")
  for (const key of ["expected_source_revision", "expected_target_revision", "expected_system_revision"]) {
    if (typeof body[key] !== "number") return invalid(route, `${key} required`)
  }
  const isApply = req.path.endsWith("/settings/copy")
  const stale =
    body.expected_source_revision !== (state.projectSettings[source.id]?.revision ?? 0) ||
    body.expected_target_revision !== (state.projectSettings[targetId]?.revision ?? 0) ||
    body.expected_system_revision !== state.systemSettings.revision
  if (!isApply) {
    // A preview binds to the current revisions; it never writes.
    return json(route, copyPlan(source.id, targetId, mode, null))
  }
  if (stale) return conflict(route, "SETTINGS_COPY_STALE", "Settings changed since the preview.")
  const versions = (body.binding_versions ?? {}) as Record<string, number>
  for (const [bindingId, version] of Object.entries(versions)) {
    const b = state.bindings.find((x) => x.id === bindingId && x.project_id === source.id)
    if (b === undefined || b.version !== version) {
      return conflict(route, "SETTINGS_COPY_STALE", "A selected binding changed since the preview.")
    }
  }
  const plan = copyPlan(source.id, targetId, mode, versions)
  const doc = (state.projectSettings[targetId] ??= { revision: 0, overrides: { routing: {}, execution: {}, trace: {} } })
  for (const [fieldId, value] of Object.entries(plan.overrides as Record<string, unknown>)) {
    const spec = FIELD_CATALOG[fieldId]
    if (spec !== undefined) doc.overrides[spec.section][spec.attribute] = value
  }
  doc.revision += 1
  const copied: string[] = []
  for (const b of plan.bindings as Array<{ binding_id: string; selected: boolean; eligible: boolean }>) {
    if (!b.selected || !b.eligible || !(b.binding_id in versions)) continue
    const src = state.bindings.find((x) => x.id === b.binding_id)
    if (src === undefined) continue
    const created: StubBinding = { ...src, id: nextId("b3000000"), project_id: targetId, version: 1 }
    state.bindings.push(created)
    copied.push(created.id)
  }
  return json(route, {
    ...plan,
    target_revision: doc.revision,
    target: resolveSettings(targetId),
    bindings_copied: copied,
    audit_event_id: "a0000000-0000-4000-8000-000000000001",
  })
}

/**
 * Register the U3 routes. Call after the project catch-all route so these
 * take precedence (Playwright prefers the most recently registered handler).
 */
export async function installProviderConfigRoutes(page: Page, bridge: ProjectAccessBridge): Promise<void> {
  const projectPattern = new RegExp(
    `^/api/v1/projects/(${UUID})/(providers|bindings|credentials|settings)(/.*)?$`
  )
  await page.route(
    (url) => projectPattern.test(url.pathname),
    async (route) => {
      const url = new URL(route.request().url())
      const match = projectPattern.exec(url.pathname)
      if (match === null) return route.fallback()
      const [, projectId, resource] = match
      // The U2 provider view stays in charge until a U3 scenario activates this stub.
      if (resource === "providers" && !state.active) return route.fallback()
      const req = record(route)
      const access = bridge.access(projectId)
      if (access === null) return empty(route, 404)
      if (resource === "providers") {
        if (req.method !== "GET" || req.path !== `/api/v1/projects/${projectId}/providers`) return empty(route, 404)
        if (!access.permissions.includes("providers.read")) return empty(route, 403)
        return json(route, providersView(projectId))
      }
      if (resource === "bindings") {
        if (req.method !== "GET" || req.path !== `/api/v1/projects/${projectId}/bindings`) return empty(route, 404)
        return handleBindings(route, req, projectId, access.permissions)
      }
      if (resource === "credentials") {
        if (req.method !== "GET" || req.path !== `/api/v1/projects/${projectId}/credentials`) return empty(route, 404)
        return handleProjectCredentials(route, req, projectId, access.permissions)
      }
      if (req.path.endsWith("/settings")) return handleSettings(route, req, projectId, access.permissions)
      if (/\/settings\/copy(\/preview)?$/.test(req.path)) {
        return handleCopy(route, req, projectId, access.permissions, bridge)
      }
      return empty(route, 404)
    }
  )


}
