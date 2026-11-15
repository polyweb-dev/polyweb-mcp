/**
 * Project member identity views.
 *
 * Members page only: the full personal name wins, then the username, then the
 * email, which stays as the contact and disambiguation line. Every other view
 * shows a person by display name only (see `identityLabel`), so the profile
 * projection below carries no email. Views never rename projects and never
 * change visibility or permissions.
 */
import type { ProjectMember } from "@/domains/projects"
import { contactLabel, identityDetailLabel } from "@/shared/lib/identity"
import type { ContactIdentity, IdentityProfile } from "@/shared/lib/identity"

/** One contact identity entry resolved from a project member record. */
export function identityFromMember(member: ProjectMember): ContactIdentity {
  return {
    email: member.email,
    username: member.username,
    first_name: member.first_name,
    last_name: member.last_name,
  }
}

/** The name-only projection of one member, for views that must not show an email. */
export function profileFromMember(member: ProjectMember): IdentityProfile {
  return {
    username: member.username,
    first_name: member.first_name,
    last_name: member.last_name,
  }
}

/** Sort key of one member: the display name when present, else the email. */
export function memberSortLabel(member: ProjectMember): string {
  return contactLabel(identityFromMember(member)).toLocaleLowerCase()
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


