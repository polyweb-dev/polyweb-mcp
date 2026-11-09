/**
 * Full project provider view.
 *
 * The view carries provider policy, health and effective routes.
 */
import { requestJson } from "@/shared/api/client"
import { asRecord } from "@/shared/api/decode"
import { decodeProviderTypeView } from "./credentialsWire"
import type { ProviderTypeView } from "../model/providerView"

/** The provider data used by the project UI. */
export interface ProjectProviderView {
  providers: ProviderTypeView[]
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
