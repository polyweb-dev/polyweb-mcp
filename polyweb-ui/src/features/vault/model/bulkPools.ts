import { KEYLESS_AUTH_MODE, providerTypeName, supportedOperationsOf } from "@/domains/providers"
import type { KeyPool, KeyPoolInput, VaultKey, VaultProject } from "@/domains/vault"

/** One provider row of the vault table: its owned key and every pool on it. */
export interface BulkVaultRow {
  key: VaultKey
  pools: KeyPool[]
}

/** Resolution of one bulk-selected provider against the owned keys. */
export type BulkProviderStatus =
  | { kind: "ready"; providerType: string; key: VaultKey }
  | { kind: "missing-key"; providerType: string }
  | { kind: "ambiguous-keys"; providerType: string; labels: string[] }

/** Default pool input for one owned key. Keyless keys stay unlimited (null
 * limit); keyed keys inherit the key capacity, mirroring the single-pool
 * dialog's rate default. Budgets stay null: free rails carry no budget and
 * keyed budgets remain an explicit per-pool choice.
 */
export function defaultPoolInputForKey(key: VaultKey, projectId: string, label?: string): KeyPoolInput {
  return {
    label: label ?? providerTypeName(key.provider_type),
    project_id: projectId,
    rate: { limit: key.capacity?.limit ?? null, window_seconds: key.capacity?.window_seconds ?? 60 },
    budget: null,
    operations: supportedOperationsOf(key.provider_type),
    operation_limits: null,
  }
}

/** Resolve every selected provider to its single owned key. Multi-key
 * providers resolve ambiguous and are never picked silently; providers with
 * no owned key resolve missing so the caller can report them by name.
 */
export function resolveBulkProviders(rows: readonly BulkVaultRow[], providerTypes: readonly string[]): BulkProviderStatus[] {
  return providerTypes.map((providerType) => {
    const keys = rows.filter((row) => row.key.provider_type === providerType).map((row) => row.key)
    const [only, second] = keys
    if (only === undefined) return { kind: "missing-key", providerType }
    if (second !== undefined) return { kind: "ambiguous-keys", providerType, labels: keys.map((key) => key.label) }
    return { kind: "ready", providerType, key: only }
  })
}

/** Provider types of the vault's owned keys, in first-seen order. */
export function ownedProviderTypes(rows: readonly BulkVaultRow[]): string[] {
  const seen: string[] = []
  for (const row of rows) {
    if (!seen.includes(row.key.provider_type)) seen.push(row.key.provider_type)
  }
  return seen
}

/** Keyless input for one supported provider: no secret, keyless auth mode,
 * default capacity policy. The caller sends it only when no owned keyless
 * key exists for the provider.
 */
export function keylessKeyInput(providerType: string) {
  return {
    provider_type: providerType,
    label: `${providerTypeName(providerType)} keyless`,
    auth_mode: KEYLESS_AUTH_MODE,
    overcommit: true,
    contention_mode: "equal" as const,
  }
}

/** One keyless provider's key step: reuse the single owned keyless key or
 * signal creation; never pick from several silently. Creation (and its auth
 * contract) stays in the caller, next to the pool step.
 */
export function planKeylessKey(
  rows: readonly BulkVaultRow[],
  providerType: string
): { row?: BulkVaultRow; outcome?: BulkOutcome } {
  const name = providerTypeName(providerType)
  const owned = rows.filter((row) => row.key.provider_type === providerType && row.key.auth_mode === KEYLESS_AUTH_MODE)
  if (owned.length > 1) {
    return {
      outcome: {
        providerType,
        message: `${name}: ${owned.length} keyless keys (${owned.map((row) => row.key.label).join(", ")}) — create from the key row instead`,
        created: false,
      },
    }
  }
  return { row: owned[0] }
}

/** True when the project already holds an assigned pool on this key. */
export function hasProjectPool(pools: readonly KeyPool[], projectId: string): boolean {
  return pools.some((pool) => pool.project_id === projectId)
}

/** Projects that may receive pools for every listed provider. */
export function eligibleBulkProjects(projects: readonly VaultProject[], providerTypes: readonly string[]): VaultProject[] {
  return projects.filter((project) =>
    providerTypes.every((providerType) => project.available_providers.includes(providerType))
  )
}

/** One per-provider bulk outcome: the vault row it ran against, if any. */
export interface BulkOutcome {
  providerType: string
  message: string
  created: boolean
}

/** Resolve one bulk-selected provider to a pool-creation step or a named skip.
 * Multi-key providers fail loudly by name and are never picked silently.
 */
export function planBulkProvider(
  rows: readonly BulkVaultRow[],
  projects: readonly VaultProject[],
  providerType: string,
  projectId: string
): { key?: VaultKey; outcome: BulkOutcome } {
  const name = providerTypeName(providerType)
  const keys = rows.filter((row) => row.key.provider_type === providerType).map((row) => row.key)
  const [only, second] = keys
  if (only === undefined) return { outcome: { providerType, message: `${name}: no owned key — add one first`, created: false } }
  if (second !== undefined) {
    return {
      outcome: {
        providerType,
        message: `${name}: ${keys.length} keys (${keys.map((key) => key.label).join(", ")}) — create from the key row instead`,
        created: false,
      },
    }
  }
  const key = only
  const row = rows.find((entry) => entry.key.id === key.id)
  const available = eligibleBulkProjects(projects, [providerType]).some((project) => project.id === projectId)
  if (row === undefined || !available) {
    return { outcome: { providerType, message: `${name}: not available for this project`, created: false } }
  }
  if (hasProjectPool(row.pools, projectId)) {
    return { outcome: { providerType, message: `${name}: already assigned`, created: false } }
  }
  return { key, outcome: { providerType, message: "", created: false } }
}
