/**
 * Role-less account fixtures and system permission sets for stubbed scenarios.
 *
 * The backend account carries no role and no privilege flag: GET /users/me
 * returns exactly the safe `UserAccount` projection below. Authority comes from
 * effective permissions instead: system permissions from
 * GET /api/v1/system/access and project permissions from
 * GET /api/v1/projects/{id}/access. Scenarios pick an account kind; the kind
 * fixes both the account body and its system permission list.
 */

/** Every system-scope action of the built-in system_admin role (backend catalog). */
export const SYSTEM_ADMIN_PERMISSIONS: readonly string[] = [
  "project.create",
  "system.allocations.manage",
  "system.audit.read",
  "system.credentials.manage",
  "system.pools.manage",
  "system.projects.create",
  "system.roles.assign",
  "system.settings.read",
  "system.settings.write",
]

/** Wire shape of GET /users/me, registration and POST /api/v1/users. */
export interface StubUserAccount {
  id: string
  email: string
  auth_provider: "local"
  auth_provider_id: null
  username: string | null
  first_name: string | null
  last_name: string | null
  is_active: boolean
  is_verified: boolean
}

/** Build one role-less account body; profile fields default to null. */
export function userAccountBody(
  id: string,
  email: string,
  profile: { username?: string | null; first_name?: string | null; last_name?: string | null } = {}
): StubUserAccount {
  return {
    id,
    email,
    auth_provider: "local",
    auth_provider_id: null,
    username: profile.username ?? null,
    first_name: profile.first_name ?? null,
    last_name: profile.last_name ?? null,
    is_active: true,
    is_verified: true,
  }
}

/**
 * Parse a Gherkin permission list: "none" is empty, otherwise a comma list,
 * "all system" expands to the system administrator set.
 */
export function parsePermissionList(value: string): string[] {
  const trimmed = value.trim()
  if (trimmed === "" || trimmed === "none") return []
  if (trimmed === "all system") return [...SYSTEM_ADMIN_PERMISSIONS]
  return trimmed
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item !== "")
}

/**
 * Former role labels that must never label an account (case-sensitive, so the
 * lower-case fixture username "admin" and emails do not match).
 */
export const ROLE_LABEL_PATTERN = /\b(Admin|Developer|Agent|Role)\b/
