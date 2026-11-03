/**
 * Decoders of credential, grant, binding and OAuth payloads.
 *
 * Each decoder copies only the documented safe fields by name. Anything else
 * a response may carry (a secret slot, a token, a device code, a fingerprint,
 * an owner id) is never read, so it cannot reach a view or a log.
 */
import {
  asRecord,
  readEnum,
  readFlag,
  readInt,
  readMembers,
  readString,
} from "@/shared/api/decode"
import {
  CREDENTIAL_OPERATIONS,
  CREDENTIAL_OWNERS,
  OAUTH_GRANT_STATUSES,
  providerTypeName,
} from "../model/credentials"
import type {
  AvailableCredential,
  CredentialGrant,
  CredentialPoolRef,
  OAuthDeviceStart,
  OAuthStatus,
  ProjectCredential,
  ProviderBinding,
  ProviderTypeView,
  SystemCredential,
} from "../model/credentials"

function decodePoolRef(value: unknown): CredentialPoolRef | null {
  const record = asRecord(value)
  if (record === null) return null
  const operation = readEnum(record, "operation_scope", CREDENTIAL_OPERATIONS)
  const poolId = readString(record, "pool_id")
  if (operation === null || poolId === null) return null
  return { operation, poolId, label: readString(record, "label") ?? poolId }
}

/** Decode one available credential of the project provider view. */
export function decodeAvailableCredential(value: unknown): AvailableCredential | null {
  const record = asRecord(value)
  if (record === null) return null
  const id = readString(record, "id")
  const owner = readEnum(record, "owner_scope", CREDENTIAL_OWNERS)
  if (id === null || owner === null) return null
  const pools = Array.isArray(record.pools) ? record.pools : []
  return {
    id,
    label: readString(record, "label") ?? id,
    owner,
    authMode: readString(record, "auth_mode") ?? "api_key",
    status: readString(record, "status") ?? "unknown",
    health: readString(record, "health_status"),
    grantedOperations: readMembers(record, "granted_operations", CREDENTIAL_OPERATIONS),
    supportedOperations: readMembers(record, "supported_operations", CREDENTIAL_OPERATIONS),
    pools: pools.map(decodePoolRef).filter((pool) => pool !== null),
  }
}

/** Decode one binding of the provider view or the bindings route. */
export function decodeBinding(value: unknown): ProviderBinding | null {
  const record = asRecord(value)
  if (record === null) return null
  const id = readString(record, "id")
  const credentialId = readString(record, "credential_id")
  if (id === null || credentialId === null) return null
  const enabled = readMembers(record, "enabled_operations", CREDENTIAL_OPERATIONS)
  return {
    id,
    credentialId,
    routeLabel: readString(record, "route_label") ?? id,
    priority: readInt(record, "priority") ?? 0,
    enabledOperations: enabled,
    effectiveOperations:
      "effective_operations" in record
        ? readMembers(record, "effective_operations", CREDENTIAL_OPERATIONS)
        : enabled,
  }
}

function decodeRows<T>(value: unknown, decode: (row: unknown) => T | null): T[] {
  if (!Array.isArray(value)) return []
  return value.map(decode).filter((row): row is T => row !== null)
}

/** Decode one provider type of the project provider view. */
export function decodeProviderTypeView(value: unknown): ProviderTypeView | null {
  const record = asRecord(value)
  const providerType = record === null ? null : readString(record, "provider_type")
  if (record === null || providerType === null || providerType === "") return null
  return {
    providerType,
    name: providerTypeName(providerType),
    capability: readMembers(record, "capability", CREDENTIAL_OPERATIONS),
    killSwitch: readFlag(record, "kill_switch"),
    systemEnabledOperations: readMembers(record, "system_enabled_operations", CREDENTIAL_OPERATIONS),
    available: readFlag(record, "available"),
    enabled: readFlag(record, "enabled"),
    credentials: decodeRows(record.credentials, decodeAvailableCredential),
    bindings: decodeRows(record.bindings, decodeBinding),
    effectiveOperations: readMembers(record, "effective_operations", CREDENTIAL_OPERATIONS),
  }
}

/** Decode one project-facing credential (`ProjectCredentialRead`). */
export function decodeProjectCredential(value: unknown): ProjectCredential | null {
  const record = asRecord(value)
  if (record === null) return null
  const id = readString(record, "id")
  const providerType = readString(record, "provider_type")
  const owner = readEnum(record, "owner_scope", CREDENTIAL_OWNERS)
  if (id === null || providerType === null || owner === null) return null
  return {
    id,
    providerType,
    owner,
    label: readString(record, "label") ?? id,
    authMode: readString(record, "auth_mode") ?? "api_key",
    status: readString(record, "status") ?? "unknown",
    permittedOperations: readMembers(record, "permitted_operations", CREDENTIAL_OPERATIONS),
    canManage: readFlag(record, "can_manage"),
    generation: readInt(record, "generation"),
  }
}

/** Decode one system credential (`CredentialInstanceRead`). */
export function decodeSystemCredential(value: unknown): SystemCredential | null {
  const record = asRecord(value)
  if (record === null) return null
  const id = readString(record, "id")
  const providerType = readString(record, "provider_type")
  if (id === null || providerType === null) return null
  return {
    id,
    providerType,
    label: readString(record, "label") ?? id,
    authMode: readString(record, "auth_mode") ?? "api_key",
    generation: readInt(record, "generation") ?? 1,
    status: readString(record, "status") ?? "active",
  }
}

/** Decode one project grant of a system credential. */
export function decodeGrant(value: unknown): CredentialGrant | null {
  const record = asRecord(value)
  if (record === null) return null
  const credentialId = readString(record, "credential_id")
  const projectId = readString(record, "project_id")
  if (credentialId === null || projectId === null) return null
  return {
    credentialId,
    projectId,
    permittedOperations: readMembers(record, "permitted_operations", CREDENTIAL_OPERATIONS),
    version: readInt(record, "version") ?? 1,
  }
}

/** Decode a started device flow: user code, verification link and timings only. */
export function decodeOAuthDevice(value: unknown): OAuthDeviceStart | null {
  const record = asRecord(value)
  if (record === null) return null
  const userCode = readString(record, "user_code")
  const verificationUri = readString(record, "verification_uri")
  if (userCode === null || verificationUri === null || !isHttpUrl(verificationUri)) return null
  return {
    userCode,
    verificationUri,
    intervalSeconds: Math.max(1, readInt(record, "interval") ?? 5),
    expiresInSeconds: Math.max(1, readInt(record, "expires_in") ?? 600),
  }
}

/** Decode one OAuth connection state; token material is never read. */
export function decodeOAuthStatus(value: unknown): OAuthStatus | null {
  const record = asRecord(value)
  if (record === null) return null
  const status = readEnum(record, "status", OAUTH_GRANT_STATUSES)
  if (status === null) return null
  const interval = readInt(record, "interval")
  return { status, intervalSeconds: interval !== null && interval >= 1 ? interval : null }
}

function isHttpUrl(value: string): boolean {
  try {
    const url = new URL(value)
    return url.protocol === "https:" || url.protocol === "http:"
  } catch {
    return false
  }
}
