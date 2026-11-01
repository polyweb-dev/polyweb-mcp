import type {
  Project,
  ProjectAccess,
  ProjectApiKey,
  ProjectScopeContextValue,
  ProjectsContextValue,
  SystemAccess,
} from "@/domains/projects"
import { ADMIN_ACCOUNT_ID, DEVELOPER_ACCOUNT_ID } from "./authFixtures"
import { err, ok } from "./fetchMock"
import type { RecordedRequest } from "./fetchMock"

/**
 * Effective-permission fixtures of the projects-first access model.
 *
 * Tests grant authority through these descriptors only, exactly as the
 * backend does through `GET /api/v1/system/access` and
 * `GET /api/v1/projects/{id}/access`. No fixture carries a role label that
 * the UI could gate on.
 */

/** System permissions of the built-in system administrator. */
export const SYSTEM_ADMIN_PERMISSIONS: readonly string[] = [
  "project.create",
  "system.settings.read",
  "system.settings.write",
  "system.credentials.manage",
  "system.pools.manage",
  "system.allocations.manage",
  "system.projects.create",
  "system.audit.read",
  "system.roles.assign",
]

/** A caller who may read the global control plane but not change it. */
export const SETTINGS_READER_PERMISSIONS: readonly string[] = ["system.settings.read"]

/** Project permissions of the built-in project administrator. */
export const PROJECT_ADMIN_PERMISSIONS: readonly string[] = [
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
]

/** Project permissions of the built-in project member. */
export const PROJECT_MEMBER_PERMISSIONS: readonly string[] = [
  "project.read",
  "members.read",
  "settings.read",
  "providers.read",
  "traces.read",
  "usage.read",
  "search.execute",
  "fetch.execute",
]

export const PROJECT_ALPHA_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
export const PROJECT_BETA_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"

/** Build one system access descriptor. */
export function systemAccessFixture(
  permissions: readonly string[] = SYSTEM_ADMIN_PERMISSIONS
): SystemAccess {
  return { rollout_state: "preview", permissions: [...permissions] }
}

/** Build one project projection. */
export function projectFixture(overrides?: Partial<Project>): Project {
  return {
    id: PROJECT_ALPHA_ID,
    account_id: "00000000-0000-4000-8000-000000000001",
    name: "Alpha",
    slug: "alpha",
    status: "active",
    created_by: "11111111-1111-4111-8111-111111111111",
    created_at: "2026-10-01T00:00:00Z",
    version: 1,
    ...overrides,
  }
}

/** Build one project access descriptor. */
export function projectAccessFixture(
  projectId: string = PROJECT_ALPHA_ID,
  permissions: readonly string[] = PROJECT_ADMIN_PERMISSIONS
): ProjectAccess {
  return {
    project_id: projectId,
    permissions: [...permissions],
    roles: [],
    policy_revision: 1,
  }
}

/** Build one ready project scope with the given effective permissions. */
export function projectScopeValue(
  projectId: string = PROJECT_ALPHA_ID,
  permissions: readonly string[] = PROJECT_ADMIN_PERMISSIONS
): ProjectScopeContextValue {
  return {
    projectId,
    project: null,
    accessState: { status: "ready", data: projectAccessFixture(projectId, permissions) },
    refreshAccess: () => {},
  }
}

/** Build one API key metadata projection (no raw key). */
export function apiKeyFixture(overrides?: Partial<ProjectApiKey>): ProjectApiKey {
  return {
    id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
    project_id: PROJECT_ALPHA_ID,
    label: "CI runner",
    prefix: "fs_live_abcd",
    scopes: ["search.execute", "fetch.execute"],
    created_by: "11111111-1111-4111-8111-111111111111",
    created_at: "2026-10-02T10:00:00Z",
    expires_at: "2027-01-01T00:00:00Z",
    revoked_at: null,
    last_used_at: null,
    rotated_from_id: null,
    status: "active",
    ...overrides,
  }
}

/** Build one ready projects context value for components rendered standalone. */
export function projectsContextFixture(
  overrides?: Partial<ProjectsContextValue>
): ProjectsContextValue {
  return {
    accountId: "11111111-1111-4111-8111-111111111111",
    availability: "available",
    rolloutState: "preview",
    systemAccess: systemAccessFixture(),
    projects: [],
    reloadProjects: () => Promise.resolve([]),
    ...overrides,
  }
}

/** Options of the workspace access routes answered by `answerWorkspaceAccess`. */
export interface WorkspaceAccessOptions {
  systemPermissions?: readonly string[]
  projects?: readonly Project[]
  /** Project permissions keyed by project id; a missing id answers 404. */
  projectPermissions?: Readonly<Record<string, readonly string[]>>
}

/**
 * Answer the access routes of the workspace shell, or return `null`.
 *
 * Full-app tests call it first in their fetch handler, so the shell sees a
 * real system access descriptor and project list instead of a 404.
 */
export function answerWorkspaceAccess(
  req: RecordedRequest,
  options: WorkspaceAccessOptions = {}
): Response | null {
  if (req.method !== "GET") return null
  if (req.url === "/api/v1/system/access") {
    return ok(systemAccessFixture(options.systemPermissions ?? SYSTEM_ADMIN_PERMISSIONS))
  }
  if (req.url === "/api/v1/projects?include_archived=true") return ok(options.projects ?? [])
  const match = /^\/api\/v1\/projects\/([^/]+)\/access$/.exec(req.url)
  if (match === null) return null
  const projectId = match[1] ?? ""
  const permissions = options.projectPermissions?.[projectId]
  return permissions === undefined
    ? err(404, null)
    : ok(projectAccessFixture(projectId, permissions))
}

/**
 * System permissions of each account persona in shell tests: the admin
 * persona holds the system administrator permissions, the developer persona
 * reads settings only, and every other account holds none.
 */
export function personaSystemPermissions(account: { id: string } | null): readonly string[] {
  if (account?.id === ADMIN_ACCOUNT_ID) return SYSTEM_ADMIN_PERMISSIONS
  if (account?.id === DEVELOPER_ACCOUNT_ID) return SETTINGS_READER_PERMISSIONS
  return []
}
