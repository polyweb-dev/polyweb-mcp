/**
 * Project usage reads: `GET /api/v1/projects/{id}/usage` and `/dashboard`.
 *
 * Both answer the same project-only shape. The payload is decoded from
 * `unknown`; decimal units arrive as strings or numbers and both are accepted.
 */
import { requestJson } from "@/shared/api/client"
import { normalizeUnitKind } from "@/shared/api/units"
import type { ProjectUsage, ProjectUsageEntry, ProjectUsageTotal } from "../model/types"

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function asString(value: unknown): string | null {
  return typeof value === "string" && value !== "" ? value : null
}

/** A decimal string or a number; anything else, or a non-finite value, is 0. */
function asAmount(value: unknown): number {
  const parsed = typeof value === "number" ? value : typeof value === "string" ? Number(value) : NaN
  return Number.isFinite(parsed) ? parsed : 0
}

function asLatency(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null
}

function decodeTotal(value: unknown): ProjectUsageTotal | null {
  const record = asRecord(value)
  const provider = asString(record?.provider)
  const operation = asString(record?.operation)
  if (record === null || provider === null || operation === null) return null
  return {
    provider,
    operation,
    totalUnits: asAmount(record.total_units),
    eventCount: Math.max(0, Math.round(asAmount(record.event_count))),
    unitKind: normalizeUnitKind(record.unit_kind),
  }
}

function decodeEntry(value: unknown): ProjectUsageEntry | null {
  const record = asRecord(value)
  const provider = asString(record?.provider)
  const operation = asString(record?.operation)
  const observedAt = asString(record?.observed_at)
  if (record === null || provider === null || operation === null || observedAt === null) return null
  return {
    provider,
    operation,
    units: asAmount(record.units),
    observedAt,
    latencyMs: asLatency(record.latency_ms),
    status: record.status === "failure" ? "failure" : "success",
    unitKind: normalizeUnitKind(record.unit_kind),
    displayUnit: asString(record.display_unit),
  }
}

function decodeList<T>(value: unknown, decode: (item: unknown) => T | null): T[] {
  if (!Array.isArray(value)) return []
  return value.map(decode).filter((item): item is T => item !== null)
}

/** Decode one project usage payload; a body that is not an object is rejected. */
export function decodeProjectUsage(payload: unknown): ProjectUsage {
  const record = asRecord(payload)
  if (record === null) throw new Error("project usage response is not an object")
  return {
    projectId: asString(record.project_id) ?? "",
    totals: decodeList(record.totals, decodeTotal),
    recent: decodeList(record.recent_usage, decodeEntry),
    generatedAt: asString(record.generated_at) ?? "",
  }
}

async function readUsage(path: string, signal: AbortSignal | undefined): Promise<ProjectUsage> {
  const payload = await requestJson<unknown>(path, signal === undefined ? {} : { signal })
  return decodeProjectUsage(payload)
}

/** Read the project's usage totals and recent ledger. */
export function getProjectUsage(projectId: string, signal?: AbortSignal): Promise<ProjectUsage> {
  return readUsage(`/api/v1/projects/${encodeURIComponent(projectId)}/usage`, signal)
}

/** Read the project's dashboard snapshot (its own usage only). */
export function getProjectDashboard(projectId: string, signal?: AbortSignal): Promise<ProjectUsage> {
  return readUsage(`/api/v1/projects/${encodeURIComponent(projectId)}/dashboard`, signal)
}
