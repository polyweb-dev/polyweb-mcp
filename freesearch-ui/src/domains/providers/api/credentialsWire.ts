/**
 * Decode the project provider view's safe fields.
 *
 * Each decoder copies only the documented safe fields by name. Anything else
 * a response may carry (a secret slot, a token, a device code, a fingerprint,
 * an owner id) is never read, so it cannot reach a view or a log.
 */
import {
  asRecord,
  readFlag,
  readInt,
  readMembers,
  readString,
} from "@/shared/api/decode"
import { decodeCallCosts } from "../model/providerPricing"
import {
  PROVIDER_OPERATIONS,
  providerTypeName,
} from "../model/providerView"
import type {
  AvailableCredential,
  ProviderBinding,
  ProviderTypeView,
} from "../model/providerView"

/** Decode one available credential of the project provider view. */
export function decodeAvailableCredential(value: unknown): AvailableCredential | null {
  const record = asRecord(value)
  if (record === null) return null
  const id = readString(record, "id")
  if (id === null) return null
  return {
    id,
    label: readString(record, "label") ?? id,
    authMode: readString(record, "auth_mode") ?? "api_key",
  }
}

/** Decode one binding of the provider view or the bindings route. */
export function decodeBinding(value: unknown): ProviderBinding | null {
  const record = asRecord(value)
  if (record === null) return null
  const id = readString(record, "id")
  const credentialId = readString(record, "credential_id")
  if (id === null || credentialId === null) return null
  const enabled = readMembers(record, "enabled_operations", PROVIDER_OPERATIONS)
  return {
    credentialId,
    priority: readInt(record, "priority") ?? 0,
    effectiveOperations:
      "effective_operations" in record
        ? readMembers(record, "effective_operations", PROVIDER_OPERATIONS)
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
    keyless: Object.keys(decodeCallCosts(record.keyless_call_cost_usd)).length > 0,
    callCostUsd: decodeCallCosts(record.call_cost_usd),
    keylessCallCostUsd: decodeCallCosts(record.keyless_call_cost_usd),
    capability: readMembers(record, "capability", PROVIDER_OPERATIONS),
    killSwitch: readFlag(record, "kill_switch"),
    systemEnabledOperations: readMembers(record, "system_enabled_operations", PROVIDER_OPERATIONS),
    healthStatus: readString(record, "health_status"),
    healthCheckedAt: readString(record, "health_checked_at"),
    credentials: decodeRows(record.credentials, decodeAvailableCredential),
    bindings: decodeRows(record.bindings, decodeBinding),
    effectiveOperations: readMembers(record, "effective_operations", PROVIDER_OPERATIONS),
  }
}
