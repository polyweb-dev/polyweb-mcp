/**
 * Project provider view read (`GET /api/v1/projects/{id}/providers`).
 *
 * The payload is decoded from `unknown`; only the fields the client gates on
 * are kept. Credential and binding details never leave this decoder.
 */
import { requestJson } from "@/shared/api/client"
import { toUiId } from "./idMapping"
import { projectProviderName } from "../model/projectProviders"
import type { ProjectProvider, ProviderOperation } from "../model/projectProviders"

const OPERATIONS: readonly ProviderOperation[] = ["search", "fetch"]

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function decodeOperations(value: unknown): ProviderOperation[] {
  if (!Array.isArray(value)) return []
  return OPERATIONS.filter((operation) => value.includes(operation))
}

function decodeProvider(value: unknown): ProjectProvider | null {
  const record = asRecord(value)
  const providerType = record?.provider_type
  if (record === null || typeof providerType !== "string" || providerType === "") return null
  const id = toUiId(providerType)
  return {
    id,
    name: projectProviderName(id, providerType),
    available: record.available === true,
    enabled: record.enabled === true,
    effectiveOperations: decodeOperations(record.effective_operations),
  }
}

/** Decode the project provider view; rows that do not decode are dropped. */
export function decodeProjectProviders(payload: unknown): ProjectProvider[] {
  const rows = asRecord(payload)?.providers
  if (!Array.isArray(rows)) throw new Error("project provider view is not a list of providers")
  const providers: ProjectProvider[] = []
  for (const row of rows) {
    const provider = decodeProvider(row)
    if (provider !== null) providers.push(provider)
  }
  return providers
}

/** Read the provider view of one project. */
export async function getProjectProviders(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectProvider[]> {
  const payload = await requestJson<unknown>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/providers`,
    signal === undefined ? {} : { signal }
  )
  return decodeProjectProviders(payload)
}
