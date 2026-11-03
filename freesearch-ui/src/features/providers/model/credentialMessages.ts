import { isConflict, isForbidden } from "@/shared/api/conflict"

export const ROTATE_CONFLICT_MESSAGE = "This key changed since you opened it. Reload and try again."
export const PERMISSION_DENIED_MESSAGE = "You do not have permission to make this change."
export const SAVE_FAILED_MESSAGE = "The key could not be saved."
export const ROTATE_FAILED_MESSAGE = "The key could not be rotated."
export const DELETE_FAILED_MESSAGE = "The key could not be deleted."
export const DISCONNECT_FAILED_MESSAGE = "The connection could not be removed."

/** Notice after a saved key; it names the label, never the key. */
export function keySavedNotice(label: string): string {
  return `Key saved for ${label}.`
}

/**
 * Safe text of one failed credential mutation.
 *
 * Server details are never shown for these requests: a validation answer
 * could echo request input, and a create or rotate request carries a secret.
 */
export function credentialFailureMessage(error: unknown, fallback: string, rotate = false): string {
  if (rotate && isConflict(error)) return ROTATE_CONFLICT_MESSAGE
  if (isForbidden(error)) return PERMISSION_DENIED_MESSAGE
  return fallback
}
