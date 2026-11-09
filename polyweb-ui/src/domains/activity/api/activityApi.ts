/**
 * Project trace reads of the Activity screen.
 *
 * The project id in the path is the only ownership selector. Every call goes
 * through the shared transport and every payload is decoded from `unknown`.
 * A trace of another project, or an unknown one, answers 404.
 */
import { requestJson } from "@/shared/api/client"
import { ApiError } from "@/shared/api/http"
import { mapTraceDetail, mapTracePage } from "../model/mappers"
import type { TracePage } from "../model/mappers"
import type { TraceDetail, TraceOperation, TraceOutcome } from "../model/types"

/** Query of one list page; an omitted value asks for the backend default. */
export interface TraceListQuery {
  limit?: number
  operation?: TraceOperation
  outcome?: TraceOutcome
  cursor?: string
}

function tracesPath(projectId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/traces`
}

function withSignal(signal: AbortSignal | undefined): RequestInit {
  return signal === undefined ? {} : { signal }
}

/** Read one newest-first page of the project's trace summaries. */
export async function listProjectTraces(
  projectId: string,
  query: TraceListQuery = {},
  signal?: AbortSignal
): Promise<TracePage> {
  const params = new URLSearchParams()
  if (query.limit !== undefined) params.set("limit", String(query.limit))
  if (query.operation !== undefined) params.set("operation", query.operation)
  if (query.outcome !== undefined) params.set("outcome", query.outcome)
  if (query.cursor !== undefined) params.set("cursor", query.cursor)
  const search = params.toString()
  const path = `${tracesPath(projectId)}${search ? `?${search}` : ""}`
  return mapTracePage(await requestJson<unknown>(path, withSignal(signal)))
}

/** Read one trace of the project: summary, input, tagged output, and spans. */
export async function getProjectTrace(
  projectId: string,
  traceId: string,
  signal?: AbortSignal
): Promise<TraceDetail> {
  const path = `${tracesPath(projectId)}/${encodeURIComponent(traceId)}`
  return mapTraceDetail(await requestJson<unknown>(path, withSignal(signal)))
}

/** Return whether the failure is the project's non-revealing trace 404. */
export function isTraceNotFound(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404
}
