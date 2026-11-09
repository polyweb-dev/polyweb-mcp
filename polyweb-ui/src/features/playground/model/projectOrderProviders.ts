import { providerIdentity } from "@/domains/providers"
import type { ProjectProvider, ProviderTypeView } from "@/domains/providers"
import type { OrderOperation, ProjectOrder } from "@/domains/routing"

/** Combine pool membership with system operation controls, not legacy bindings. */
export function projectOrderProviders(order: ProjectOrder, types: readonly ProviderTypeView[]) {
  const providers = new Map<string, ProjectProvider>()
  const byOperation: Record<OrderOperation, ProjectProvider[]> = { search: [], fetch: [] }
  for (const operation of ["search", "fetch"] as const) {
    for (const item of order[operation].providers) {
      const type = types.find((entry) => entry.providerType === item.provider)
      if (!type || type.killSwitch || !type.capability.includes(operation) ||
          !type.systemEnabledOperations.includes(operation) ||
          order[operation].notAllowed.includes(item.provider)) continue
      const identity = providerIdentity(item.provider)
      const provider = providers.get(identity.id) ?? {
        ...identity, available: true, enabled: true, effectiveOperations: [],
      }
      provider.effectiveOperations = [...provider.effectiveOperations, operation]
      providers.set(identity.id, provider)
      byOperation[operation].push(provider)
    }
  }
  return { providers: [...providers.values()], byOperation }
}
