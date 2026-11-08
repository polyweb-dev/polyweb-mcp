/**
 * Route order of one project: every binding of every provider type, in the
 * priority order the router tries them. The project overview and the
 * providers page both read routes through this one derivation.
 */
import type { AvailableCredential, ProviderBinding, ProviderTypeView } from "./credentials"
import type { ProviderOperation } from "./projectProviders"

/** One binding with the provider and credential facts its row shows. */
export interface RouteEntry {
  binding: ProviderBinding
  provider: ProviderTypeView
  credential: AvailableCredential | null
}

/**
 * Flatten the bindings of a provider view into one list, lowest priority
 * number first; equal priorities keep the view's provider order.
 */
export function routeOrder(providers: readonly ProviderTypeView[]): RouteEntry[] {
  const entries: RouteEntry[] = []
  for (const provider of providers) {
    for (const binding of provider.bindings) {
      const credential = provider.credentials.find((row) => row.id === binding.credentialId) ?? null
      entries.push({ binding, provider, credential })
    }
  }
  return entries
    .map((entry, index) => ({ entry, index }))
    .sort((left, right) => left.entry.binding.priority - right.entry.binding.priority || left.index - right.index)
    .map(({ entry }) => entry)
}

/** Return whether at least one route of the view can run one operation. */
export function hasEffectiveRoute(
  providers: readonly ProviderTypeView[],
  operation?: ProviderOperation
): boolean {
  return providers.some((provider) =>
    provider.bindings.some((binding) =>
      operation === undefined
        ? binding.effectiveOperations.length > 0
        : binding.effectiveOperations.includes(operation)
    )
  )
}

