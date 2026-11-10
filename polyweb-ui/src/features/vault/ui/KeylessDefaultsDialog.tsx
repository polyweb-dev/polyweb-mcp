import { useState } from "react"
import { keylessProviderTypes, providerTypeName } from "@/domains/providers"
import { createKeyPool, createVaultKey } from "@/domains/vault"
import type { VaultProject } from "@/domains/vault"
import { Button } from "@/shared/ui/button"
import { Field } from "@/shared/ui/Field"
import { FormActions } from "@/shared/ui/FormActions"
import { Modal } from "@/shared/ui/Modal"
import { Select } from "@/shared/ui/select"
import {
  defaultPoolInputForKey,
  hasProjectPool,
  keylessKeyInput,
  planKeylessKey,
} from "../model/bulkPools"
import type { BulkVaultRow } from "../model/bulkPools"

/** One per-provider outcome line: reused, created, or blocked. */
interface DefaultsResult {
  providerType: string
  message: string
}

/**
 * Run one supported keyless provider: reuse or create its keyless key with
 * no secret, then create the assigned pool unless the project holds one.
 * Returns the outcome line and whether anything changed.
 */
async function runDefaultsProvider(
  rows: BulkVaultRow[],
  projectId: string,
  providerType: string
): Promise<{ outcome: DefaultsResult; changed: boolean }> {
  const name = providerTypeName(providerType)
  const step = planKeylessKey(rows, providerType)
  if (step.outcome !== undefined) return { outcome: step.outcome, changed: false }
  const row = step.row
  const key = row === undefined
    ? await createVaultKey(keylessKeyInput(providerType)).then((created) => ({ key: created, pools: [] as BulkVaultRow["pools"] }))
    : row
  if (row === undefined) {
    const createdPool = await createKeyPool(key.key.id, defaultPoolInputForKey(key.key, projectId))
    return { outcome: { providerType, message: `${name}: created pool ${createdPool.label}` }, changed: true }
  }
  if (hasProjectPool(key.pools, projectId)) {
    return { outcome: { providerType, message: `${name}: already assigned` }, changed: false }
  }
  const createdPool = await createKeyPool(key.key.id, defaultPoolInputForKey(key.key, projectId))
  return { outcome: { providerType, message: `${name}: created pool ${createdPool.label}` }, changed: true }
}

/**
 * One-shot provisioning of the supported keyless free-tier pools for one
 * project. For each supported keyless provider the dialog reuses the owned
 * keyless key or creates one with no secret, then skips the pool when the
 * project already holds one — reruns create nothing new. Keyed pools and
 * ownership are preserved. Every call is a plain local record write — no
 * vendor request is made.
 */
export function KeylessDefaultsDialog({ rows, projects, onClose, onSaved }: {
  rows: BulkVaultRow[]
  projects: readonly VaultProject[]
  onClose: () => void
  onSaved: (notice: string) => void
}) {
  const supported = keylessProviderTypes()
  const [projectId, setProjectId] = useState("")
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [results, setResults] = useState<DefaultsResult[] | null>(null)
  async function save() {
    if (pending || !projectId || supported.length === 0) return
    setPending(true)
    setError(null)
    setResults(null)
    try {
      const outcomes: DefaultsResult[] = []
      let changed = 0
      for (const providerType of supported) {
        const stepped = await runDefaultsProvider(rows, projectId, providerType)
        outcomes.push(stepped.outcome)
        if (stepped.changed) changed += 1
      }
      setResults(outcomes)
      if (changed > 0) {
        const name = projects.find((project) => project.id === projectId)?.name ?? "project"
        onSaved(`Keyless defaults ready for ${name}`)
      } else setError("Everything is already assigned. Nothing changed")
    } catch {
      setError("The defaults did not save. Try again")
    } finally {
      setPending(false)
    }
  }
  return (
    <Modal isOpen onClose={onClose} title="Keyless defaults" maxWidth="lg">
      <div className="space-y-4">
        <p>Create the supported keyless free-tier pools ({supported.map(providerTypeName).join(", ")}) for one project. No API key is needed; existing pools and keys are reused.</p>
        <Field id="defaults-project" label="Project" hint="Only projects where you are the provider owner">
          <Select id="defaults-project" value={projectId} onValueChange={setProjectId}
            options={projects.map((entry) => ({ value: entry.id, label: entry.name }))} placeholder="No available projects" />
        </Field>
        {supported.length === 0 && <p>No supported keyless providers are configured</p>}
        {results !== null && (
          <ul className="space-y-1 text-[13px]">
            {results.map((result) => <li key={result.providerType}>{result.message}</li>)}
          </ul>
        )}
        {error && <p role="alert" className="fs-field-error">{error}</p>}
        <FormActions>
          <Button type="button" variant="outline" size="form" onClick={onClose}>Cancel</Button>
          <Button type="button" size="form" pending={pending} disabled={pending || !projectId || supported.length === 0} onClick={() => void save()}>Create defaults</Button>
        </FormActions>
      </div>
    </Modal>
  )
}
