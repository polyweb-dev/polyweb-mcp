/**
 * Project provider view: which provider types one project can execute, per
 * operation. The server computes `effective_operations` (capability, system
 * policy, grant and binding enablement); the UI only filters by it.
 */
import { catalogNameOf } from "./catalog"

export type ProviderOperation = "search" | "fetch"

/** One provider type of the project view, keyed by its UI id. */
export interface ProjectProvider {
  /** UI provider id (`youcom`, not the wire `you`). */
  id: string
  /** Static catalog name, else the wire provider type. */
  name: string
  available: boolean
  enabled: boolean
  effectiveOperations: readonly ProviderOperation[]
}

/** Return the providers of the view that can run one operation, in view order. */
export function providersForOperation(
  providers: readonly ProjectProvider[],
  operation: ProviderOperation
): ProjectProvider[] {
  return providers.filter((provider) => provider.effectiveOperations.includes(operation))
}

/** Display name of one UI provider id from the static catalog. */
export function projectProviderName(id: string, providerType: string): string {
  return catalogNameOf(id) ?? providerType
}
