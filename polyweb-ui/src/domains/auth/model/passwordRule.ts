/**
 * Password length rule of the backend user manager.
 *
 * Registration and account provisioning check the length before they send a
 * request, with the same copy, so a user sees one rule everywhere. The server
 * stays authoritative for the full password policy.
 */

export const MIN_PASSWORD_LENGTH = 12
export const MAX_PASSWORD_LENGTH = 128

/** Hint shown under every new-password field. */
export const PASSWORD_HINT = `Use ${MIN_PASSWORD_LENGTH} to ${MAX_PASSWORD_LENGTH} characters.`

/** Return the length problem of one password, or `null` when it fits the rule. */
export function passwordLengthProblem(password: string): string | null {
  if (password.length < MIN_PASSWORD_LENGTH) {
    return `Use at least ${MIN_PASSWORD_LENGTH} characters for the password.`
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    return `Use no more than ${MAX_PASSWORD_LENGTH} characters for the password.`
  }
  return null
}
