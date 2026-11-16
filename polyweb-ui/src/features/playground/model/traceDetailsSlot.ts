import type { ReactNode } from "react"
import type { SearchTraceRef } from "@/domains/execution"

/**
 * What the Playground hands the trace inspector: the trace of the search the
 * user opened (fixed at click time), or why it has none.
 */
export type TraceDetailsRequest = SearchTraceRef & { onClose: () => void }

/**
 * Composition slot for the project trace inspector. The Activity feature owns
 * the inspector, so the app shell supplies it; the Playground never imports
 * another feature.
 */
export type RenderTraceDetails = (request: TraceDetailsRequest) => ReactNode
