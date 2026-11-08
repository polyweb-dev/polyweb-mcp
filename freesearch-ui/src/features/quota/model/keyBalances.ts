import { toBackendId } from "@/domains/providers"
import { requestJson } from "@/shared/api/client"

export interface KeyBalance {
  keyId: string
  label: string
  ownerEmail: string
  authMode: "api_key" | "oauth"
  oauthConnected: boolean | null
  balance: { remaining: string | null; unit: string; observedAt: string | null } | null
}

function record(value: unknown): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid key balance")
  }
  return value as Record<string, unknown>
}

function text(value: unknown): string {
  if (typeof value !== "string") throw new Error("Invalid key balance")
  return value
}

function optionalText(value: unknown): string | null {
  return value === null ? null : text(value)
}

/** Keep only the safe fields that the quota page displays. */
export function decodeKeyBalances(value: unknown): KeyBalance[] {
  if (!Array.isArray(value)) throw new Error("Invalid key balance list")
  return value.map((item: unknown) => {
    const row = record(item)
    const pool = row.balance === null ? null : record(row.balance)
    const authMode = row.auth_mode
    const oauthConnected = row.oauth_connected
    if (oauthConnected !== null && typeof oauthConnected !== "boolean") throw new Error("Invalid key balance")
    if (
      (authMode !== "api_key" && authMode !== "oauth")
      || (authMode === "api_key" && oauthConnected !== null)
      || (authMode === "oauth" && typeof oauthConnected !== "boolean")
    ) throw new Error("Invalid key balance")
    return {
      keyId: text(row.key_id),
      label: text(row.label),
      ownerEmail: text(row.owner_email),
      authMode,
      oauthConnected,
      balance: pool === null ? null : {
        remaining: optionalText(pool.remaining),
        unit: text(pool.native_unit),
        observedAt: optionalText(pool.observed_at),
      },
    }
  })
}

function providerPath(providerId: string): string {
  return `/api/v1/providers/${encodeURIComponent(toBackendId(providerId))}/limits/keys`
}

export async function listKeyBalances(providerId: string, signal: AbortSignal): Promise<KeyBalance[]> {
  return decodeKeyBalances(await requestJson<unknown>(providerPath(providerId), { signal }))
}

export async function syncKeyBalance(providerId: string, keyId: string): Promise<unknown> {
  return requestJson<unknown>(`${providerPath(providerId)}/${encodeURIComponent(keyId)}/sync`, { method: "POST" })
}

export function canRefreshKey(key: KeyBalance, isAdmin: boolean, email: string | null): boolean {
  return isAdmin || (email !== null && key.ownerEmail.toLowerCase() === email.toLowerCase())
}
