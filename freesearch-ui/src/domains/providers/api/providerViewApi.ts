/**
 * Full project provider view.
 *
 * The view carries provider types (capability, system state, available
 * credentials, bindings) plus this project's own allocations.
 */
import { requestJson } from "@/shared/api/client"
import { asRecord } from "@/shared/api/decode"
import { decodeAllocation } from "./capacityWire"
import { decodeProviderTypeView } from "./credentialsWire"
import type { Allocation } from "../model/capacity"
import type { ProviderTypeView } from "../model/credentials"

/** The project provider view plus its own allocations. */
export interface ProjectProviderView {
  providers: ProviderTypeView[]
  allocations: Allocation[]
}

function rows<T>(value: unknown, decode: (row: unknown) => T | null): T[] {
  if (!Array.isArray(value)) return []
  return value.map(decode).filter((row): row is T => row !== null)
}

/** Decode `ProjectProvidersRead`; rows that do not decode are dropped. */
export function decodeProjectProviderView(payload: unknown): ProjectProviderView {
  const record = asRecord(payload)
  if (record === null || !Array.isArray(record.providers)) {
    throw new Error("project provider view is not a list of providers")
  }
  return {
    providers: rows(record.providers, decodeProviderTypeView),
    allocations: rows(record.allocations, decodeAllocation),
  }
}

/** Read the full provider view of one project. */
export async function getProjectProviderView(
  projectId: string,
  signal?: AbortSignal
): Promise<ProjectProviderView> {
  const payload = await requestJson<unknown>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/providers`,
    signal === undefined ? {} : { signal }
  )
  return decodeProjectProviderView(payload)
}
