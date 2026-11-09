/**
 * Time display and row order of the audit trail.
 *
 * Every instant becomes reader-locale text here, so no raw ISO string reaches
 * the UI, and the newest event of the loaded history stays at the top. The
 * stored values never change; only the shown text and the shown order change.
 */

import type { LimitAuditEvent } from "@/domains/dashboard"

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

/** Reader-locale text of one instant; an unreadable value stays verbatim. */
export function timeText(value: string | null | undefined): string {
  if (value === null || value === undefined) return ""
  const text = value.trim()
  if (text === "") return ""
  const date = new Date(text)
  return Number.isNaN(date.getTime()) ? text : date.toLocaleString()
}

/**
 * Reader-locale date of one instant or one calendar date. A calendar date
 * keeps its own day, because a UTC midnight shift can move it one day back.
 */
export function dateText(value: string | null | undefined): string {
  if (value === null || value === undefined) return ""
  const text = value.trim()
  if (text === "") return ""
  const date = new Date(DATE_ONLY.test(text) ? text + "T00:00:00" : text)
  return Number.isNaN(date.getTime()) ? text : date.toLocaleDateString()
}

/** Reader-locale text of one optional instant; an absent value yields null. */
export function timestampOrNull(value: string | null | undefined): string | null {
  const text = timeText(value)
  return text === "" ? null : text
}

/** Epoch milliseconds of one instant; an unreadable value sorts last. */
function instant(iso: string): number {
  const time = new Date(iso).getTime()
  return Number.isNaN(time) ? Number.NEGATIVE_INFINITY : time
}

/** The same events with the newest observed row first, older pages below it. */
export function newestFirst(events: LimitAuditEvent[]): LimitAuditEvent[] {
  return [...events].sort((left, right) => instant(right.observed_at) - instant(left.observed_at))
}
