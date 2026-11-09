import { catalogNameOf, toUiId } from "@/domains/providers"

/** Display name of one wire provider id, from the static catalog. */
export function usageProviderLabel(provider: string): string {
  return catalogNameOf(toUiId(provider)) ?? provider
}
