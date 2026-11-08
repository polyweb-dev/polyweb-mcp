/**
 * Expiration choice of the issue form and the rotate dialog.
 *
 * `default` omits `expires_at` (90 days on issue, the current lifetime on
 * rotation), `never` sends an explicit `null`, and `custom` sends the end of
 * the chosen local day as an ISO timestamp, which must lie in the future.
 */
import type { ApiKeyExpiry } from "@/domains/projects"

export type ExpiryChoice = "default" | "never" | "custom"

export const PAST_EXPIRY_MESSAGE = "Choose an expiration date in the future"

export type ExpiryResult = { ok: true; expiry: ApiKeyExpiry } | { ok: false; message: string }

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/

/** Return the request expiry of one choice, or a validation message. */
export function toApiKeyExpiry(
  choice: ExpiryChoice,
  customDate: string,
  now: Date = new Date()
): ExpiryResult {
  if (choice === "default") return { ok: true, expiry: { kind: "default" } }
  if (choice === "never") return { ok: true, expiry: { kind: "never" } }
  if (!DATE_RE.test(customDate)) return { ok: false, message: PAST_EXPIRY_MESSAGE }
  const endOfDay = new Date(`${customDate}T23:59:59`)
  if (Number.isNaN(endOfDay.getTime()) || todayInputValue(endOfDay) !== customDate || endOfDay.getTime() <= now.getTime()) {
    return { ok: false, message: PAST_EXPIRY_MESSAGE }
  }
  return { ok: true, expiry: { kind: "at", isoTimestamp: endOfDay.toISOString() } }
}

/** Return today's local date as `YYYY-MM-DD`, the earliest custom date. */
export function todayInputValue(now: Date = new Date()): string {
  const month = String(now.getMonth() + 1).padStart(2, "0")
  const day = String(now.getDate()).padStart(2, "0")
  return `${now.getFullYear()}-${month}-${day}`
}
