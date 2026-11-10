import type { PlaygroundController } from "../model/usePlaygroundController"

/**
 * The display name of the one pinned provider, if the run pins one that is
 * still eligible for the mode. Auto/all runs stay unscoped: the setup
 * guidance names no provider rather than guessing.
 */
export function pinnedProviderName(controller: PlaygroundController): string | undefined {
  if (controller.selectedProviderId === "auto" || controller.selectedProviderId === "all") return undefined
  return controller.eligibleProviders.find((provider) => provider.id === controller.selectedProviderId)?.name
}
