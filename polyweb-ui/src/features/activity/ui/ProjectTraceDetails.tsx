import { PROJECT_PERMISSIONS, hasPermission, useProjectScope } from "@/domains/projects"
import { useProjectTraceDetail } from "../model/useProjectTraceDetail"
import { TraceDetailDialog } from "./TraceDetailDialog"

export interface ProjectTraceDetailsProps {
  /** Trace of the call; null when the backend recorded none. */
  traceId: string | null
  onClose: () => void
}

/**
 * The Activity trace inspector for one known trace of the URL project, open
 * while mounted. Other screens (the Playground) open it for the call they
 * just made; a missing or metadata-only trace explains what is unavailable.
 */
export function ProjectTraceDetails({ traceId, onClose }: ProjectTraceDetailsProps) {
  const { projectId, accessState } = useProjectScope()
  const access = accessState.status === "ready" ? accessState.data : null
  const state = useProjectTraceDetail({
    projectId,
    traceId,
    canReadTraces: hasPermission(access, PROJECT_PERMISSIONS.tracesRead),
  })
  return (
    <TraceDetailDialog
      isOpen
      trace={state.detail}
      status={state.status === "idle" ? "loading" : state.status}
      error={state.error}
      onClose={onClose}
      onRetry={state.retry}
    />
  )
}
