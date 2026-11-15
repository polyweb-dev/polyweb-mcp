/**
 * Generic person identity primitives.
 *
 * Business-agnostic: no domain or feature imports. The full personal name
 * wins, then the username. Email privacy: `identityLabel` NEVER falls back to
 * an email; it ends in a neutral label instead. Only the two places that may
 * show an email (the sidebar account popup and the project Members page) use
 * the `Contact` helpers below, which take an explicit email.
 */

export interface IdentityProfile {
  username?: string | null
  first_name?: string | null
  last_name?: string | null
}

/** A profile that also carries an email; only email-allowed views build one. */
export interface ContactIdentity extends IdentityProfile {
  email: string
}

/** Neutral label of a person who has neither a name nor a username. */
export const UNKNOWN_USER_LABEL = "Unknown user"

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

/** Primary display name of one identity (full name, else username), or `null`. */
export function displayNameFromProfile(profile: IdentityProfile): string | null {
  const fullName = fullNameFromProfile(profile)
  if (fullName !== null) return fullName
  return cleanPart(profile.username)
}

/**
 * Display label of a person anywhere an email must not appear: the full name,
 * else the username, else `Unknown user`. Never an email, even when the
 * profile object happens to carry one.
 */
export function identityLabel(profile: IdentityProfile): string {
  return displayNameFromProfile(profile) ?? UNKNOWN_USER_LABEL
}

/**
 * Email-allowed contact label (Members page, account popup): the display name
 * when present, else the email.
 */
export function contactLabel(identity: ContactIdentity): string {
  return displayNameFromProfile(identity) ?? identity.email
}

/**
 * Email-allowed contact detail (Members page, account popup): `Display
 * (email)` when a display name exists, else the email alone.
 */
export function identityDetailLabel(identity: ContactIdentity): string {
  const display = displayNameFromProfile(identity)
  return display === null ? identity.email : `${display} (${identity.email})`
}

/** One letter of the text avatar: the display name's, else the email's. */
export function identityInitial(displayName: string | null, email: string): string {
  return (displayName ?? email).trim().slice(0, 1).toUpperCase() || "?"
}
