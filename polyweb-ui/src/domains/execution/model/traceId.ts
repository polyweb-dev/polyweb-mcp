const TRACE_ID_PATTERN = /^[0-9a-f]{32}$/

/** Whether `value` is a well-formed trace id: 32 lowercase hex characters. */
export function isTraceId(value: unknown): value is string {
  return typeof value === "string" && TRACE_ID_PATTERN.test(value)
}

/** Why a search result has no trace to open. */
export type TraceUnavailableReason = "not_recorded" | "not_saved"

/** The trace of a search result, or why there is none. */
export type SearchTraceRef =
  | { traceId: string }
  | { traceId: null; reason: TraceUnavailableReason }

/**
 * The trace a stored search result links to. A result saved before the field
 * existed has no `traceId` key at all (`not_saved`); a result whose response
 * carried no well-formed `X-Trace-Id` stores `null` (`not_recorded`).
 */
export function searchTraceRef(search: { traceId?: unknown }): SearchTraceRef {
  if (isTraceId(search.traceId)) return { traceId: search.traceId }
  return { traceId: null, reason: search.traceId === undefined ? "not_saved" : "not_recorded" }
}
