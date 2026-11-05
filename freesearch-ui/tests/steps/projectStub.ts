import type { Page, Route } from "@playwright/test"
import { SYSTEM_ADMIN_PERMISSIONS } from "./accountStub"
import {
  recordTraceDetailRequest,
  recordTraceListRequest,
  setExecutionGate,
  traceDetailFailureMessage,
  traceListFailureMessage,
} from "./backendStub"
import {
  ALPHA_PROJECT_ID,
  BETA_PROJECT_ID,
  projectProviders,
  projectTraceDetail,
  projectTraceList,
  projectUsage,
  resetProjectActivityStub,
} from "./projectActivityStub"
import { installProviderConfigRoutes, resetProviderConfigStub } from "./providerConfigStub"

/**
 * In-memory projects backend for project-shell and project API key scenarios.
 *
 * The state lives at module level so two tabs of one browser context share it.
 * Accounts carry no role: system authority is the system permission list of
 * the signed-in account (GET /api/v1/system/access), and project authority is
 * computed from live project role assignments with a fixture copy of the
 * backend's built-in role table (test-side only), served as the project access
 * descriptor (GET /api/v1/projects/{id}/access).
 *
 * Project API keys mirror the backend contract (TASK-000041): issue and rotate
 * answer 201 with the raw key once, the list never carries a raw key, revoke
 * answers 204, rotating an inactive or already rotated key answers
 * 409 {"detail": {"code": "API_KEY_INACTIVE"}}, an omitted `expires_at` on issue
 * means +90 days and an explicit null means no expiration. Stub raw keys are
 * obviously fake (`fs_live_stubprefixNN_FAKE...`).
 *
 * Project reads of U2 (TASK-000047) follow the same membership rule: traces
 * (traces.read), usage and dashboard (usage.read) and the provider view
 * (providers.read) answer 404 for a non-member and 403 without the
 * permission; their data comes from projectActivityStub.ts. POST /search and
 * POST /fetch resolve their `project_id` through the gate installed here.
 */

export const ALPHA_ID = ALPHA_PROJECT_ID
export const BETA_ID = BETA_PROJECT_ID
export const GAMMA_ID = "cccccccc-3333-4333-8333-cccccccccccc"
export const USER_ID = "33333333-3333-4333-8333-333333333333"
const PEER_ID = "44444444-4444-4444-8444-444444444444"

const DAY_MS = 86_400_000
const DEFAULT_LIFETIME_DAYS = 90
const DEFAULT_OVERLAP_SECONDS = 86_400
const MAX_OVERLAP_SECONDS = 604_800
const API_KEY_SCOPES = ["fetch.execute", "search.execute"] as const

/** Fixture copy of the backend's built-in project roles (models/projects.py). */
const ROLE_PERMISSIONS: Record<string, string[]> = {
  project_admin: [
    "project.read",
    "project.archive",
    "members.read",
    "members.manage",
    "roles.assign",
    "settings.read",
    "settings.write",
    "settings.copy",
    "providers.read",
    "providers.configure",
    "credentials.manage_private",
    "tokens.manage",
    "routing.write",
    "traces.read",
    "usage.read",
    "search.execute",
    "fetch.execute",
  ],
  project_member: [
    "project.read",
    "members.read",
    "settings.read",
    "providers.read",
    "traces.read",
    "usage.read",
    "search.execute",
    "fetch.execute",
  ],
  routing_editor: ["project.read", "settings.read", "providers.read", "routing.write"],
  provider_editor: [
    "project.read",
    "settings.read",
    "providers.read",
    "providers.configure",
    "credentials.manage_private",
  ],
  token_manager: ["project.read", "tokens.manage"],
}

interface StubMember {
  user_id: string
  email: string
  status: "active" | "suspended"
  roles: string[]
  version: number
}

interface StubApiKey {
  id: string
  project_id: string
  label: string
  prefix: string
  scopes: string[]
  created_by: string
  created_at: string
  expires_at: string | null
  revoked_at: string | null
  last_used_at: string | null
  rotated_from_id: string | null
  /** Insertion order, for a stable newest-first list at equal timestamps. */
  seq: number
}

interface StubProject {
  id: string
  name: string
  status: "active" | "archived"
  members: StubMember[]
  apiKeys: StubApiKey[]
}

interface ProjectStubState {
  /** Email of the signed-in account; empty means no memberships resolve. */
  userEmail: string
  /** Account id the signed-in session reports from GET /users/me. */
  accountId: string
  /** System-scope permission list of the signed-in account. */
  systemPermissions: string[]
  projects: StubProject[]
  /** Delay in ms applied to the Alpha members read (rapid-switch scenario). */
  alphaMembersDelayMs: number
  apiKeySeq: number
}

const state: ProjectStubState = {
  userEmail: "",
  accountId: USER_ID,
  systemPermissions: [],
  projects: [],
  alphaMembersDelayMs: 0,
  apiKeySeq: 0,
}

/**
 * Evidence of the API key wire traffic for assertions. Request bodies are the
 * parsed JSON the UI sent; `rawKeys` holds the fake raw keys the stub revealed,
 * newest last, so a scenario can prove a key was shown once and then left the
 * page and the browser storage.
 */
export const apiKeyTraffic: {
  issueBodies: Record<string, unknown>[]
  rotateBodies: Record<string, unknown>[]
  revokedIds: string[]
  rawKeys: string[]
} = { issueBodies: [], rotateBodies: [], revokedIds: [], rawKeys: [] }

export function resetProjectStub(): void {
  state.userEmail = ""
  state.accountId = USER_ID
  state.systemPermissions = []
  resetProjectActivityStub()
  resetProviderConfigStub()
  projectReadTraffic.length = 0
  state.alphaMembersDelayMs = 0
  state.apiKeySeq = 0
  apiKeyTraffic.issueBodies.length = 0
  apiKeyTraffic.rotateBodies.length = 0
  apiKeyTraffic.revokedIds.length = 0
  apiKeyTraffic.rawKeys.length = 0
  state.projects = [
    {
      id: ALPHA_ID,
      name: "Alpha",
      status: "active",
      members: [
        { user_id: USER_ID, email: "", status: "active", roles: ["project_member"], version: 1 },
        {
          user_id: PEER_ID,
          email: "alpha-peer@example.com",
          status: "active",
          roles: ["project_member"],
          version: 1,
        },
      ],
      apiKeys: [],
    },
    { id: BETA_ID, name: "Beta", status: "active", members: [], apiKeys: [] },
  ]
}

/** Point the stub at one signed-in account email and its system permissions. */
export function setProjectStubAccount(
  email: string,
  systemPermissions: readonly string[] = [],
  accountId: string = USER_ID
): void {
  state.userEmail = email
  state.accountId = accountId
  state.systemPermissions = [...systemPermissions]
  for (const project of state.projects) {
    for (const member of project.members) {
      if (member.email === "") member.email = email
    }
  }
}

/** Account id of the signed-in session (the owner of persisted playground keys). */
export function projectStubAccountId(): string {
  return state.accountId
}

/** Id of one stub project by its name. */
export function projectStubId(projectName: string): string {
  const project = state.projects.find((p) => p.name === projectName)
  if (project === undefined) throw new Error(`unknown stub project ${projectName}`)
  return project.id
}

/** Grant the signed-in account the system administrator permission set. */
export function setProjectStubSystemAdmin(): void {
  state.systemPermissions = [...SYSTEM_ADMIN_PERMISSIONS]
}

/** Ensure the signed-in account holds exactly these roles in one project. */
export function setProjectStubRoles(projectName: string, roles: string[]): void {
  const project = state.projects.find((p) => p.name === projectName)
  if (project === undefined) return
  const member = project.members.find((m) => m.email === state.userEmail)
  if (member === undefined) {
    project.members.push({
      user_id: USER_ID,
      email: state.userEmail,
      status: "active",
      roles,
      version: 1,
    })
    return
  }
  member.roles = roles
  member.version += 1
}

/** Remove every membership of one account, keeping its stub identity. */
export function clearProjectStubMemberships(email: string): void {
  for (const project of state.projects) {
    project.members = project.members.filter((m) => m.email !== email)
  }
}

/** Rename one stub project (long-name visual scenarios). */
export function renameProjectStub(projectName: string, newName: string): void {
  const project = state.projects.find((p) => p.name === projectName)
  if (project === undefined) throw new Error(`unknown stub project ${projectName}`)
  project.name = newName
}

/** Remove the signed-in account's membership of one project. */
export function removeProjectStubMember(projectName: string, email: string): void {
  const project = state.projects.find((p) => p.name === projectName)
  if (project === undefined) return
  project.members = project.members.filter((m) => m.email !== email)
}

function nextKeyMaterial(): { id: string; prefix: string; raw: string; seq: number } {
  state.apiKeySeq += 1
  const seq = state.apiKeySeq
  const nn = String(seq).padStart(2, "0")
  const prefix = `stubprefix${nn}`
  return {
    id: `dddddddd-0000-4000-8000-${String(seq).padStart(12, "0")}`,
    prefix,
    // 43 characters after the separator, like token_urlsafe(32); plainly fake.
    raw: `fs_live_${prefix}_${"FAKE".repeat(10)}${nn}X`,
    seq,
  }
}

/**
 * Seed one existing key in a project, created by the signed-in account.
 * `expiresInDays` null means no expiration; `lastUsedMinutesAgo` null means
 * never used.
 */
export function seedProjectStubApiKey(
  projectName: string,
  label: string,
  options: { expiresInDays?: number | null; lastUsedMinutesAgo?: number | null } = {}
): void {
  const project = state.projects.find((p) => p.name === projectName)
  if (project === undefined) throw new Error(`unknown stub project ${projectName}`)
  const material = nextKeyMaterial()
  const now = Date.now()
  const createdAt = now - 2 * DAY_MS + material.seq * 1000
  const expiresInDays = options.expiresInDays === undefined ? 30 : options.expiresInDays
  const lastUsed = options.lastUsedMinutesAgo === undefined ? 5 : options.lastUsedMinutesAgo
  project.apiKeys.push({
    id: material.id,
    project_id: project.id,
    label,
    prefix: material.prefix,
    scopes: [...API_KEY_SCOPES],
    created_by: USER_ID,
    created_at: new Date(createdAt).toISOString(),
    expires_at: expiresInDays === null ? null : new Date(now + expiresInDays * DAY_MS).toISOString(),
    revoked_at: null,
    last_used_at: lastUsed === null ? null : new Date(now - lastUsed * 60_000).toISOString(),
    rotated_from_id: null,
    seq: material.seq,
  })
}

/** Release latch of the held Alpha members response (rapid-switch scenario). */
let alphaMembersRelease: (() => void) | null = null

/** Hold the Alpha members response open until released by the test. */
export function holdProjectStubMembers(projectName: string): void {
  if (projectName === "Alpha") state.alphaMembersDelayMs = -1
}

/** Release a held members response; a no-op when none is held. */
export function releaseProjectStubMembers(): void {
  alphaMembersRelease?.()
  alphaMembersRelease = null
}

/** Delay the Alpha members response for the rapid-switch scenario. */
export function delayProjectStubMembers(projectName: string, ms: number): void {
  if (projectName === "Alpha") state.alphaMembersDelayMs = ms
}

function projectOf(url: URL): StubProject | null {
  const match = /^\/api\/v1\/projects\/([0-9a-f-]{36})(\/.*)?$/.exec(url.pathname)
  if (match === null) return null
  return state.projects.find((p) => p.id === match[1]) ?? null
}

function memberOf(project: StubProject): StubMember | null {
  return (
    project.members.find(
      (m) => m.email === state.userEmail && m.status === "active"
    ) ?? null
  )
}

function permissionsOf(member: StubMember | null): string[] {
  if (member === null) return []
  const permissions = new Set<string>()
  for (const role of member.roles) {
    for (const permission of ROLE_PERMISSIONS[role] ?? []) permissions.add(permission)
  }
  return [...permissions].sort()
}

async function json(route: Route, body: unknown, status = 200): Promise<void> {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) })
}

async function empty(route: Route, status: number): Promise<void> {
  await route.fulfill({ status, body: "" })
}

async function conflict(route: Route, code: string, message: string): Promise<void> {
  await json(route, { detail: { code, message } }, 409)
}

function projectWire(project: StubProject): Record<string, unknown> {
  return {
    id: project.id,
    account_id: "00000000-0000-4000-8000-000000000001",
    name: project.name,
    slug: project.name.toLowerCase(),
    status: project.status,
    created_by: USER_ID,
    created_at: "2026-01-01T00:00:00Z",
    version: 1,
  }
}

function keyStatus(key: StubApiKey, now: number): "active" | "expired" | "revoked" {
  if (key.revoked_at !== null) return "revoked"
  if (key.expires_at !== null && Date.parse(key.expires_at) <= now) return "expired"
  return "active"
}

function keyWire(key: StubApiKey, now: number): Record<string, unknown> {
  return {
    id: key.id,
    project_id: key.project_id,
    label: key.label,
    prefix: key.prefix,
    scopes: [...key.scopes].sort(),
    created_by: key.created_by,
    created_at: key.created_at,
    expires_at: key.expires_at,
    revoked_at: key.revoked_at,
    last_used_at: key.last_used_at,
    rotated_from_id: key.rotated_from_id,
    status: keyStatus(key, now),
  }
}

async function oneTime(route: Route, body: Record<string, unknown>): Promise<void> {
  await route.fulfill({
    status: 201,
    contentType: "application/json",
    headers: { "Cache-Control": "no-store" },
    body: JSON.stringify(body),
  })
}

function readBody(route: Route): Record<string, unknown> | null {
  const raw = route.request().postData()
  if (raw === null || raw === "") return {}
  try {
    const parsed: unknown = JSON.parse(raw)
    return parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)
      ? (parsed as Record<string, unknown>)
      : null
  } catch {
    return null
  }
}

/** Resolve an explicit `expires_at`: null stays null, a string must be a future instant. */
function explicitExpiry(value: unknown, now: number): { ok: true; value: string | null } | { ok: false } {
  if (value === null) return { ok: true, value: null }
  if (typeof value !== "string") return { ok: false }
  const at = Date.parse(value)
  if (Number.isNaN(at) || at <= now) return { ok: false }
  return { ok: true, value: new Date(at).toISOString() }
}

async function handleIssue(route: Route, project: StubProject, held: string[]): Promise<void> {
  const body = readBody(route)
  if (body === null) return json(route, { detail: "invalid body" }, 422)
  apiKeyTraffic.issueBodies.push(body)
  const label = typeof body.label === "string" ? body.label : ""
  if (label.length < 1 || label.length > 100) return json(route, { detail: "invalid label" }, 422)
  const scopes =
    body.scopes === undefined ? [...API_KEY_SCOPES] : Array.isArray(body.scopes) ? body.scopes : null
  if (
    scopes === null ||
    scopes.length === 0 ||
    scopes.some((s) => typeof s !== "string" || !(API_KEY_SCOPES as readonly string[]).includes(s))
  ) {
    return json(route, { detail: "invalid scopes" }, 422)
  }
  if (scopes.some((s) => !held.includes(s as string))) return empty(route, 403)
  if (project.status === "archived") {
    return conflict(route, "PROJECT_ARCHIVED", "archived projects cannot issue API keys")
  }
  const now = Date.now()
  let expiresAt: string | null
  if (!("expires_at" in body)) {
    expiresAt = new Date(now + DEFAULT_LIFETIME_DAYS * DAY_MS).toISOString()
  } else {
    const resolved = explicitExpiry(body.expires_at, now)
    if (!resolved.ok) return json(route, { detail: "expires_at must be in the future" }, 422)
    expiresAt = resolved.value
  }
  const material = nextKeyMaterial()
  const key: StubApiKey = {
    id: material.id,
    project_id: project.id,
    label,
    prefix: material.prefix,
    scopes: [...new Set(scopes as string[])].sort(),
    created_by: USER_ID,
    created_at: new Date(now).toISOString(),
    expires_at: expiresAt,
    revoked_at: null,
    last_used_at: null,
    rotated_from_id: null,
    seq: material.seq,
  }
  project.apiKeys.push(key)
  apiKeyTraffic.rawKeys.push(material.raw)
  return oneTime(route, { ...keyWire(key, now), key: material.raw })
}

async function handleRotate(
  route: Route,
  project: StubProject,
  keyId: string,
  held: string[]
): Promise<void> {
  const old = project.apiKeys.find((k) => k.id === keyId)
  if (old === undefined) return empty(route, 404)
  const body = readBody(route)
  if (body === null) return json(route, { detail: "invalid body" }, 422)
  apiKeyTraffic.rotateBodies.push(body)
  if (old.scopes.some((s) => !held.includes(s))) return empty(route, 403)
  if (project.status === "archived") {
    return conflict(route, "PROJECT_ARCHIVED", "archived projects cannot issue API keys")
  }
  const now = Date.now()
  const hasSuccessor = project.apiKeys.some((k) => k.rotated_from_id === old.id)
  if (keyStatus(old, now) !== "active" || hasSuccessor) {
    return conflict(route, "API_KEY_INACTIVE", "only an active, not yet rotated API key can be rotated")
  }
  const overlap = body.overlap_seconds === undefined ? DEFAULT_OVERLAP_SECONDS : body.overlap_seconds
  if (
    typeof overlap !== "number" ||
    !Number.isInteger(overlap) ||
    overlap < 0 ||
    overlap > MAX_OVERLAP_SECONDS
  ) {
    return json(route, { detail: "invalid overlap_seconds" }, 422)
  }
  let expiresAt: string | null
  if ("expires_at" in body) {
    const resolved = explicitExpiry(body.expires_at, now)
    if (!resolved.ok) return json(route, { detail: "expires_at must be in the future" }, 422)
    expiresAt = resolved.value
  } else if (old.expires_at === null) {
    expiresAt = null
  } else {
    const lifetime = Date.parse(old.expires_at) - Date.parse(old.created_at)
    expiresAt = new Date(now + lifetime).toISOString()
  }
  const material = nextKeyMaterial()
  const replacement: StubApiKey = {
    id: material.id,
    project_id: project.id,
    label: old.label,
    prefix: material.prefix,
    scopes: [...old.scopes],
    created_by: USER_ID,
    created_at: new Date(now).toISOString(),
    expires_at: expiresAt,
    revoked_at: null,
    last_used_at: null,
    rotated_from_id: old.id,
    seq: material.seq,
  }
  project.apiKeys.push(replacement)
  if (overlap === 0) {
    old.revoked_at = new Date(now).toISOString()
  } else {
    const overlapEnd = now + overlap * 1000
    const bounded =
      old.expires_at === null ? overlapEnd : Math.min(Date.parse(old.expires_at), overlapEnd)
    old.expires_at = new Date(bounded).toISOString()
  }
  apiKeyTraffic.rawKeys.push(material.raw)
  return oneTime(route, { ...keyWire(replacement, now), key: material.raw })
}

/** Pages (tabs) that registered the project routes. */
const installedPages = new WeakSet<Page>()

/** Whether this tab already serves the project routes. */
export function isProjectStubInstalled(page: Page): boolean {
  return installedPages.has(page)
}

/** Resolve one POST /search or /fetch `project_id` like the backend. */
function executionGate(
  projectId: string,
  permission: "search.execute" | "fetch.execute"
): { status: 200; projectName: string } | { status: 403 | 404 } {
  const project = state.projects.find((p) => p.id === projectId) ?? null
  const member = project === null ? null : memberOf(project)
  if (project === null || member === null) return { status: 404 }
  if (!permissionsOf(member).includes(permission)) return { status: 403 }
  return { status: 200, projectName: project.name }
}

/**
 * Resolve one project read: the uniform 404 for an unknown project or a
 * non-member, 403 without the permission, otherwise the project.
 */
function readableProject(
  url: URL,
  permission: string
): { ok: true; project: StubProject } | { ok: false; status: 403 | 404 } {
  const project = projectOf(url)
  const member = project === null ? null : memberOf(project)
  if (project === null || member === null) return { ok: false, status: 404 }
  if (!permissionsOf(member).includes(permission)) return { ok: false, status: 403 }
  return { ok: true, project }
}

/**
 * Install the project routes after the default backend stub so they override
 * its answers for every tab that registers them. `systemAccess: false` keeps
 * the backend stub's system access read (setStubbedSystemPermissions), for
 * scenarios that add project membership to the default session.
 */
export async function installProjectStub(
  page: Page,
  options: { systemAccess?: boolean } = {}
): Promise<void> {
  const serveSystemAccess = options.systemAccess ?? true
  installedPages.add(page)
  setExecutionGate(executionGate)
  if (serveSystemAccess) {
    await page.unroute((url) => url.pathname === "/api/v1/system/access").catch(() => {})
  }
  await page
    .unroute(
      (url) =>
        url.pathname === "/api/v1/projects" || url.pathname.startsWith("/api/v1/projects/")
    )
    .catch(() => {})

  if (serveSystemAccess) {
    await page.route(
      (url) => url.pathname === "/api/v1/system/access",
      (route) => {
        if (route.request().method() !== "GET") return route.fallback()
        return json(route, {
          rollout_state: "preview",
          permissions: [...state.systemPermissions].sort(),
        })
      }
    )
  }

  await page.route((url) => url.pathname === "/api/v1/projects", (route) => {
    const method = route.request().method()
    if (method === "GET") {
      const readable = state.projects.filter((p) => memberOf(p) !== null)
      return json(route, readable.map(projectWire))
    }
    if (method === "POST") {
      // The backend authorizes creation with the system-scoped project.create.
      if (!state.systemPermissions.includes("project.create")) {
        return empty(route, 403)
      }
      const body = readBody(route) ?? {}
      const email = typeof body.initial_admin_email === "string" ? body.initial_admin_email : ""
      if (email.trim().toLowerCase() !== state.userEmail) {
        return json(route, {}, 400)
      }
      const created: StubProject = {
        id: GAMMA_ID,
        name: String(body.name ?? "New project"),
        status: "active",
        members: [
          { user_id: USER_ID, email: state.userEmail, status: "active", roles: ["project_admin"], version: 1 },
        ],
        apiKeys: [],
      }
      state.projects.push(created)
      return json(route, projectWire(created), 201)
    }
    return route.fallback()
  })

  // Any other project resource: the uniform 404 for an unknown project or a
  // non-member, otherwise a 404 for a sub-resource U1 does not stub.
  await page.route(
    (url) => url.pathname.startsWith("/api/v1/projects/"),
    (route) => {
      const url = new URL(route.request().url())
      const project = projectOf(url)
      if (project === null || memberOf(project) === null) return empty(route, 404)
      if (/^\/api\/v1\/projects\/[0-9a-f-]{36}$/.test(url.pathname) && route.request().method() === "GET") {
        return json(route, projectWire(project))
      }
      return empty(route, 404)
    }
  )

  await page.route(
    (url) => /^\/api\/v1\/projects\/[0-9a-f-]{36}\/access$/.test(url.pathname),
    (route) => {
      const url = new URL(route.request().url())
      const project = projectOf(url)
      const member = project === null ? null : memberOf(project)
      if (project === null || member === null) return empty(route, 404)
      return json(route, {
        project_id: project.id,
        permissions: permissionsOf(member),
        roles: [...member.roles].sort(),
        policy_revision: member.version,
      })
    }
  )

  await page.route(
    (url) => /^\/api\/v1\/projects\/[0-9a-f-]{36}\/members$/.test(url.pathname),
    async (route) => {
      const url = new URL(route.request().url())
      const project = projectOf(url)
      const member = project === null ? null : memberOf(project)
      if (project === null || member === null) return empty(route, 404)
      if (!permissionsOf(member).includes("members.read")) return empty(route, 403)
      if (route.request().method() !== "GET") return route.fallback()
      if (project.name === "Alpha" && state.alphaMembersDelayMs === -1) {
        await new Promise<void>((resolve) => {
          alphaMembersRelease = resolve
        })
      } else if (project.name === "Alpha" && state.alphaMembersDelayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, state.alphaMembersDelayMs))
      }
      return json(
        route,
        project.members.map((m) => ({
          project_id: project.id,
          user_id: m.user_id,
          email: m.email,
          status: m.status,
          roles: [...m.roles].sort(),
          version: m.version,
        }))
      )
    }
  )

  await page.route(
    (url) =>
      /^\/api\/v1\/projects\/[0-9a-f-]{36}\/api-keys(\/[0-9a-f-]{36}(\/rotate)?)?$/.test(
        url.pathname
      ),
    async (route) => {
      const url = new URL(route.request().url())
      const project = projectOf(url)
      const member = project === null ? null : memberOf(project)
      if (project === null || member === null) return empty(route, 404)
      const held = permissionsOf(member)
      if (!held.includes("tokens.manage")) return empty(route, 403)
      const method = route.request().method()
      const match = /\/api-keys(?:\/([0-9a-f-]{36})(\/rotate)?)?$/.exec(url.pathname)
      const keyId = match?.[1]
      const isRotate = match?.[2] !== undefined
      if (keyId === undefined) {
        if (method === "GET") {
          const now = Date.now()
          const newestFirst = [...project.apiKeys].sort(
            (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.seq - a.seq
          )
          return json(route, newestFirst.map((key) => keyWire(key, now)))
        }
        if (method === "POST") return handleIssue(route, project, held)
        return empty(route, 405)
      }
      if (isRotate) {
        if (method !== "POST") return empty(route, 405)
        return handleRotate(route, project, keyId, held)
      }
      if (method !== "DELETE") return empty(route, 405)
      const key = project.apiKeys.find((k) => k.id === keyId)
      if (key === undefined) return empty(route, 404)
      if (key.revoked_at === null) key.revoked_at = new Date().toISOString()
      apiKeyTraffic.revokedIds.push(keyId)
      return empty(route, 204)
    }
  )

  // Activity list: newest first, filters and an opaque project-bound cursor.
  await page.route(
    (url) => /^\/api\/v1\/projects\/[0-9a-f-]{36}\/traces$/.test(url.pathname),
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      const url = new URL(route.request().url())
      const access = readableProject(url, "traces.read")
      if (!access.ok) return empty(route, access.status)
      recordTraceListRequest(url.search)
      const failure = traceListFailureMessage()
      if (failure !== null) return json(route, { detail: failure }, 500)
      const answer = projectTraceList(access.project.id, url.searchParams)
      return json(route, answer.body, answer.status)
    }
  )

  // Activity detail: 404 for an unknown trace or a trace of another project.
  await page.route(
    (url) => /^\/api\/v1\/projects\/[0-9a-f-]{36}\/traces\/[^/]+$/.test(url.pathname),
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      const url = new URL(route.request().url())
      const access = readableProject(url, "traces.read")
      if (!access.ok) return empty(route, access.status)
      const traceId = decodeURIComponent(url.pathname.split("/").pop() ?? "")
      recordTraceDetailRequest(traceId)
      const failure = traceDetailFailureMessage(traceId)
      if (failure !== null) return json(route, { detail: failure }, 500)
      const detail = projectTraceDetail(access.project.id, traceId)
      if (detail === null) return json(route, { detail: "Trace not found" }, 404)
      return json(route, detail)
    }
  )

  // Project usage and the project dashboard share one wire shape.
  await page.route(
    (url) => /^\/api\/v1\/projects\/[0-9a-f-]{36}\/(usage|dashboard)$/.test(url.pathname),
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      const url = new URL(route.request().url())
      const access = readableProject(url, "usage.read")
      if (!access.ok) return empty(route, access.status)
      projectReadTraffic.push(url.pathname)
      return json(route, projectUsage(access.project.id, url.searchParams))
    }
  )

  // Project provider view (effective operations per provider type).
  await page.route(
    (url) => /^\/api\/v1\/projects\/[0-9a-f-]{36}\/providers$/.test(url.pathname),
    (route) => {
      if (route.request().method() !== "GET") return route.fallback()
      const url = new URL(route.request().url())
      const access = readableProject(url, "providers.read")
      if (!access.ok) return empty(route, access.status)
      projectReadTraffic.push(url.pathname)
      return json(route, projectProviders(access.project.id))
    }
  )

  // U3 provider configuration: credentials, bindings, settings and copy, and
  // the system credential, pool and allocation routes (providerConfigStub.ts).
  await installProviderConfigRoutes(page, {
    access(projectId) {
      const project = state.projects.find((p) => p.id === projectId) ?? null
      const member = project === null ? null : memberOf(project)
      if (project === null || member === null) return null
      return { id: project.id, name: project.name, permissions: permissionsOf(member) }
    },
    systemPermissions: () => [...state.systemPermissions],
  })
}

/** Paths of the project usage, dashboard and provider reads, in order. */
export const projectReadTraffic: string[] = []
