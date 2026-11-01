/**
 * Project provider view fixtures (`GET /api/v1/projects/{id}/providers`).
 *
 * The default view mirrors the canonical provider fleet: every provider type
 * is bound and can search; Brave cannot fetch.
 */
import { BACKEND_IDS } from "./providers"
import type { BackendId } from "./providers"

export interface WireProjectProviderType {
  provider_type: string
  capability: string[]
  kill_switch: boolean
  system_enabled_operations: string[]
  available: boolean
  enabled: boolean
  credentials: unknown[]
  bindings: unknown[]
  effective_operations: string[]
}

/** One provider type of the project view; operations default to its capability. */
export function projectProviderType(
  providerType: BackendId | string,
  effectiveOperations: readonly string[] = providerType === "brave" ? ["search"] : ["search", "fetch"]
): WireProjectProviderType {
  const capability = providerType === "brave" ? ["search"] : ["search", "fetch"]
  return {
    provider_type: providerType,
    capability,
    kill_switch: false,
    system_enabled_operations: capability,
    available: true,
    enabled: effectiveOperations.length > 0,
    credentials: [],
    bindings: [],
    effective_operations: [...effectiveOperations],
  }
}

/** The project provider view payload. */
export function projectProvidersFixture(
  projectId: string,
  providers: readonly WireProjectProviderType[] = BACKEND_IDS.map((id) => projectProviderType(id))
) {
  return { project_id: projectId, providers: [...providers], allocations: [] }
}
