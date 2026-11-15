import type { ReactNode } from "react"

/** What the Playground hands the trace inspector for the call it just made. */
export interface TraceDetailsRequest {
  /** Trace of the call; null when the backend sent no `X-Trace-Id`. */
  traceId: string | null
  onClose: () => void
}

/**
 * Composition slot for the project trace inspector. The Activity feature owns
 * the inspector, so the app shell supplies it; the Playground never imports
 * another feature.
 */
export type RenderTraceDetails = (request: TraceDetailsRequest) => ReactNode
