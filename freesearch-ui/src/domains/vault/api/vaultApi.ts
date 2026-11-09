import { requestJson } from "@/shared/api/client"
import type { KeyPool, KeyPoolInput, VaultKey, VaultKeyDeleteResult, VaultKeyInput, VaultOAuthDevice, VaultOAuthStatus, VaultProject } from "../model/types"
import { decodeKeyDeleteResult, decodeKeyPool, decodeList, decodeOAuthDevice, decodeOAuthStatus, decodeVaultKey, decodeVaultProjects } from "./vaultWire"

const keyPath = (id: string) => `/api/v1/account/vault/keys/${encodeURIComponent(id)}`
const poolPath = (id: string) => `/api/v1/account/vault/pools/${encodeURIComponent(id)}`
const json = (method: string, body: unknown) => ({ method, body: JSON.stringify(body) })

export async function listVaultKeys(signal?: AbortSignal): Promise<VaultKey[]> {
  return decodeList(await requestJson<unknown>("/api/v1/account/vault/keys", { signal }), decodeVaultKey)
}

export async function createVaultKey(input: VaultKeyInput): Promise<VaultKey> {
  return decodeVaultKey(await requestJson<unknown>("/api/v1/account/vault/keys", json("POST", input)))
}

export async function updateVaultKey(id: string, input: Partial<Pick<VaultKeyInput, "label" | "capacity" | "overcommit" | "contention_mode">>): Promise<VaultKey> {
  return decodeVaultKey(await requestJson<unknown>(keyPath(id), json("PATCH", input)))
}

export async function rotateVaultKey(id: string, expected_generation: number, secret: string): Promise<VaultKey> {
  return decodeVaultKey(await requestJson<unknown>(`${keyPath(id)}/rotate`, json("POST", { expected_generation, secret })))
}

export async function deleteVaultKey(id: string): Promise<VaultKeyDeleteResult> {
  return decodeKeyDeleteResult(await requestJson<unknown>(keyPath(id), { method: "DELETE" }))
}

export async function listKeyPools(id: string, signal?: AbortSignal): Promise<KeyPool[]> {
  return decodeList(await requestJson<unknown>(`${keyPath(id)}/pools`, { signal }), decodeKeyPool)
}

export async function createKeyPool(id: string, input: KeyPoolInput): Promise<KeyPool> {
  return decodeKeyPool(await requestJson<unknown>(`${keyPath(id)}/pools`, json("POST", input)))
}

export async function getKeyPool(id: string, signal?: AbortSignal): Promise<KeyPool> {
  return decodeKeyPool(await requestJson<unknown>(poolPath(id), { signal }))
}

export async function updateKeyPool(id: string, input: Partial<Omit<KeyPoolInput, "project_id">>): Promise<KeyPool> {
  const { label, rate, budget, operations, operation_limits } = input
  return decodeKeyPool(await requestJson<unknown>(poolPath(id), json("PATCH", { label, rate, budget, operations, operation_limits })))
}

export async function deleteKeyPool(id: string): Promise<void> {
  await requestJson(poolPath(id), { method: "DELETE" })
}

export async function copyKeyPool(id: string, project_id: string, label?: string): Promise<KeyPool> {
  return decodeKeyPool(await requestJson<unknown>(`${poolPath(id)}/copy`, json("POST", { project_id, label })))
}

export async function assignKeyPool(id: string, project_id: string): Promise<KeyPool> {
  return decodeKeyPool(await requestJson<unknown>(`${poolPath(id)}/assign`, json("POST", { project_id })))
}

export async function unassignKeyPool(id: string): Promise<KeyPool> {
  return decodeKeyPool(await requestJson<unknown>(`${poolPath(id)}/unassign`, { method: "POST" }))
}

export async function listVaultProjects(signal?: AbortSignal): Promise<VaultProject[]> {
  return decodeVaultProjects(await requestJson<unknown>("/api/v1/account/vault/projects", { signal }))
}

export async function startVaultOAuth(id: string, signal?: AbortSignal): Promise<VaultOAuthDevice> {
  return decodeOAuthDevice(await requestJson<unknown>(`${keyPath(id)}/oauth/device`, { method: "POST", signal }))
}

export async function pollVaultOAuth(id: string, signal?: AbortSignal): Promise<VaultOAuthStatus> {
  return decodeOAuthStatus(await requestJson<unknown>(`${keyPath(id)}/oauth/poll`, { method: "POST", signal }))
}

export async function getVaultOAuth(id: string, signal?: AbortSignal): Promise<VaultOAuthStatus> {
  return decodeOAuthStatus(await requestJson<unknown>(`${keyPath(id)}/oauth`, { signal }))
}

export async function disconnectVaultOAuth(id: string): Promise<void> {
  await requestJson(`${keyPath(id)}/oauth`, { method: "DELETE" })
}
