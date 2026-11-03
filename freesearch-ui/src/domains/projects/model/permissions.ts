/**
 * Effective-permission names the web client gates on.
 *
 * The names mirror the backend action catalog. The UI asks whether the live
 * access descriptor holds one of them; it never maps a role to permissions.
 */
import { hasPermission } from "./types"
import type { PermissionAccess } from "./types"

/** System-scope actions. */
export const SYSTEM_PERMISSIONS = {
  settingsRead: "system.settings.read",
  settingsWrite: "system.settings.write",
  /** Backend gate of `POST /api/v1/projects` (system-scoped). */
  projectCreate: "project.create",
  /** System-owned provider credentials and their project grants. */
  credentialsManage: "system.credentials.manage",
  /** Upstream quota pools and their credential links. */
  poolsManage: "system.pools.manage",
  /** Per-project allocations of shared pools. */
  allocationsManage: "system.allocations.manage",
} as const

/** Project-scope actions. */
export const PROJECT_PERMISSIONS = {
  read: "project.read",
  membersRead: "members.read",
  membersManage: "members.manage",
  rolesAssign: "roles.assign",
  tokensManage: "tokens.manage",
  searchExecute: "search.execute",
  fetchExecute: "fetch.execute",
  tracesRead: "traces.read",
  usageRead: "usage.read",
  providersRead: "providers.read",
  providersConfigure: "providers.configure",
  credentialsManagePrivate: "credentials.manage_private",
  settingsRead: "settings.read",
  settingsWrite: "settings.write",
  settingsCopy: "settings.copy",
} as const

/**
 * Return whether the system access lets the caller create projects.
 *
 * It mirrors the backend gate exactly: `POST /api/v1/projects` checks the
 * system-scoped `project.create`, so only that permission shows the form.
 */
export function canCreateProjects(systemAccess: PermissionAccess | null | undefined): boolean {
  return hasPermission(systemAccess, SYSTEM_PERMISSIONS.projectCreate)
}
