/**
 * Application route table. Workspace route identifiers live here in app
 * routing, not in the visual Sidebar component. Redirects (root, legacy
 * /providers, unknown paths) stay verbatim in DashboardShell's Routes
 * table so the legacy targets are pinned exactly once.
 *
 * One permission helper serves both the navigation filter and the route gate,
 * so a hidden link and a rejected direct URL can never disagree.
 */
import type { UserRole } from "@/domains/auth"

export type TabId =
  | "playground"
  | "routing"
  | "quotas"
  | "activity"
  | "settings"
  | "account"
  | "adminUsers"

export const TAB_PATHS: Record<TabId, string> = {
  playground: "/playground",
  routing: "/routing",
  quotas: "/usage",
  activity: "/activity",
  settings: "/settings",
  account: "/account",
  adminUsers: "/admin/users",
}

/** Public account routes. They stay outside the protected workspace. */
export const LOGIN_PATH = "/login"
export const REGISTER_PATH = "/register"

export interface WorkspaceRoute {
  id: TabId
  path: string
}

export const workspaceRoutes: WorkspaceRoute[] = [
  { id: "playground", path: TAB_PATHS.playground },
  { id: "routing", path: TAB_PATHS.routing },
  { id: "quotas", path: TAB_PATHS.quotas },
  { id: "activity", path: TAB_PATHS.activity },
  { id: "settings", path: TAB_PATHS.settings },
  { id: "account", path: TAB_PATHS.account },
  { id: "adminUsers", path: TAB_PATHS.adminUsers },
]

/**
 * Roles allowed on each workspace route. These permissions preserve the shipped
 * backend policy: an Agent cannot read provider controls or routing policy, and
 * only an Admin reaches the role control screen.
 */
const ROUTE_ROLES: Record<TabId, readonly UserRole[]> = {
  playground: ["admin", "developer", "agent"],
  activity: ["admin", "developer", "agent"],
  account: ["admin", "developer", "agent"],
  routing: ["admin", "developer"],
  quotas: ["admin", "developer"],
  settings: ["admin", "developer"],
  adminUsers: ["admin"],
}

/** Return whether one role may open one workspace route. */
export function canAccessRoute(id: TabId, role: UserRole): boolean {
  return ROUTE_ROLES[id].includes(role)
}

/**
 * Return whether a return destination belongs to the current route set.
 *
 * A relative path, an unknown path, a protocol-relative URL, and an absolute
 * URL are all rejected, so a login link can never forward the browser to
 * another origin.
 */
export function isInternalPath(value: string | null | undefined): value is string {
  if (!value || !value.startsWith("/") || value.startsWith("//")) return false
  return Object.values(TAB_PATHS).includes(value)
}

/** Return the login URL that remembers one internal destination, or login. */
export function loginPathFor(pathname: string): string {
  if (!isInternalPath(pathname)) return LOGIN_PATH
  return `${LOGIN_PATH}?returnTo=${encodeURIComponent(pathname)}`
}

/** Return the destination of a validated `returnTo` value, or the playground. */
export function returnDestination(value: string | null | undefined): string {
  return isInternalPath(value) ? value : TAB_PATHS.playground
}
