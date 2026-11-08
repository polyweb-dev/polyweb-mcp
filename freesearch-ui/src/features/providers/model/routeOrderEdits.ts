/**
 * Route order edits of one project: the priority a new route takes so it runs
 * last and a free route label.
 */
import type { ProviderTypeView, RouteEntry } from "@/domains/providers"

export const PRIORITY_STEP = 10
export const MAX_PRIORITY = 1_000_000

/** Priority that places a new route after every current route. */
export function nextPriority(routes: readonly RouteEntry[]): number {
  if (routes.length === 0) return PRIORITY_STEP
  const highest = routes.reduce((max, entry) => Math.max(max, entry.binding.priority), 0)
  return Math.min(MAX_PRIORITY, highest + PRIORITY_STEP)
}

/**
 * Route label for a new route on one key: the provider type, or the provider
 * type with the first free number when the key already carries that label.
 */
export function defaultRouteLabel(provider: ProviderTypeView, credentialId: string): string {
  const taken = new Set(
    provider.bindings.filter((binding) => binding.credentialId === credentialId).map((binding) => binding.routeLabel)
  )
  const base = provider.providerType
  if (!taken.has(base)) return base
  let suffix = 2
  while (taken.has(`${base}-${suffix}`)) suffix += 1
  return `${base}-${suffix}`
}
