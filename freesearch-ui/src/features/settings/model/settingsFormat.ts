/**
 * Display rules of the settings page that the domain catalog does not own:
 * provider ids as provider names.
 */
import { PROVIDER_CATALOG, toUiId } from "@/domains/providers"
import { formatSettingsValue } from "@/domains/settings"
import type { SettingsValue } from "@/domains/settings"

const PREFERRED_PROVIDERS_FIELD = "routing.preferred_providers"

/** One provider a project may prefer: the stored wire id, its logo id and its name. */
interface PreferredProviderOption {
  value: string
  logoId: string
  label: string
}

/** Every provider the backend accepts in `preferred_providers`, in catalog order. */
export const PREFERRED_PROVIDER_OPTIONS: readonly PreferredProviderOption[] = PROVIDER_CATALOG.map((entry) => ({
  value: entry.backendId,
  logoId: entry.id,
  label: entry.name,
}))

/** Name of one stored provider id; an unknown id shows as stored. */
export function providerLabel(value: string): string {
  return PREFERRED_PROVIDER_OPTIONS.find((option) => option.value === value)?.label ?? value
}

/** Logo id of one stored provider id (`you` → `youcom`). */
export function providerLogoId(value: string): string {
  return toUiId(value)
}

/** Human text of one value on this page. */
export function valueText(fieldId: string, value: SettingsValue): string {
  if (fieldId === PREFERRED_PROVIDERS_FIELD && Array.isArray(value)) {
    return value.length === 0 ? "None" : value.map(providerLabel).join(", ")
  }
  return formatSettingsValue(fieldId, value)
}
