/**
 * Project domain contracts of the browser client.
 *
 * The UI renders affordances from these effective backend permissions only;
 * it never duplicates the backend role-to-permission table.
 */

/** Lifecycle rollout state of the projects surface. */
export type ProjectRolloutState = "preview" | "strict" | "fair"

/** Lifecycle state of one project. */
export type ProjectStatus = "active" | "archived"

/** Membership lifecycle state. */
export type MembershipStatus = "active" | "suspended"

/** Built-in project-scoped role keys of the backend contract. */
export type ProjectRoleKey =
  | "project_admin"
  | "project_member"
  | "routing_editor"
  | "provider_editor"
  | "token_manager"

/** Every project role key, in display order, for role controls. */
const PROJECT_ROLE_KEYS: readonly ProjectRoleKey[] = [
  "project_admin",
  "project_member",
  "routing_editor",
  "provider_editor",
  "token_manager",
]

/** Safe projection of one project record. */
export interface Project {
  id: string
  account_id: string
  name: string
  slug: string
  status: ProjectStatus
  created_by: string
  created_at: string
  version: number
}

/** Live system-scope access descriptor of the signed-in account. */
export interface SystemAccess {
  rollout_state: ProjectRolloutState
  permissions: string[]
}

/** Live project-scope access descriptor of the signed-in account. */
export interface ProjectAccess {
  project_id: string
  permissions: string[]
  roles: string[]
  policy_revision: number
}

/** Safe projection of one project membership record. */
export interface ProjectMember {
  project_id: string
  user_id: string
  email: string
  status: MembershipStatus
  roles: string[]
  role: "admin" | "developer"
  permissions: number
  provider_owner: boolean
  account_active: boolean
  version: number
}

/** Return whether an unknown value is one of the built-in project role keys. */
export function isProjectRoleKey(value: unknown): value is ProjectRoleKey {
  return typeof value === "string" && (PROJECT_ROLE_KEYS as readonly string[]).includes(value)
}

/** Permission-bearing surface: anything that carries a permission list. */
export interface PermissionAccess {
  permissions: readonly string[]
}

/** Return whether an access descriptor grants one catalog action. */
export function hasPermission(
  access: PermissionAccess | null | undefined,
  action: string
): boolean {
  return access !== null && access !== undefined && access.permissions.includes(action)
}
