/** Provider view metadata and catalog helpers. */
import { PROVIDER_CATALOG, catalogEntryForId, catalogNameOf } from "./catalog"
import type { ProviderOperation } from "./projectProviders"
import type { ProviderPricing } from "./providerPricing"
import type { ProviderHealthStatus } from "./types"

export const PROVIDER_OPERATIONS: readonly ProviderOperation[] = ["search", "fetch"]

export type CredentialAuthMode = "api_key" | "oauth"

/** The only provider type whose credentials may use OAuth. */
export const OAUTH_PROVIDER_TYPE = "parallel"

/** Safe metadata required by the provider row's legacy key menu. */
export interface AvailableCredential {
  id: string
  label: string
  authMode: string
}

/** The project provider route fields used by the UI. */
export interface ProviderBinding {
  credentialId: string
  priority: number
  effectiveOperations: ProviderOperation[]
}

/** Full project view of one provider type. */
export interface ProviderTypeView extends ProviderPricing {
  /** Wire provider type (`you`, not `youcom`). */
  providerType: string
  name: string
  keyless: boolean
  capability: ProviderOperation[]
  killSwitch: boolean
  systemEnabledOperations: ProviderOperation[]
  credentials: AvailableCredential[]
  bindings: ProviderBinding[]
  effectiveOperations: ProviderOperation[]
  /** Latest project-scoped provider observation, shared by all members. */
  healthStatus?: ProviderHealthStatus | null
  healthCheckedAt?: string | null
}

/** Display name of one wire provider type. */
export function providerTypeName(providerType: string): string {
  return catalogNameOf(providerType) ?? providerType
}

/** Wire provider types a credential can be created for, in catalog order. */
export function credentialProviderTypes(): string[] {
  return PROVIDER_CATALOG.map((meta) => meta.backendId)
}

/** Operations one provider type supports, from the static catalog. */
export function supportedOperationsOf(providerType: string): ProviderOperation[] {
  const entry = PROVIDER_CATALOG.find((meta) => meta.backendId === providerType)
  if (entry === undefined) return [...PROVIDER_OPERATIONS]
  return PROVIDER_OPERATIONS.filter((operation) => entry.capabilities.includes(operation))
}

/** Return whether a provider type may use OAuth credentials. */
export function supportsOAuth(providerType: string): boolean {
  return providerType === OAUTH_PROVIDER_TYPE
}

/** Return whether a provider type documents a keyless public access tier.
 *
 * The static catalog marks this in two equivalent ways: Keenable lists
 * `"keyless_tier"` among its capabilities, while Tavily sets the
 * `keyless_tier: true` property. Both markers count; wiring a new
 * keyless provider needs only one of them.
 */
export function supportsKeyless(providerType: string): boolean {
  if (providerType === OAUTH_PROVIDER_TYPE) return false
  const entry = catalogEntryForId(providerType)
  return entry !== undefined && (entry.keyless_tier === true || entry.capabilities.includes("keyless_tier"))
}

/** Keyless-supported wire provider types, in catalog order. */
export function keylessProviderTypes(): string[] {
  return PROVIDER_CATALOG.filter((meta) => meta.keyless_tier === true || meta.capabilities.includes("keyless_tier")).map(
    (meta) => meta.backendId
  )
}

/** Wire authentication mode selecting keyless credential creation. */
export const KEYLESS_AUTH_MODE = "keyless"

/** Stable keyless/free-tier authentication choice label for select controls. */
export const KEYLESS_AUTH_LABEL = "Keyless (no key needed)"

/** Credential authentication modes offered for a supported provider. Keyless
 * enters first when supported (a no-secret explicit choice); OAuth-supported
 * providers always offer API key + OAuth and never keyless. Keyed providers
 * offer API key only.
 */
export function credentialAuthModes(providerType: string): { value: string; label: string }[] {
  if (supportsOAuth(providerType)) return [{ value: "api_key", label: "API key" }, { value: "oauth", label: "OAuth" }]
  if (supportsKeyless(providerType)) return [{ value: KEYLESS_AUTH_MODE, label: KEYLESS_AUTH_LABEL }, { value: "api_key", label: "API key" }]
  return [{ value: "api_key", label: "API key" }]
}

/** Return whether the given auth selection needs a stored secret. */
export function authModeNeedsSecret(authMode: string): boolean {
  return authMode === "api_key"
}
