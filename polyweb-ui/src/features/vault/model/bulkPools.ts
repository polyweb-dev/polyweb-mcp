import { KEYLESS_AUTH_MODE, providerTypeName, supportedOperationsOf } from "@/domains/providers"
import type { KeyPool, KeyPoolInput, VaultKey, VaultKeyInput, VaultProject } from "@/domains/vault"

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

/** What one provider's step ended as: a pool this run created, a provider
 * the project already had, or a provider that needs the user's attention.
 */
export type OutcomeStatus = "created" | "assigned" | "blocked"

/** One per-provider outcome line of a dialog run. */
export interface ProviderOutcome {
  providerType: string
  status: OutcomeStatus
  message: string
}

/** Next step for one provider: create its pool on a key, create the keyless
 * key first, or stop with an outcome.
 */
export type ProviderPlan =
  | { kind: "pool"; key: VaultKey }
  | { kind: "create-key" }
  | { kind: "skip"; outcome: ProviderOutcome }

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

/** Project-scoped pool label that cannot collide on the owning credential:
 * the (credential_id, label) uniqueness constraint rejects a repeated label
 * even across projects ("Research" on Alpha then on Beta). An existing
 * unassigned same-name pool counts too, so a label of a deleted assignment
 * is never reused. Suffixes stay stable: (2), (3), …
 */
export function defaultPoolLabel(providerType: string, projectName: string, existingLabels: readonly string[]): string {
  const base = `${providerTypeName(providerType)} · ${projectName}`
  if (!existingLabels.includes(base)) return base
  let suffix = 2
  while (existingLabels.includes(`${base} (${suffix})`)) suffix += 1
  return `${base} (${suffix})`
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
 * default capacity policy. Sent only when no owned keyless key exists.
 */
export function keylessKeyInput(providerType: string): VaultKeyInput {
  return {
    provider_type: providerType,
    label: `${providerTypeName(providerType)} keyless`,
    auth_mode: KEYLESS_AUTH_MODE,
    overcommit: true,
    contention_mode: "equal",
  }
}

/** True when the project already holds an assigned pool on this key. */
export function hasProjectPool(pools: readonly KeyPool[], projectId: string): boolean {
  return pools.some((pool) => pool.project_id === projectId)
}

/** True when any owned key of one provider already holds a pool assigned to
 * the project, regardless of key auth mode: an assigned keyed pool counts
 * for keyless defaults just as an assigned keyless pool does.
 */
export function hasAssignedPool(rows: readonly BulkVaultRow[], providerType: string, projectId: string): boolean {
  return rows.some((row) => row.key.provider_type === providerType && hasProjectPool(row.pools, projectId))
}

/** Projects that may receive pools for the listed providers. A provider
 * counts as satisfied for a project when the API still lists it as
 * available or an owned key already holds an assigned pool there: the API
 * excludes assigned providers from available_providers, so assignments must
 * count or bulk creation could never target a partially assigned project.
 */
export function eligibleBulkProjects(
  projects: readonly VaultProject[],
  providerTypes: readonly string[],
  rows: readonly BulkVaultRow[] = []
): VaultProject[] {
  return projects.filter((project) =>
    providerTypes.every((providerType) =>
      project.available_providers.includes(providerType) ||
      hasAssignedPool(rows, providerType, project.id)
    )
  )
}

function assignedPlan(providerType: string): ProviderPlan {
  return { kind: "skip", outcome: { providerType, status: "assigned", message: `${providerTypeName(providerType)}: already assigned` } }
}

function blockedPlan(providerType: string, detail: string): ProviderPlan {
  return { kind: "skip", outcome: { providerType, status: "blocked", message: `${providerTypeName(providerType)}: ${detail}` } }
}

function ambiguousPlan(providerType: string, noun: string, labels: readonly string[]): ProviderPlan {
  return blockedPlan(providerType, `${labels.length} ${noun} (${labels.join(", ")}) — create from the key row instead`)
}

/** Plan one bulk-selected provider on its single owned key. An assignment
 * on any key of the provider is checked first: the API excludes assigned
 * providers from available_providers, so the skip message stays accurate.
 * Multi-key providers are blocked by name and never picked silently.
 */
export function planBulkProvider(
  rows: readonly BulkVaultRow[],
  projects: readonly VaultProject[],
  providerType: string,
  projectId: string
): ProviderPlan {
  if (hasAssignedPool(rows, providerType, projectId)) return assignedPlan(providerType)
  const [status] = resolveBulkProviders(rows, [providerType])
  if (status.kind === "missing-key") return blockedPlan(providerType, "no owned key — add one first")
  if (status.kind === "ambiguous-keys") return ambiguousPlan(providerType, "keys", status.labels)
  const project = projects.find((entry) => entry.id === projectId)
  if (project?.available_providers.includes(providerType) !== true) return blockedPlan(providerType, "not available for this project")
  return { kind: "pool", key: status.key }
}

/** Plan one keyless-default provider. Skip when any pool of the provider —
 * keyed or keyless — is already assigned to the project, so an existing
 * keyed Tavily assignment counts and no keyless key is created beside it.
 * Otherwise reuse the single owned keyless key, or create one; several
 * keyless keys are blocked by name, never picked silently.
 */
export function planKeylessProvider(rows: readonly BulkVaultRow[], providerType: string, projectId: string): ProviderPlan {
  if (hasAssignedPool(rows, providerType, projectId)) return assignedPlan(providerType)
  const owned = rows.filter((row) => row.key.provider_type === providerType && row.key.auth_mode === KEYLESS_AUTH_MODE)
  if (owned.length > 1) return ambiguousPlan(providerType, "keyless keys", owned.map((row) => row.key.label))
  return owned[0] === undefined ? { kind: "create-key" } : { kind: "pool", key: owned[0].key }
}

/** Verdict over one dialog run's outcomes: closes only on `success` (no
 * blocked provider and at least one pool created); `unchanged` is a run
 * where everything was already assigned; `attention` has a blocked provider.
 */
export type OutcomeVerdict = "empty" | "success" | "unchanged" | "attention"

function countStatus(outcomes: readonly ProviderOutcome[], status: OutcomeStatus): number {
  return outcomes.filter((outcome) => outcome.status === status).length
}

export function judgeOutcomes(outcomes: readonly ProviderOutcome[]): OutcomeVerdict {
  if (outcomes.length === 0) return "empty"
  if (countStatus(outcomes, "blocked") > 0) return "attention"
  return countStatus(outcomes, "created") > 0 ? "success" : "unchanged"
}

/** Error line for a finished run that did not close: null when something was
 * created (the outcome lines already tell the rest).
 */
export function outcomeError(outcomes: readonly ProviderOutcome[]): string | null {
  const verdict = judgeOutcomes(outcomes)
  if (verdict === "unchanged") return "Everything is already assigned. Nothing changed"
  if (verdict === "attention" && countStatus(outcomes, "created") === 0) {
    return "No pools were created. Resolve each provider above and try again"
  }
  return null
}

/** Created, already-assigned and blocked counts as one line. */
export function summarizeOutcomes(outcomes: readonly ProviderOutcome[]): string {
  const created = countStatus(outcomes, "created")
  const parts = [`Created ${created} ${created === 1 ? "pool" : "pools"}`]
  const assigned = countStatus(outcomes, "assigned")
  const blocked = countStatus(outcomes, "blocked")
  if (assigned > 0) parts.push(`${assigned} already assigned`)
  if (blocked > 0) parts.push(`${blocked} blocked`)
  return parts.join(", ")
}

/** Rows after one pool write: appended to the key that owns it. */
function withCreatedPool(rows: readonly BulkVaultRow[], keyId: string, pool: KeyPool): BulkVaultRow[] {
  return rows.map((entry) => (entry.key.id === keyId ? { ...entry, pools: [...entry.pools, pool] } : entry))
}

/** One created record, reconciled into the dialog's rows for retry planning. */
export type CreatedRecord = { key: VaultKey } | { keyId: string; pool: KeyPool }

/** Rows after one created record: a key is appended unless present, a pool
 * goes onto its key. A retry then reuses successes instead of repeating writes.
 */
export function reconcileCreated(rows: readonly BulkVaultRow[], created: CreatedRecord): BulkVaultRow[] {
  if ("pool" in created) return withCreatedPool(rows, created.keyId, created.pool)
  const { key } = created
  return rows.some((entry) => entry.key.id === key.id) ? [...rows] : [...rows, { key, pools: [] }]
}

/** Which dialog's planner a run uses. */
export type ProvisionMode = "bulk" | "defaults"

/** One dialog run: the providers to provision for one project. `kept` holds
 * outcomes of earlier attempts: providers already created or assigned are
 * not repeated, blocked ones are planned again.
 */
export interface ProvisionRun {
  mode: ProvisionMode
  rows: readonly BulkVaultRow[]
  projects: readonly VaultProject[]
  providerTypes: readonly string[]
  projectId: string
  projectName: string
  kept: readonly ProviderOutcome[]
}

/** Callbacks a run reports through, one outcome or created record at a time. */
export interface ProvisionHooks {
  publish: (outcome: ProviderOutcome) => void
  reconcile: (created: CreatedRecord) => void
}

/** Transport injected into the run so this module owns no API imports. */
export interface ProvisionClients {
  createKey: (input: VaultKeyInput) => Promise<VaultKey>
  createPool: (keyId: string, input: KeyPoolInput) => Promise<KeyPool>
}

function planProvider(run: ProvisionRun, providerType: string): ProviderPlan {
  return run.mode === "bulk"
    ? planBulkProvider(run.rows, run.projects, providerType, run.projectId)
    : planKeylessProvider(run.rows, providerType, run.projectId)
}

async function provisionProvider(
  run: ProvisionRun,
  providerType: string,
  hooks: ProvisionHooks,
  clients: ProvisionClients
): Promise<ProviderOutcome> {
  const plan = planProvider(run, providerType)
  if (plan.kind === "skip") return plan.outcome
  const key = plan.kind === "pool" ? plan.key : await clients.createKey(keylessKeyInput(providerType))
  if (plan.kind === "create-key") hooks.reconcile({ key })
  const pools = run.rows.find((row) => row.key.id === key.id)?.pools ?? []
  const label = defaultPoolLabel(providerType, run.projectName, pools.map((pool) => pool.label))
  const pool = await clients.createPool(key.id, defaultPoolInputForKey(key, run.projectId, label))
  hooks.reconcile({ keyId: key.id, pool })
  return { providerType, status: "created", message: `${providerTypeName(providerType)}: created pool ${pool.label}` }
}

/** Execute one run provider by provider, publishing each outcome as it
 * completes so a later failure keeps earlier successes visible. Created
 * records are reconciled as they happen, so a retry reuses the created key
 * and writes every pool once.
 */
export async function executeProvisionRun(
  run: ProvisionRun,
  hooks: ProvisionHooks,
  clients: ProvisionClients
): Promise<void> {
  for (const providerType of run.providerTypes) {
    const done = run.kept.some((outcome) => outcome.providerType === providerType && outcome.status !== "blocked")
    if (!done) hooks.publish(await provisionProvider(run, providerType, hooks, clients))
  }
}
