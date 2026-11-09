/**
 * Effective-permission capabilities of the workspace.
 *
 * Every flag reads the live system access descriptor of
 * `GET /api/v1/system/access`, never an account role. The backend accepts a
 * control-plane read with `system.settings.read` and a mutation or an account
 * provisioning with `system.settings.write`. The composition passes the flags
 * into the domain providers, so a domain never imports the auth domain and
 * every call site shares one policy.
 */
import { SYSTEM_PERMISSIONS, hasPermission } from "@/domains/projects"
import type { PermissionAccess } from "@/domains/projects"

type SystemAccessLike = PermissionAccess | null | undefined

/** Return whether the caller may read the global control plane. */
export function canReadControls(systemAccess: SystemAccessLike): boolean {
  return hasPermission(systemAccess, SYSTEM_PERMISSIONS.settingsRead)
}

/** Return whether the caller may mutate the global control plane. */
export function canEditControls(systemAccess: SystemAccessLike): boolean {
  return hasPermission(systemAccess, SYSTEM_PERMISSIONS.settingsWrite)
}
