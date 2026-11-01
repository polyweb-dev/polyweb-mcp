/**
 * Plain-language explanation of an absent trace payload.
 *
 * The project trace policy can store metadata only, or redact the results, so
 * the detail explains the absence from the trace itself; it never reads the
 * project settings.
 */
import type { TraceDetail } from "./types"

export const TRACE_METADATA_ONLY_MESSAGE =
  "This trace stored metadata only. The project's trace policy did not capture the query or the results."
export const TRACE_RESULTS_NOT_STORED_MESSAGE = "The results of this trace were not stored."
export const TRACE_NOT_IN_PROJECT_MESSAGE = "This trace is not available in this project."

/** Return the notice for an absent payload, or `null` when nothing is missing. */
export function tracePayloadNotice(
  trace: Pick<TraceDetail, "input" | "output" | "outcome">
): string | null {
  if (trace.input === null && trace.output === null) return TRACE_METADATA_ONLY_MESSAGE
  if (trace.output === null && trace.outcome === "success") return TRACE_RESULTS_NOT_STORED_MESSAGE
  return null
}
