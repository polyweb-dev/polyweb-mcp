import type { Page, Route } from "@playwright/test"

/**
 * In-memory projects backend for project-shell scenarios.
 *
 * The state lives at module level so two tabs of one browser context share it.
 * Permissions are computed from a fixture role table (test-side only), which
 * mirrors the backend's live-assignment semantics without duplicating them in
 * the app.
 */

const ALPHA_ID = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
const BETA_ID = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
const USER_ID = "33333333-3333-4333-8333-333333333333"

const ROLE_PERMISSIONS: Record<string, string[]> = {
  project_admin: [
    "project.read",
    "members.read",
    "members.manage",
    "roles.assign",
    "settings.read",
    "search.execute",
  ],
  project_member: ["project.read", "members.read", "search.execute"],
  routing_editor: ["project.read", "routing.write"],
}

interface StubMember {
  user_id: string
  email: string
  status: "active" | "suspended"
  roles: string[]
  version: number
}

interface StubProject {
  id: string
  name: string
  status: "active" | "archived"
  members: StubMember[]
}

interface ProjectStubState {
  /** Email of the signed-in account; empty means no memberships resolve. */
  userEmail: string
  /** System-scope permission list of the signed-in account. */
  systemPermissions: string[]
  projects: StubProject[]
  /** Delay in ms applied to the Alpha members read (rapid-switch scenario). */
  alphaMembersDelayMs: number
}

const state: ProjectStubState = {
  userEmail: "",
  systemPermissions: [],
  projects: [],
  alphaMembersDelayMs: 0,
}

export function resetProjectStub(): void {
  state.userEmail = ""
  state.systemPermissions = []
  state.alphaMembersDelayMs = 0
  state.projects = [
    {
      id: ALPHA_ID,
      name: "Alpha",
      status: "active",
      members: [
        { user_id: USER_ID, email: "", status: "active", roles: ["project_member"], version: 1 },
        {
          user_id: "44444444-4444-4444-8444-444444444444",
          email: "alpha-peer@example.com",
          status: "active",
          roles: ["project_member"],
          version: 1,
        },
      ],
    },
    { id: BETA_ID, name: "Beta", status: "active", members: [] },
  ]
}

/** Point the stub at one signed-in account email and its system permissions. */
export function setProjectStubAccount(email: string, systemPermissions: string[] = []): void {
  state.userEmail = email
  state.systemPermissions = systemPermissions
  for (const project of state.projects) {
    for (const member of project.members) {
      if (member.email === "") member.email = email
    }
  }
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

/**
 * Install the project routes after the default backend stub so they override
 * its 404 answers for every tab that registers them.
 */
export async function installProjectStub(page: Page): Promise<void> {
  await page.unroute((url) => url.pathname === "/api/v1/system/access").catch(() => {})
  await page
    .unroute(
      (url) =>
        url.pathname === "/api/v1/projects" || url.pathname.startsWith("/api/v1/projects/")
    )
    .catch(() => {})

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

  await page.route((url) => url.pathname === "/api/v1/projects", (route) => {
    const method = route.request().method()
    if (method === "GET") {
      const readable = state.projects.filter((p) => memberOf(p) !== null)
      return json(route, readable.map(projectWire))
    }
    if (method === "POST") {
      if (!state.systemPermissions.includes("project.create")) {
        return json(route, {}, 403)
      }
      const body = JSON.parse(route.request().postData() ?? "{}") as Record<string, unknown>
      const email = typeof body.initial_admin_email === "string" ? body.initial_admin_email : ""
      if (email.trim().toLowerCase() !== state.userEmail) {
        return json(route, {}, 400)
      }
      const created: StubProject = {
        id: "cccccccc-3333-4333-8333-cccccccccccc",
        name: String(body.name ?? "New project"),
        status: "active",
        members: [
          { user_id: USER_ID, email: state.userEmail, status: "active", roles: ["project_admin"], version: 1 },
        ],
      }
      state.projects.push(created)
      return json(route, projectWire(created), 201)
    }
    return route.fallback()
  })

  await page.route(
    (url) => /^\/api\/v1\/projects\/[0-9a-f-]{36}\/access$/.test(url.pathname),
    (route) => {
      const url = new URL(route.request().url())
      const project = projectOf(url)
      const member = project === null ? null : memberOf(project)
      if (project === null || member === null) return json(route, {}, 404)
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
      if (project === null || member === null) return json(route, {}, 404)
      if (!permissionsOf(member).includes("members.read")) return json(route, {}, 403)
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
}
