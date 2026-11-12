/**
 * Generic contact identity primitives.
 *
 * Business-agnostic: no domain or feature imports. The full personal name
 * wins, then the username, then the email. The email stays as the contact and
 * disambiguation line. Views never rename entities and never change access.
 */

export interface IdentityProfile {
  username?: string | null
  first_name?: string | null
  last_name?: string | null
}

export interface ContactIdentity extends IdentityProfile {
  email: string
}

function cleanPart(value: string | null | undefined): string | null {
  if (typeof value !== "string") return null
  const trimmed = value.trim()
  return trimmed === "" ? null : trimmed
}

/** Full personal name of one identity, or `null` when none is available. */
export function fullNameFromProfile(profile: IdentityProfile): string | null {
  const parts = [cleanPart(profile.first_name), cleanPart(profile.last_name)].filter(
    (part): part is string => part !== null
  )
  return parts.length > 0 ? parts.join(" ") : null
}

/**
 * Primary display name of one identity, or `null` when it has none.
 *
 * The full name wins over the username; callers fall back to the email.
 */
export function displayNameFromProfile(profile: IdentityProfile): string | null {
  const fullName = fullNameFromProfile(profile)
  if (fullName !== null) return fullName
  return cleanPart(profile.username)
}

/** Primary identity label: the display name when present, else the email. */
export function identityLabel(identity: ContactIdentity): string {
  return displayNameFromProfile(identity) ?? identity.email
}

/**
 * Identity with contact detail: `Display (email)` when a display name
 * exists, else the email alone. Keeps the email for disambiguation.
 */
export function identityDetailLabel(identity: ContactIdentity): string {
  const display = displayNameFromProfile(identity)
  return display === null ? identity.email : `${display} (${identity.email})`
}

/** One letter of the text avatar: the display name's, else the email's. */
export function identityInitial(displayName: string | null, email: string): string {
  return (displayName ?? email).trim().slice(0, 1).toUpperCase() || "?"
}

/**
 * Trace actor attribution text: the human display name with email only when
 * it disambiguates, or the raw email. `null` keeps legacy/unknown callers
 * quiet; API-key rows never claim a name and are labelled separately.
 */
export function traceActorLabel(actor: {
  displayName: string | null
  email: string | null
}): string | null {
  if (actor.displayName !== null) {
    return actor.email !== null && actor.email !== actor.displayName
      ? `${actor.displayName} (${actor.email})`
      : actor.displayName
  }
  return actor.email
}
