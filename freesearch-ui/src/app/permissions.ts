/**
 * Role capabilities of the workspace.
 *
 * These flags mirror the shipped backend policy: the control plane accepts a
 * read from an Admin or a Developer, and a mutation from an Admin only. The
 * composition passes the flags into the domain providers, so a domain never
 * imports the auth domain and every call site shares one policy.
 */
import type { UserRole } from "@/domains/auth"

/** Roles allowed to read provider, routing, and dashboard control data. */
const CONTROL_READ_ROLES: readonly UserRole[] = ["admin", "developer"]

/** Roles allowed to mutate provider, routing, and quota control data. */
const CONTROL_EDIT_ROLES: readonly UserRole[] = ["admin"]

/** Return whether one role may read the control plane. */
export function canReadControls(role: UserRole): boolean {
  return CONTROL_READ_ROLES.includes(role)
}

/** Return whether one role may mutate the control plane. */
export function canEditControls(role: UserRole): boolean {
  return CONTROL_EDIT_ROLES.includes(role)
}
