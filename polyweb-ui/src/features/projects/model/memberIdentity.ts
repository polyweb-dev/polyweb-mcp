/**
 * Project member identity views.
 *
 * Member, owner, and pool-owner views resolve the same way via the shared
 * contact primitives: the full personal name wins, then the username, then
 * the email. The email stays as the contact and disambiguation line. Views
 * never rename projects and never change visibility or permissions.
 */
import type { ProjectMember } from "@/domains/projects"
import { identityDetailLabel, identityLabel } from "@/shared/lib/identity"
import type { ContactIdentity } from "@/shared/lib/identity"

/** One contact identity entry resolved from a project member record. */
export function identityFromMember(member: ProjectMember): ContactIdentity {
  return {
    email: member.email,
    username: member.username,
    first_name: member.first_name,
    last_name: member.last_name,
  }
}

/** Sort key of one member: the display name when present, else the email. */
export function memberSortLabel(member: ProjectMember): string {
  return identityLabel(identityFromMember(member)).toLocaleLowerCase()
}

/**
 * Member identity with contact detail: `Display (email)` when a display name
 * exists, else the email alone.
 */
export function memberDetailLabel(member: ProjectMember): string {
  return identityDetailLabel(identityFromMember(member))
}

/**
 * Accessible member action label: the display name when present, with the
 * email kept for disambiguation.
 */
export function memberActionLabel(member: ProjectMember): string {
  return memberDetailLabel(member)
}


