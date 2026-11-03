/**
 * Credential instances, project bindings and the OAuth device flow.
 *
 * Every type here is safe metadata: no secret, token, device code or
 * fingerprint exists in any of them, so nothing secret can reach a view.
 */
import { PROVIDER_CATALOG, catalogNameOf } from "./catalog"
import type { ProviderOperation } from "./projectProviders"

export const CREDENTIAL_OPERATIONS: readonly ProviderOperation[] = ["search", "fetch"]

export type CredentialAuthMode = "api_key" | "oauth"

export type CredentialOwner = "system" | "project"
export const CREDENTIAL_OWNERS: readonly CredentialOwner[] = ["system", "project"]

/** The only provider type whose credentials may use OAuth. */
export const OAUTH_PROVIDER_TYPE = "parallel"

/** Pool that one operation of an available credential draws from. */
export interface CredentialPoolRef {
  operation: ProviderOperation
  poolId: string
  label: string
}

/** One credential a project may bind: its own private or a granted system one. */
export interface AvailableCredential {
  id: string
  label: string
  owner: CredentialOwner
  authMode: string
  status: string
  health: string | null
  grantedOperations: ProviderOperation[]
  supportedOperations: ProviderOperation[]
  pools: CredentialPoolRef[]
}

/** One project binding with its configured and effective operations. */
export interface ProviderBinding {
  id: string
  credentialId: string
  routeLabel: string
  priority: number
  enabledOperations: ProviderOperation[]
  effectiveOperations: ProviderOperation[]
}

/** Full project view of one provider type. */
export interface ProviderTypeView {
  /** Wire provider type (`you`, not `youcom`). */
  providerType: string
  name: string
  capability: ProviderOperation[]
  killSwitch: boolean
  systemEnabledOperations: ProviderOperation[]
  available: boolean
  enabled: boolean
  credentials: AvailableCredential[]
  bindings: ProviderBinding[]
  effectiveOperations: ProviderOperation[]
}

/** Project-facing projection of one credential instance. */
export interface ProjectCredential {
  id: string
  providerType: string
  owner: CredentialOwner
  label: string
  authMode: string
  status: string
  permittedOperations: ProviderOperation[]
  canManage: boolean
  generation: number | null
}

/** System view of one system-owned credential instance. */
export interface SystemCredential {
  id: string
  providerType: string
  label: string
  authMode: string
  generation: number
  status: string
}

/** One project's grant of a system credential. */
export interface CredentialGrant {
  credentialId: string
  projectId: string
  permittedOperations: ProviderOperation[]
  version: number
}

/** Input of one credential creation; `secret` only for `api_key`. */
export interface NewCredentialInput {
  providerType: string
  label: string
  authMode: CredentialAuthMode
  secret: string
}

/** Input of one binding creation; a new binding starts with nothing enabled. */
export interface NewBindingInput {
  credentialId: string
  routeLabel: string
  priority: number
}

export type OAuthGrantStatus = "pending" | "connected" | "refresh_failed" | "disconnected"
export const OAUTH_GRANT_STATUSES: readonly OAuthGrantStatus[] = [
  "pending",
  "connected",
  "refresh_failed",
  "disconnected",
]

/** The public part of a started device flow: what the human types and where. */
export interface OAuthDeviceStart {
  userCode: string
  verificationUri: string
  intervalSeconds: number
  expiresInSeconds: number
}

/** Connection state of one credential's OAuth grant. */
export interface OAuthStatus {
  status: OAuthGrantStatus
  /** Seconds before the next poll; set only on a pending poll answer. */
  intervalSeconds: number | null
}

const OAUTH_STATUS_TEXT: Record<OAuthGrantStatus, string> = {
  pending: "Waiting for approval…",
  connected: "Connected",
  refresh_failed: "Connection needs attention",
  disconnected: "Not connected",
}

/** User-facing text of one OAuth grant status. */
export function oauthStatusText(status: OAuthGrantStatus): string {
  return OAUTH_STATUS_TEXT[status]
}

/** "Runs: search, fetch" or "Runs: nothing yet". */
export function runsText(operations: readonly ProviderOperation[]): string {
  return operations.length === 0 ? "Runs: nothing yet" : `Runs: ${operations.join(", ")}`
}

/** User-facing auth mode label. */
export function authModeLabel(authMode: string): string {
  return authMode === "oauth" ? "OAuth" : "API key"
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
  if (entry === undefined) return [...CREDENTIAL_OPERATIONS]
  return CREDENTIAL_OPERATIONS.filter((operation) => entry.capabilities.includes(operation))
}

/** Return whether a provider type may use OAuth credentials. */
export function supportsOAuth(providerType: string): boolean {
  return providerType === OAUTH_PROVIDER_TYPE
}
