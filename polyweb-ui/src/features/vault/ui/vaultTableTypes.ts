import type { KeyPool, VaultKey, VaultOAuthStatus } from "@/domains/vault"

export type KeyAction = "create" | "rotate" | "settings" | "delete" | "connect" | "disconnect"
export type PoolAction = "edit" | "copy" | "assign" | "unassign" | "delete"
export interface VaultRow {
  key: VaultKey
  pools: KeyPool[]
  oauth: VaultOAuthStatus["status"] | null
}
