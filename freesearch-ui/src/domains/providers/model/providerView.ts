/** Provider view metadata and catalog helpers. */
import { PROVIDER_CATALOG, catalogNameOf } from "./catalog"
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
