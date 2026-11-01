/**
 * Application route table. Workspace route identifiers and the project
 * section registry live here in app routing, not in the visual Sidebar
 * component. The legacy `/providers` redirect stays verbatim in
 * DashboardShell's Routes table so its target is pinned exactly once.
 *
 * One permission helper serves both the navigation filter and the route gate,
 * so a hidden link and a rejected direct URL can never disagree. Every gate
 * reads an effective-permission descriptor from the API, never a role.
 */
import { PROJECT_PERMISSIONS, SYSTEM_PERMISSIONS, hasPermission } from "@/domains/projects"
import type { PermissionAccess } from "@/domains/projects"

export type TabId =
  | "routing"
  | "quotas"
  | "settings"
  | "projects"
  | "account"
  | "adminUsers"

export const TAB_PATHS: Record<TabId, string> = {
  routing: "/routing",
  quotas: "/usage",
  settings: "/settings",
  projects: "/projects",
  account: "/account",
  adminUsers: "/admin/users",
}

/** Public account routes. They stay outside the protected workspace. */
export const LOGIN_PATH = "/login"
export const REGISTER_PATH = "/register"

/** Workspace entry: it resolves to the last valid project, else the list. */
export const WORKSPACE_ENTRY_PATH = "/"

/** Projects overview route of the workspace. */
export const PROJECTS_PATH = TAB_PATHS.projects

export interface WorkspaceRoute {
  id: TabId
  path: string
}

export const workspaceRoutes: WorkspaceRoute[] = [
  { id: "routing", path: TAB_PATHS.routing },
  { id: "quotas", path: TAB_PATHS.quotas },
  { id: "settings", path: TAB_PATHS.settings },
  { id: "projects", path: TAB_PATHS.projects },
  { id: "account", path: TAB_PATHS.account },
  { id: "adminUsers", path: TAB_PATHS.adminUsers },
]

/**
 * System permission each global route needs; `null` means always open.
 *
 * Routing, usage and settings read the global control plane, which the
 * backend gates on `system.settings.read`. Account provisioning needs
 * `system.settings.write`. Playground and activity live under projects.
 */
const ROUTE_PERMISSIONS: Record<TabId, string | null> = {
  projects: null,
  account: null,
  routing: SYSTEM_PERMISSIONS.settingsRead,
  quotas: SYSTEM_PERMISSIONS.settingsRead,
  settings: SYSTEM_PERMISSIONS.settingsRead,
  adminUsers: SYSTEM_PERMISSIONS.settingsWrite,
}

/** Return whether one global route waits for the system access descriptor. */
export function isGatedRoute(id: TabId): boolean {
  return ROUTE_PERMISSIONS[id] !== null
}

/** Return whether the system access descriptor opens one global route. */
export function canAccessRoute(
  id: TabId,
  systemAccess: PermissionAccess | null | undefined
): boolean {
  const permission = ROUTE_PERMISSIONS[id]
  return permission === null || hasPermission(systemAccess, permission)
}

/** Identifier of one project-scoped section. U3 extends this union. */
export type ProjectSectionId =
  | "overview"
  | "playground"
  | "activity"
  | "usage"
  | "members"
  | "apiKeys"

/** One entry of the project section registry. */
export interface ProjectSection {
  id: ProjectSectionId
  /** Path segment under `/p/:projectId`; `""` is the overview. */
  segment: string
  /** Sidebar label and accessible name of the section link. */
  label: string
  /**
   * Project permissions that open the section, any of them (any-of), from the
   * project access descriptor.
   */
  permissions: readonly string[]
}

/** Project section registry, in sidebar order. */
export const PROJECT_SECTIONS: readonly ProjectSection[] = [
  { id: "overview", segment: "", label: "Overview", permissions: [PROJECT_PERMISSIONS.read] },
  {
    id: "playground",
    segment: "playground",
    label: "Playground",
    permissions: [PROJECT_PERMISSIONS.searchExecute, PROJECT_PERMISSIONS.fetchExecute],
  },
  {
    id: "activity",
    segment: "activity",
    label: "Activity",
    permissions: [PROJECT_PERMISSIONS.tracesRead],
  },
  { id: "usage", segment: "usage", label: "Usage", permissions: [PROJECT_PERMISSIONS.usageRead] },
  {
    id: "members",
    segment: "members",
    label: "Members",
    permissions: [PROJECT_PERMISSIONS.membersRead],
  },
  {
    id: "apiKeys",
    segment: "api-keys",
    label: "API keys",
    permissions: [PROJECT_PERMISSIONS.tokensManage],
  },
]

/**
 * Former global paths of sections that moved under projects. Each one
 * redirects to the same section of the validated last project.
 */
export const LEGACY_SECTION_PATHS: Readonly<Record<string, ProjectSectionId>> = {
  "/playground": "playground",
  "/activity": "activity",
}

const PROJECT_UUID_RE =
  /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

const PROJECT_PREFIX_RE = /^\/p\/([^/]+)(?:\/(.*))?$/

function sectionBySegment(segment: string): ProjectSection | undefined {
  return PROJECT_SECTIONS.find((section) => section.segment === segment)
}

/** Return the workspace path of one project at one registered section. */
export function projectPath(projectId: string, section: ProjectSectionId = "overview"): string {
  const segment = PROJECT_SECTIONS.find((entry) => entry.id === section)?.segment ?? ""
  return segment === "" ? `/p/${projectId}` : `/p/${projectId}/${segment}`
}

/** Return the project id of any `/p/:projectId/...` path, or `null`. */
export function projectIdFromPath(pathname: string): string | null {
  const id = PROJECT_PREFIX_RE.exec(pathname)?.[1]
  return id === undefined || id === "" ? null : id
}

/** Return the project and the registered section of a path, or `null`. */
export function parseProjectPath(
  pathname: string
): { projectId: string; section: ProjectSectionId } | null {
  const match = PROJECT_PREFIX_RE.exec(pathname)
  const projectId = match?.[1]
  if (match === null || projectId === undefined) return null
  const section = sectionBySegment(match[2] ?? "")
  return section === undefined ? null : { projectId, section: section.id }
}

/** Return whether the project access descriptor opens one project section. */
export function canAccessProjectSection(
  id: ProjectSectionId,
  access: PermissionAccess | null | undefined
): boolean {
  const section = PROJECT_SECTIONS.find((entry) => entry.id === id)
  return (
    section !== undefined &&
    section.permissions.some((permission) => hasPermission(access, permission))
  )
}

/**
 * Return whether a return destination belongs to the current route set.
 *
 * A relative path, an unknown path, a protocol-relative URL, and an absolute
 * URL are all rejected, so a login link can never forward the browser to
 * another origin. A project path must name a UUID and a registered section.
 */
export function isInternalPath(value: string | null | undefined): value is string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return false
  if (Object.values(TAB_PATHS).includes(value)) return true
  if (Object.keys(LEGACY_SECTION_PATHS).includes(value)) return true
  const parsed = parseProjectPath(value)
  return parsed !== null && PROJECT_UUID_RE.test(parsed.projectId)
}

/** Return the login URL that remembers one internal destination, or login. */
export function loginPathFor(pathname: string): string {
  if (!isInternalPath(pathname)) return LOGIN_PATH
  return `${LOGIN_PATH}?returnTo=${encodeURIComponent(pathname)}`
}

/** Return the destination of a validated `returnTo` value, or the workspace entry. */
export function returnDestination(value: string | null | undefined): string {
  return isInternalPath(value) ? value : WORKSPACE_ENTRY_PATH
}
