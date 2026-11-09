import type { ProviderTypeView } from "./providerView"
import type { ProviderOperation } from "./projectProviders"

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
